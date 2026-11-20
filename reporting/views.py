import datetime

from django.utils import timezone
from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from tenancy.limits import patient_status
from tenancy.models import Tenant
from tenancy.permissions import Capability, CapabilityRequiredView

from . import operations, patients
from .models import ReportExport, ReportExportKind, ReportExportStatus
from .services import EXPORT_TTL_HOURS, pode_ver_export, request_export

#: Os arquivos que saem com o prontuário ou com dados de contato de toda a
#: carteira: baixados só por quem pediu, e com o código recente.
RELATORIOS_SENSIVEIS = frozenset({'acervo_pacientes', 'acervo_atendimentos', 'mailing_contatos'})


class TenantScopedView(CapabilityRequiredView):
    """Indicadores agregados: faturamento, repasse, falta, perfil da carteira.

    O PRD dá esta linha a dono, médico e gestor, e à secretaria dá "agenda
    operacional" — que é o balcão, não isto. Faturamento por competência e
    previsão de repasse ao médico não são número de recepção.
    """

    required_capability = Capability.MANAGERIAL_DASHBOARD


class HomeRedirectMixin:
    """Sem o dashboard gerencial, a página inicial passa a ser o balcão.

    Recusar com 404 seria correto e inútil: `reporting:dashboard` é o
    "Início" do sistema, e a secretária cai nele ao entrar e a cada
    breadcrumb. Um 404 na porta de entrada é defeito de navegação, não
    proteção — a proteção é não mostrar os números, e mostrar em vez deles
    a tela que é de fato a dela.
    """

    def dispatch(self, request, *args, **kwargs):
        context = request.access_context
        if context is not None and not context.can(Capability.MANAGERIAL_DASHBOARD):
            if context.can(Capability.SCHEDULE):
                return redirect('scheduling:desk')
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _parse_period(request):
    """O período da tela, e o mês corrente quando não veio nenhum.

    Data ilegível cai no padrão em vez de derrubar a página: `start` e
    `end` vêm da URL, e a URL é digitada, colada pela metade e guardada nos
    favoritos com o ano cortado. `fromisoformat` levantava `ValueError`
    direto da view e o painel de indicadores respondia erro 500 — para um
    caractere errado num parâmetro que tem padrão óbvio.

    Inverter as duas também é entrada inválida, e silenciosa: um período
    que termina antes de começar devolve todo indicador zerado, o que se
    lê como "não houve atendimento" em vez de "a data está trocada".
    """
    # Ver a mesma nota em `finance/views.py::_parse_period`: em UTC, das
    # 21h a meia-noite o dia ja virou, e o painel abria no periodo errado.
    today = timezone.localdate()

    def data(valor, padrao):
        if not valor:
            return padrao
        try:
            return datetime.date.fromisoformat(valor)
        except ValueError:
            return padrao

    start = data(request.GET.get('start'), today.replace(day=1))
    end = data(request.GET.get('end'), today)
    if end < start:
        start, end = end, start
    return start, end


class DashboardView(HomeRedirectMixin, TenantScopedView):
    """Every number on this page is labeled with its period, unit and n --
    a plain HTML table doubles as its own "tabela alternativa" (RNF-01.09)
    since there is no chart to begin with, consistent with this project's
    established no-JS-by-default UI pattern.
    """

    def get(self, request):
        start, end = _parse_period(request)
        tenant = Tenant.objects.get(id=request.access_context.tenant_id)

        indicators = {
            'active_patients': patients.active_patients_count(tenant),
            'patients_seen': patients.patients_seen(tenant, start, end),
            'new_patients': patients.new_patients_count(tenant, start, end),
            'returning_patients': patients.returning_patients_count(tenant, start, end),
            'no_show': patients.no_show_rate(tenant, start, end),
            'age': patients.age_distribution(tenant, end),
            'revenue_by_competence': operations.revenue_by_competence(tenant, start, end),
            'cash_received': operations.cash_received(tenant, start, end),
            'outstanding_balance': operations.outstanding_balance(tenant, end),
            'doctor_share_forecast': operations.doctor_share_forecast(tenant, start, end),
            'payment_category': operations.payment_category_breakdown(tenant, start, end),
        }
        return render(request, 'reporting/dashboard.html', {
            'start': start, 'end': end, 'indicators': indicators,
            # O consumo do plano vem de `tenancy.limits`, e não recontado
            # aqui: `LimitStatus` já sabe o que é "perto do fim" (80 %) e o
            # que é "sem vaga", e é a mesma fonte que bloqueia o cadastro
            # nas seis portas. Um segundo cálculo na tela acabaria dizendo
            # que ainda cabe um paciente enquanto o cadastro recusa.
            'plano': patient_status(tenant),
            'email_suporte': settings.LEADS_EMAIL,
            'tenant': tenant,
        })


class AcervoView(CapabilityRequiredView):
    """Levar os dados embora: cadastro e prontuário, em Markdown ou JSON.

    Fica na administração da clínica porque o direito é da CONTRATANTE, e
    não de quem opera o balcão — cláusula 13.1 do contrato de adesão. Por
    isso a tela exige `MANAGE_ORGANIZATION`, que só o dono tem.

    O acervo **clínico** exige, além dela, `READ_CLINICAL`: o dono que não
    é médico administra a clínica e não abre prontuário, e não seria
    coerente que não pudesse ler uma nota na tela e pudesse baixar todas
    num arquivo. Quando falta, a tela diz por que o botão não está lá em
    vez de simplesmente escondê-lo — sumir sem explicação faz a pessoa
    procurar defeito onde há regra.

    Quem decide de verdade é `request_export`, que confere as capacidades
    do relatório pedido. Esta tela só evita oferecer o que seria negado.
    """

    required_capability = Capability.MANAGE_ORGANIZATION

    def get(self, request):
        from tenancy.selectors import scope_to_tenant

        # A lista mostra so o que este vinculo poderia baixar.
        #
        # Antes ela era escopada apenas por inquilino, e o acervo CLINICO --
        # que exige MANAGE_ORGANIZATION **e** READ_CLINICAL para ser pedido --
        # aparecia para o dono que nao e medico assim que qualquer medico da
        # clinica exportasse um. Ver `pode_ver_export`.
        permitidos = [
            nome for nome in ('acervo_pacientes', 'acervo_atendimentos')
            if pode_ver_export(request.access_context, nome)
        ]
        # E só o que **esta pessoa** pediu: desde 2026-11-20 o acervo é
        # baixado só por quem o pediu (`RELATORIOS_SENSIVEIS`), e listar o
        # do colega seria oferecer um link que dá 404.
        recentes = scope_to_tenant(
            ReportExport.objects.filter(
                report_name__in=permitidos, requested_by_id=request.access_context.membership_id,
            ),
            request.access_context,
        ).order_by('-created_at')[:10]
        return render(request, 'reporting/acervo.html', {
            'pode_clinico': request.access_context.can(Capability.READ_CLINICAL),
            'recentes': recentes,
            'horas': EXPORT_TTL_HOURS,
        })

    def post(self, request):
        from tenancy.models import Membership

        from .services import ReportNotAllowed, ReportNotFound

        nome = request.POST.get('acervo')
        formato = request.POST.get('formato')
        # Lista fechada, e não o que vier no POST: `request_export` já
        # recusa nome desconhecido, mas deixar a tela aceitar qualquer
        # string faria a trilha de auditoria encher de tentativas que são
        # só erro de digitação em link colado.
        if nome not in {'acervo_pacientes', 'acervo_atendimentos'}:
            raise Http404
        if formato not in {ReportExportKind.MD, ReportExportKind.JSON}:
            raise Http404

        # O acervo inteiro num arquivo é o pedido mais valioso para quem
        # tiver só a senha de alguém: exige o segundo fator, confirmado há
        # pouco (revisão de 2026-11-02, S5). Sem dispositivo, a tela leva à
        # configuração; com ele, à reconfirmação, e volta para cá.
        from django.contrib import messages
        from django.urls import reverse
        from django.utils.http import urlencode

        from accounts import mfa

        volta = reverse('reporting:acervo')
        if not mfa.user_has_confirmed_totp(request.user):
            messages.warning(
                request,
                'Para exportar o acervo, configure antes o código do celular (segundo fator).',
            )
            return redirect(f'{reverse("accounts:mfa-setup")}?{urlencode({"next": volta})}')
        if not mfa.mfa_verified_recently(request):
            return mfa.redirect_to_mfa_confirm(request, destino=volta)

        membership = Membership.objects.filter(
            id=request.access_context.membership_id,
        ).first()
        try:
            export = request_export(
                request.access_context, membership, nome, {}, kind=formato,
            )
        except (ReportNotAllowed, ReportNotFound):
            raise Http404
        return redirect('reporting:export-detail', export_id=export.id)


#: Os relatórios que o formulário da tela de Indicadores pede.
RELATORIOS_DOS_INDICADORES = frozenset({'patients_seen_detail'})


class PainelView(TenantScopedView):
    """Dashboard: perfil da carteira e da atividade, por clínica e médico.

    Mesma capacidade dos Indicadores (`MANAGERIAL_DASHBOARD`: responsável,
    gestor e médico; a secretaria não). O escopo — clínica da sessão, médico
    pelo papel — é decidido em `painel.resolver_escopo`, nunca aqui: esta
    view só desenha o que ele devolve.

    `?baixar=<seção>` devolve aquela tabela em CSV, agregada, sem linha de
    paciente. Cabe na requisição (são dezenas de linhas) e fica na trilha
    com a seção e o médico escolhido — sem números, que não são de quem
    audita.
    """

    def get(self, request):
        from audit.services import record_audit_event

        from . import painel
        from .exporters import export_csv

        escopo = painel.resolver_escopo(request.access_context, request.GET)
        secao = request.GET.get('baixar')
        if secao:
            if secao not in painel.SECOES_CSV:
                raise Http404
            resultado = painel.linhas_csv(escopo, secao)
            if resultado is None:
                raise Http404
            colunas, linhas = resultado
            record_audit_event(
                request.access_context.user_id, request.access_context.tenant_id,
                'reporting.painel_csv', object_type='painel', object_id=None,
                integrity_metadata={
                    'secao': secao, 'medico': escopo.medico_id,
                    'inicio': escopo.inicio.isoformat(), 'fim': escopo.fim.isoformat(),
                },
            )
            resposta = HttpResponse(
                '﻿' + export_csv(linhas, colunas), content_type='text/csv; charset=utf-8',
            )
            resposta['Content-Disposition'] = (
                f'attachment; filename="dashboard-{secao}-{escopo.inicio:%Y%m%d}-{escopo.fim:%Y%m%d}.csv"'
            )
            resposta['X-Content-Type-Options'] = 'nosniff'
            resposta['Cache-Control'] = 'private, no-store'
            return resposta

        from tenancy.models import Membership, MembershipStatus

        clinicas = (
            Membership.objects.filter(user_id=request.user.id, status=MembershipStatus.ACTIVE)
            .select_related('tenant').order_by('tenant__legal_name')
        )
        from django.utils.http import urlencode

        tenant = Tenant.objects.get(id=escopo.tenant_id)
        filtro = {'medico': escopo.medico_id} if escopo.ve_clinica_inteira and escopo.medico_id else {}
        if escopo.periodo == 'personalizado':
            filtro.update(inicio=escopo.inicio.isoformat(), fim=escopo.fim.isoformat())
        else:
            filtro['periodo'] = escopo.periodo
        return render(request, 'reporting/painel.html', {
            'escopo': escopo,
            'qs': urlencode(filtro),
            'tenant': tenant,
            'clinicas': [m.tenant for m in clinicas],
            'periodos': painel.PERIODOS,
            'resumo': painel.resumo(escopo),
            'mensal': painel.mensal(escopo),
            'idade': painel.idade(escopo),
            'sexo': painel.sexo(escopo),
            'uf': painel.uf(escopo),
            'municipio': painel.municipio(escopo, limite=painel.TOPO),
            'origem': painel.origem(escopo),
            'pagamento': painel.pagamento(escopo),
            'convenios': painel.convenios(escopo, limite=painel.TOPO),
            'diagnosticos': painel.diagnosticos(escopo, limite=painel.TOPO),
            'max_meses': painel.MAX_MESES,
            'topo': painel.TOPO,
            'limiar': painel.SMALL_CELL_THRESHOLD,
        })


class MailingView(CapabilityRequiredView):
    """Lista de e-mails para mailing externo: só de quem consentiu.

    Só o responsável (`MANAGE_ORGANIZATION`): a clínica é a controladora, e
    quem decide mandar dados de pacientes a uma ferramenta de terceiros é
    quem responde por ela — o mesmo critério do acervo (cláusula 13.1).

    Três travas antes de sair qualquer linha, e as três ficam na trilha pelo
    motor de exportação:

    - o **segundo fator confirmado há pouco**, como no acervo: a lista de
      e-mails de uma clínica de neurologia é o arquivo que mais vale a quem
      tiver só a senha de alguém;
    - a **declaração de uso**, marcada a cada pedido e gravada nos
      parâmetros da exportação — é a prova de que quem baixou foi avisado
      de que a lista só serve a quem consentiu e que cada mensagem leva o
      link de descadastro;
    - o **escopo** reconferido no servidor: o médico escolhido tem de ser
      desta clínica, senão a lista sai vazia (nunca a da clínica inteira).
    """

    required_capability = Capability.MANAGE_ORGANIZATION

    def post(self, request):
        from django.contrib import messages
        from django.urls import reverse
        from django.utils.http import urlencode

        from accounts import mfa
        from tenancy.models import Membership

        from . import painel
        from .services import ReportNotAllowed, ReportNotFound

        escopo = painel.resolver_escopo(request.access_context, request.POST)
        volta = reverse('reporting:painel')
        if escopo.medico_id:
            volta = f'{volta}?{urlencode({"medico": escopo.medico_id})}'
        # Médico pedido e não reconhecido (saiu da clínica, id adulterado):
        # o escopo cairia na clínica inteira, e a lista exportada não seria a
        # que a tela prometeu. Recusa em vez de alargar.
        if (request.POST.get('medico') or '').strip() and not escopo.medico_id:
            messages.error(
                request,
                'O médico escolhido não está mais nesta clínica. Escolha de novo '
                'e exporte outra vez.',
            )
            return redirect(volta)
        if request.POST.get('declaracao') != 'sim':
            messages.error(
                request,
                'Para exportar o mailing, marque a declaração de uso: a lista é só para '
                'quem consentiu, e cada mensagem precisa levar o link de descadastro.',
            )
            return redirect(volta)
        if not mfa.user_has_confirmed_totp(request.user):
            messages.warning(
                request,
                'Para exportar o mailing, configure antes o código do celular (segundo fator).',
            )
            return redirect(f'{reverse("accounts:mfa-setup")}?{urlencode({"next": volta})}')
        if not mfa.mfa_verified_recently(request):
            return mfa.redirect_to_mfa_confirm(request, destino=volta)

        membership = Membership.objects.filter(id=request.access_context.membership_id).first()
        try:
            export = request_export(
                request.access_context, membership, 'mailing_contatos',
                {'medico': escopo.medico_id, 'declaracao': True}, kind=ReportExportKind.CSV,
            )
        except (ReportNotAllowed, ReportNotFound):
            raise Http404
        return redirect('reporting:export-detail', export_id=export.id)


class ExportRequestView(TenantScopedView):
    def post(self, request):
        from django.contrib import messages

        from tenancy.models import Membership

        from .services import ReportNotAllowed, ReportNotFound

        membership = Membership.objects.filter(id=request.access_context.membership_id).first()
        report_name = request.POST.get('report_name')
        # Esta porta é a dos indicadores por período, e só deles. O mailing
        # do Dashboard tem a dele (`MailingView`), que exige o segundo fator
        # recente e a declaração de uso; aceitar qualquer nome aqui deixaria
        # o mesmo arquivo sair por esta, sem nenhuma das duas.
        if report_name not in RELATORIOS_DOS_INDICADORES:
            raise Http404
        # Datas lidas aqui (auditoria de 2026-11-11): vazias ou ilegíveis,
        # elas estouravam dentro do relatório **depois** de a exportação ter
        # sido criada como "Processando" — erro 500, e a linha presa nesse
        # estado para sempre. Relatório desconhecido, ou num formato que ele
        # não tem, é 404, como na tela do acervo.
        try:
            parameters = {
                'start': datetime.date.fromisoformat(request.POST.get('start') or '').isoformat(),
                'end': datetime.date.fromisoformat(request.POST.get('end') or '').isoformat(),
            }
        except ValueError:
            messages.error(request, 'Informe as datas de início e fim do período.')
            return redirect('reporting:dashboard')
        try:
            export = request_export(
                request.access_context, membership, report_name, parameters, kind=ReportExportKind.CSV,
            )
        except (ReportNotAllowed, ReportNotFound):
            raise Http404
        return redirect('reporting:export-detail', export_id=export.id)


class ExportDetailView(TenantScopedView):
    def get(self, request, export_id):
        from tenancy.selectors import scope_to_tenant

        export = get_object_or_404(scope_to_tenant(ReportExport.objects.all(), request.access_context), id=export_id)
        # A capacidade e declarada POR RELATORIO (`reporting/apps.py`) e era
        # conferida so em `request_export`. Escopar por inquilino nao basta
        # aqui: o arquivo do acervo clinico tem o prontuario de todos os
        # pacientes, e quem alcanca esta tela nem sempre pode le-lo.
        if not pode_ver_export(request.access_context, export.report_name):
            raise Http404
        return render(request, 'reporting/export_detail.html', {'export': export})


class ExportDownloadView(TenantScopedView):
    def get(self, request, export_id):
        from tenancy.selectors import scope_to_tenant

        export = get_object_or_404(scope_to_tenant(ReportExport.objects.all(), request.access_context), id=export_id)
        # A capacidade e declarada POR RELATORIO (`reporting/apps.py`) e era
        # conferida so em `request_export`. Escopar por inquilino nao basta
        # aqui: o arquivo do acervo clinico tem o prontuario de todos os
        # pacientes, e quem alcanca esta tela nem sempre pode le-lo.
        if not pode_ver_export(request.access_context, export.report_name):
            raise Http404
        if export.status != ReportExportStatus.READY or not export.storage_key:
            raise Http404
        # O acervo e o mailing pedem o código no **pedido**; o download não
        # pedia, nem conferia quem pediu, nem deixava rastro. Nas 24 h do
        # arquivo, quem tivesse a senha e um navegador confiável de outro
        # responsável baixava o prontuário inteiro sem código e sem trilha
        # (auditoria externa de 2026-11-20). Agora o arquivo sensível é de
        # quem o pediu, sai com o código recente, e todo download é anotado.
        from accounts import mfa

        if export.report_name in RELATORIOS_SENSIVEIS:
            if export.requested_by_id != request.access_context.membership_id:
                raise Http404
            if not mfa.mfa_verified_recently(request):
                return mfa.redirect_to_mfa_confirm(request)
        # O prazo vale na hora do download, e não quando a limpeza passar.
        # Dependia de `expire_exports`: com o beat atrasado ou o worker
        # parado, o arquivo do acervo -- o prontuário da clínica inteira --
        # continuava baixável depois das 24 h prometidas, por tempo
        # indeterminado (auditoria de 2026-10-09, ND-1121-009).
        from django.utils import timezone

        if export.expires_at is not None and export.expires_at <= timezone.now():
            raise Http404
        from .services import FORMATOS

        with open(export.storage_key, 'rb') as fh:
            content = fh.read()
        # Extensao e tipo saem do formato gravado, e nao de `csv` fixo. Um
        # Markdown entregue como `text/csv` chamado `.csv` abre no Excel
        # como uma coluna de lixo -- o arquivo estava certo e a pessoa
        # concluiria que a exportacao esta quebrada.
        extensao, tipo = FORMATOS.get(export.kind, ('txt', 'text/plain; charset=utf-8'))
        response = HttpResponse(content, content_type=tipo)
        response['Content-Disposition'] = (
            f'attachment; filename="{export.report_name}.{extensao}"'
        )
        # `nosniff` porque parte disto e Markdown e JSON vindos de texto
        # que o proprio usuario escreveu: sem ele, um navegador que
        # adivinhe o tipo pode decidir renderizar em vez de baixar.
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        from audit.services import record_audit_event

        record_audit_event(
            request.access_context.user_id, request.access_context.tenant_id,
            'reporting.export_downloaded', object_type='report_export', object_id=export.id,
            outcome='success', integrity_metadata={'report': export.report_name, 'kind': export.kind},
        )
        return response
