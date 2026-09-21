import datetime

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from tenancy.limits import patient_status
from tenancy.models import Tenant
from tenancy.permissions import Capability, CapabilityRequiredView

from . import operations, patients
from .models import ReportExport, ReportExportKind, ReportExportStatus
from .services import EXPORT_TTL_HOURS, request_export


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
    today = datetime.date.today()

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
            'location': patients.location_distribution(tenant),
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

        recentes = scope_to_tenant(
            ReportExport.objects.filter(report_name__startswith='acervo_'),
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


class ExportRequestView(TenantScopedView):
    def post(self, request):
        from tenancy.models import Membership

        membership = Membership.objects.filter(id=request.access_context.membership_id).first()
        report_name = request.POST.get('report_name')
        parameters = {'start': request.POST.get('start'), 'end': request.POST.get('end')}
        export = request_export(request.access_context, membership, report_name, parameters, kind=ReportExportKind.CSV)
        return redirect('reporting:export-detail', export_id=export.id)


class ExportDetailView(TenantScopedView):
    def get(self, request, export_id):
        from tenancy.selectors import scope_to_tenant

        export = get_object_or_404(scope_to_tenant(ReportExport.objects.all(), request.access_context), id=export_id)
        return render(request, 'reporting/export_detail.html', {'export': export})


class ExportDownloadView(TenantScopedView):
    def get(self, request, export_id):
        from tenancy.selectors import scope_to_tenant

        export = get_object_or_404(scope_to_tenant(ReportExport.objects.all(), request.access_context), id=export_id)
        if export.status != ReportExportStatus.READY or not export.storage_key:
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
        return response
