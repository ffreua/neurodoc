import re
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.forms import modelform_factory
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from audit.services import record_audit_event
from patients.models import Patient
from scheduling.returns import INTERVALOS_MESES, agendar_retorno
from tenancy.permissions import Capability, CapabilityRequiredView
from tenancy.selectors import scope_to_tenant

from . import carry_forward as cf
from . import finalization, selectors
from .cranial_nerves import upsert_cranial_nerve_finding
from exams.models import ExamScale
from exams.recording import (
    mark_group_normal, record_scale, save_axis, undo_group_normal,
)
from exams.selectors import build_tree, resolve_template

from .examination import group_findings_by_domain, upsert_finding
from .forms import (
    AmendmentForm, DiagnosisForm, EncounterForm, ExamResultForm, FindingForm,
    FreeTextEncounterForm, LabValueForm,
    MedicationForm,
)
from .models import (
    EncounterKind,
    Encounter, EncounterDiagnosis, EncounterStatus, ExaminationDomain, ExaminationFinding,
    ExamResult, ExtractionStatus, LabValue, Medication, ReviewAction,
)


def _first_error(form):
    """Primeira mensagem de erro do formulário, em texto corrido."""
    for field, errors in form.errors.items():
        if not errors:
            continue
        label = form.fields[field].label if field in form.fields else ''
        return f'{label}: {errors[0]}' if label else errors[0]
    return 'Não foi possível salvar.'


def _texto_do_erro(exc):
    """A mensagem de uma exceção, legível na tela.

    `str()` de uma `ValidationError` do Django devolve a **repr da lista**:
    `["Escolha o lado de X"]`, com colchetes e aspas. Era o que aparecia na
    faixa vermelha do prontuário toda vez que faltava a lateralidade de um
    achado — a frase certa, vestida de estrutura de dados.

    `messages` é o atributo que a própria `ValidationError` expõe para
    isso; qualquer outra exceção cai no `str()` de sempre.
    """
    mensagens = getattr(exc, 'messages', None)
    if mensagens:
        return ' '.join(str(m) for m in mensagens)
    return str(exc)


#: Um identificador de painel desta tela, e nada mais. Serve para validar
#: a **forma** do que chega no POST, em vez de guardar a lista das sete
#: abas aqui -- uma lista que envelheceria na primeira aba nova, e que ja
#: existe no template, onde ela pertence.
_ABA = re.compile(r'tab-[a-z-]{3,24}')


def _aba_pedida(request):
    """De que aba o envio partiu, para a tela voltar para ela.

    A tela estruturada tem sete abas e um formulario em varias delas. O
    servidor redireciona para a mesma pagina depois de gravar, e
    `static/duralux/app.js::tabFromHash` reabre a aba cujo id esta no
    endereco -- mas o redirecionamento de "Salvar historia", "Salvar
    conduta" e "Adicionar hipotese" saia **sem** ancora. Quem acabava de
    salvar era devolvido para a primeira aba, com o formulario que
    enviara fora da tela. Em quatro das sete, o trabalho aparecia salvo;
    nas outras, parecia ter sumido.

    O valor vem de um campo oculto no proprio formulario, e nao de um mapa
    de campo-para-aba escrito aqui: quem sabe em que aba um formulario
    esta e o template que o desenha, e um mapa aqui seria a segunda lista
    a envelhecer.

    **Conferida pela forma, nao pela lista.** O valor vai para o fragmento
    de uma URL de redirecionamento; qualquer coisa que nao seja um
    identificador de painel e descartada em silencio, e a pessoa cai no
    topo da pagina -- que e o comportamento de antes, nao um erro novo.
    """
    pedida = (request.POST.get('aba') or '').strip()
    return pedida if _ABA.fullmatch(pedida) else ''


def _detalhe(encounter, ancora=''):
    url = reverse('clinical:detail', args=[encounter.id])
    return f'{url}#{ancora}' if ancora else url


def _ancora_de_adendos(encounter):
    """Onde o bloco de adendos mora, em cada uma das duas telas.

    O estruturado tem abas e o bloco e o painel `#tab-adendos`; o texto
    livre e uma coluna unica e o bloco e o cartao `#adendos`. Mandar os
    dois para a mesma ancora deixaria um dos dois abrindo no topo da
    pagina depois de registrar o adendo -- e, no texto livre, com o
    adendo recem-escrito quatro telas abaixo, parecendo que nao gravou.

    Aqui, e nao escrito nas views, porque sao tres usos: as duas recusas e
    o sucesso. Um deles ficaria para tras na proxima vez.
    """
    return 'tab-adendos' if encounter.kind == EncounterKind.STRUCTURED else 'adendos'


def _blocked(request, encounter, message, anchor=''):
    """Recusa uma ação sem tirar quem usa o sistema de dentro dele.

    Antes cada recusa devolvia uma página de texto cru — "3", o dict de
    erros do formulário, uma frase em inglês. Agora volta para o
    atendimento com a mensagem na tela, na aba de onde a ação partiu.
    """
    messages.error(request, message)
    url = reverse('clinical:detail', args=[encounter.id])
    return redirect(f'{url}#{anchor}' if anchor else url)

class TenantScopedView(CapabilityRequiredView):
    """Base do prontuário: ler exige papel médico, escrever exige habilitação.

    A capacidade sai do método HTTP em vez de ser anotada view a view.
    Neste app a correspondência é exata — toda leitura é GET e todo POST
    altera o registro clínico — e uma regra derivada não pode ser esquecida
    na próxima view que alguém acrescentar. Anotar vinte e seis classes à
    mão garantiria que a vigésima sétima nascesse sem anotação e aberta.

    A separação entre ler e escrever é a do PRD: o papel `doctor` lê o
    prontuário; finalizar atendimento exige também `PhysicianProfile`
    verificado. Secretaria e gestor não passam em nenhum dos dois.
    """

    SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

    def dispatch(self, request, *args, **kwargs):
        self.required_capability = (
            Capability.READ_CLINICAL if request.method in self.SAFE_METHODS
            else Capability.WRITE_CLINICAL
        )
        return super().dispatch(request, *args, **kwargs)


def _doctor_membership(request):
    from tenancy.models import Membership, MembershipStatus, Role

    return Membership.objects.filter(
        tenant_id=request.access_context.tenant_id, user_id=request.access_context.user_id,
        status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).first()


class PatientEvolutionView(TenantScopedView):
    """A evolução do paciente no tempo, em gráfico.

    Devolve um **fragmento** de HTML, e não uma página: quem o pede é o
    sobreposto da linha do tempo, e carregar sob demanda é o que permite a
    tela do prontuário continuar do tamanho que é. Calcular todas as séries
    a cada abertura da linha do tempo custaria uma varredura de achados e
    laudos para quem só queria ver a lista de consultas.

    A série escolhida vem por `?serie=`; sem ela, abre a primeira — que é
    uma escala, quando há alguma, porque é a medida que o médico escolheu
    aplicar.
    """

    def get(self, request, patient_id):
        from exams.models import ExamScale

        from . import series as series_mod

        patient = get_object_or_404(
            scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id,
        )
        disponiveis = series_mod.series_do_paciente(request.access_context, patient)
        escolhida = None
        pedida = request.GET.get('serie')
        for serie in disponiveis:
            if serie['chave'] == pedida:
                escolhida = serie
                break
        if escolhida is None and disponiveis:
            escolhida = disponiveis[0]

        desenho = None
        if escolhida is not None:
            dominio = None
            if escolhida['tipo'] == series_mod.ESCALA:
                cadastro = ExamScale.objects.filter(
                    tenant_id=request.access_context.tenant_id, code=escolhida['codigo'],
                ).values_list('min_score', 'max_score').first()
                if cadastro and cadastro[0] is not None and cadastro[1] is not None:
                    dominio = cadastro
            desenho = series_mod.desenhar(escolhida, escala_cadastrada=dominio)

        return render(request, 'clinical/_evolucao.html', {
            'patient': patient,
            'series': disponiveis,
            'serie': escolhida,
            'desenho': desenho,
        })


class PatientsByDiagnosisView(TenantScopedView):
    """Quem, na carteira desta clínica, tem este diagnóstico.

    Vive no app clínico, e não junto da lista de pacientes, porque é aí que
    fica a fronteira de autorização: `/app/clinical/` inteiro exige
    `READ_CLINICAL`, e esta tela responde com informação de prontuário. A
    lista de pacientes do menu administrativo é aberta aos quatro papéis —
    acrescentar um filtro por CID lá entregaria "quem aqui tem B24" a
    qualquer pessoa com acesso à agenda.

    `TenantScopedView` deriva a capacidade do método HTTP, e por isso esta
    view é `GET`: a busca não altera nada, e um POST aqui passaria a exigir
    `WRITE_CLINICAL` sem que ninguém entendesse por quê.
    """

    def get(self, request):
        from .por_cid import ATIVAS, LEITURAS, ROTULOS, buscar

        termo = (request.GET.get('q') or '').strip()
        leitura = request.GET.get('certeza') or ATIVAS
        if leitura not in LEITURAS:
            leitura = ATIVAS
        arquivados = request.GET.get('arquivados') == '1'
        resultados = buscar(
            request.access_context, termo, leitura=leitura,
            incluir_arquivados=arquivados, page=request.GET.get('page', 1),
        )
        return render(request, 'clinical/por_cid.html', {
            'termo': termo,
            'resultados': resultados,
            'leitura': leitura,
            'leituras': [(chave, ROTULOS[chave]) for chave in LEITURAS],
            'arquivados': arquivados,
        })


class DiagnosisLookupView(TenantScopedView):
    """Autocomplete do CID-10, por código ou por descrição.

    O catálogo é global (não é dado do inquilino), mas o endpoint continua
    exigindo sessão autenticada: quem não tem vínculo ativo não enumera
    catálogo nem qualquer outra coisa daqui.
    """

    def get(self, request):
        from catalogs.selectors import search_diagnosis_codes

        term = request.GET.get('q', '')
        return JsonResponse({'results': search_diagnosis_codes(term)})


class TimelineView(TenantScopedView):
    def get(self, request, patient_id):
        patient = get_object_or_404(scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id)
        # A ordem vem da URL e é validada no selector; o que chega aqui é só
        # repassado, nunca interpolado numa consulta.
        ordenar = request.GET.get('ordenar', selectors.ORDEM_PADRAO)
        if ordenar not in selectors.ORDENS_DA_GRADE:
            ordenar = selectors.ORDEM_PADRAO
        decrescente = request.GET.get('desc') == '1'
        encounters = selectors.patient_timeline(
            request.access_context, patient, ordenar=ordenar, decrescente=decrescente,
        )
        return render(request, 'clinical/timeline.html', {
            'patient': patient, 'encounters': encounters,
            'ordenar': ordenar, 'decrescente': decrescente,
        })


class EncounterCreateView(TenantScopedView):
    def post(self, request, patient_id):
        patient = get_object_or_404(scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id)
        membership = _doctor_membership(request)
        if membership is None:
            raise Http404
        # O tipo vem do botão que foi clicado. Valor desconhecido cai no
        # estruturado — que é o prontuário completo, e errar para o lado de
        # pedir mais registro é o erro aceitável aqui.
        kind = request.POST.get('kind')
        if kind not in EncounterKind.values:
            kind = EncounterKind.STRUCTURED
        from scheduling.models import Appointment, AppointmentStatus

        today = timezone.localdate()
        candidates = list(
            Appointment.objects.filter(
                tenant_id=request.access_context.tenant_id,
                patient=patient,
                physician_membership=membership,
                status__in=[AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_PROGRESS],
                encounters__isnull=True,
                starts_at__date__range=(today - timedelta(days=1), today + timedelta(days=1)),
            ).order_by('-starts_at')[:2]
        )
        # Só liga automaticamente quando a agenda responde sem ambiguidade.
        # Um check-in antigo ou dois horários abertos do mesmo paciente não
        # podem decidir silenciosamente qual cobrança pertence ao prontuário.
        appointment = candidates[0] if len(candidates) == 1 else None
        encounter = Encounter.objects.create(
            tenant_id=request.access_context.tenant_id, patient=patient, physician_membership=membership,
            appointment=appointment, occurred_at=timezone.now(), status=EncounterStatus.DRAFT, kind=kind,
        )
        source = cf.default_source_encounter(encounter)
        if source is not None:
            cf.carry_forward(request.access_context, encounter, source)
        return redirect('clinical:detail', encounter_id=encounter.id)


class EncounterDetailView(TenantScopedView):
    def get(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        pending_items = list(
            encounter.carry_forward_items.filter(review_action='pending')
            .select_related('source_encounter')
        )
        # Rótulo e valor legíveis: a tela mostrava `plan_text` com o dicionário
        # cru ao lado, e a hipótese como `diagnosis:<uuid>`.
        for item in pending_items:
            item.described = cf.describe_item(item)
        findings = list(
            encounter.examination_findings.select_related('template_node')
            .order_by('domain', 'item_code', 'side')
        )
        template = resolve_template(
            request.access_context.tenant_id, request.access_context.membership_id,
        )
        scales = list(
            ExamScale.objects
            .filter(tenant_id=request.access_context.tenant_id, active=True)
            .prefetch_related('items')
        )
        # Escalas já aplicadas neste atendimento, para o formulário reabrir
        # preenchido em vez de exigir digitar tudo de novo.
        scale_values = {
            finding.item_code.split('.', 1)[1]: finding
            for finding in findings
            if finding.item_code.startswith('escala.')
        }
        # Um template por tipo. O de texto livre é uma página só, sem abas:
        # o ponto dele é não fazer quem tem pressa navegar. Os dois recebem
        # o mesmo contexto, e os blocos que os dois usam — medicação,
        # hipóteses, documentos — são os mesmos parciais.
        livre = encounter.kind == EncounterKind.FREE_TEXT
        template_da_tela = 'clinical/detail_livre.html' if livre else 'clinical/detail.html'
        # Na tela de texto livre os campos ficam FORA do `<form>` (medicação e
        # hipóteses trazem formulário próprio, e HTML não aninha formulário):
        # o formulário é declarado por `form=` em cada campo. Ver
        # `FreeTextEncounterForm`.
        FormularioDaTela = FreeTextEncounterForm if livre else EncounterForm
        return render(request, template_da_tela, {
            'encounter': encounter, 'form': FormularioDaTela(instance=encounter),
            'finding_form': FindingForm(), 'diagnosis_form': DiagnosisForm(),
            'amendment_form': AmendmentForm(), 'pending_carry_forward': pending_items,
            'findings': findings,
            'findings_by_domain': group_findings_by_domain(findings),
            'exam_template': template,
            'exam_tree': build_tree(template, findings),
            # Atendimento finalizado continua legível, mas os controles do
            # roteiro saem desabilitados — o servidor já recusa a gravação,
            # e a tela não deve sugerir que ainda dá para editar.
            'exam_readonly': not encounter.is_editable(),
            'scales': scales,
            'scale_values': scale_values,
            'diagnoses': encounter.diagnoses.all().order_by('rank'),
            'amendments': encounter.amendments.all().order_by('authored_at'),
            # O que falta para finalizar, tudo de uma vez: a tela mostra a
            # lista antes do clique em vez de recusar um requisito por vez.
            'finalize_pending': finalization.missing_requirements(encounter),
            # Os intervalos vêm de `scheduling.returns`, e não de uma lista
            # no template: acrescentar "18 meses" deve aparecer na tela sem
            # que ninguém precise lembrar de uma segunda lista.
            'retorno_intervalos': INTERVALOS_MESES,
            # O modal de descarte mostra o que se perde e por que, quando for
            # o caso, não se pode descartar.
            'discard_summary': finalization.discard_summary(encounter),
            'discard_has_content': finalization.has_content(encounter),
            'discard_blockers': finalization.discard_blockers(encounter),
            # A consulta anterior vai renderizada junto com a página, e não
            # buscada por JavaScript quando a gaveta abre: são poucos campos,
            # já estão no banco, e o médico que abre a gaveta está no meio de
            # uma frase — uma espera de rede ali é uma frase interrompida.
            'consulta_anterior': selectors.consulta_anterior(request.access_context, encounter),
            **self._extra_tabs(request, encounter),
        })

    def _extra_tabs(self, request, encounter):
        """Medicações, resultados de exame e o painel de apoio da IA.

        Os rascunhos da IA vêm junto do resultado a que pertencem: o médico
        revisa o rascunho olhando o exame, não numa fila de artefatos
        separada do prontuário.
        """
        from ai.extraction import latest_draft
        from ai.services import latest_diagnostic_support

        medications = list(encounter.medications.all())
        # Um formulário de edição por linha, já preenchido. O prefixo é o
        # id da medicação: com dez linhas na tela, campos sem prefixo
        # repetiriam `id_dose` dez vezes, e o autocomplete preencheria a
        # dose da linha errada.
        for medication in medications:
            medication.edit_form = MedicationForm(
                instance=medication, prefix=_prefixo_da_medicacao(medication),
            )
        exam_results = list(
            encounter.exam_results.select_related('attachment').prefetch_related('lab_values')
        )
        for result in exam_results:
            values = list(result.lab_values.all())
            result.values_out = [v for v in values if v.flag in ('low', 'high', 'abnormal')]
            result.values_in = [v for v in values if v.flag == 'normal']
            result.values_unknown = [v for v in values if v.flag == 'no_reference']
            result.draft = (
                latest_draft(result)
                if result.extraction_status in (ExtractionStatus.READY, ExtractionStatus.ACCEPTED,
                                                ExtractionStatus.REJECTED)
                else None
            )
            result.display_extraction_status = result.extraction_status
            result.display_extraction_status_label = result.get_extraction_status_display()
            if encounter.status == EncounterStatus.FINALIZED and result.draft is not None:
                if result.draft.review_state == 'accepted':
                    result.display_extraction_status = ExtractionStatus.ACCEPTED
                    result.display_extraction_status_label = ExtractionStatus.ACCEPTED.label
                elif result.draft.review_state == 'rejected':
                    result.display_extraction_status = ExtractionStatus.REJECTED
                    result.display_extraction_status_label = ExtractionStatus.REJECTED.label

        support_job, support_artifact = latest_diagnostic_support(encounter)
        support_hypotheses, support_steps = [], []
        if support_artifact is not None:
            from ai.schemas import PRIORITY_LABELS, PRIORITY_TONES, STEP_CATEGORY_LABELS

            result = support_artifact.result or {}
            for item in result.get('hypotheses') or []:
                priority = item.get('priority', 'insufficient_evidence')
                support_hypotheses.append({
                    **item,
                    'priority_label': PRIORITY_LABELS.get(priority, priority),
                    'priority_tone': PRIORITY_TONES.get(priority, 'dark'),
                })
            for step in result.get('suggested_next_steps') or []:
                category = step.get('category', 'other')
                support_steps.append({
                    **step,
                    'category_label': STEP_CATEGORY_LABELS.get(category, category),
                })

        return {
            'medications': medications,
            'medication_form': MedicationForm(),
            'exam_results': exam_results,
            'exam_result_form': ExamResultForm(),
            'lab_value_form': LabValueForm(),
            'support_job': support_job,
            'support_artifact': support_artifact,
            'support_hypotheses': support_hypotheses,
            'support_steps': support_steps,
            'support_result': (support_artifact.result if support_artifact else {}) or {},
        }


class EncounterAutosaveView(TenantScopedView):
    """Grava a parte do prontuário que veio no envio.

    Duas coisas importam aqui:

    - **grava só os campos enviados.** A tela divide história e conduta em
      abas; validar o formulário inteiro faria salvar a história apagar a
      conduta, porque os campos da outra aba chegam ausentes e o ModelForm
      os gravaria em branco.
    - **responde conforme quem perguntou.** Chamada por `fetch` (o autosave)
      devolve JSON com a versão nova; envio normal de formulário volta para
      a tela com mensagem, em vez de deixar o navegador numa página escrita
      "3".
    """

    #: Campos que a tela pode enviar; qualquer outro é ignorado.
    EDITABLE = tuple(EncounterForm.Meta.fields)

    def _wants_json(self, request):
        return (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', '')
        )

    def _fail(self, request, encounter, message, status):
        if self._wants_json(request):
            return JsonResponse({'ok': False, 'error': message}, status=status)
        messages.error(request, message)
        return redirect(_detalhe(encounter, _aba_pedida(request)))

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return self._fail(
                request, encounter,
                'Atendimento finalizado: o registro não pode mais ser alterado. '
                'Use um adendo.', 409,
            )
        # Obrigatória, e não "se vier": ausente, a conferência era pulada
        # por inteiro e um envio sem o campo sobrescrevia o que outra aba
        # tivesse acabado de gravar. Quem não sabe de que versão partiu não
        # tem como saber o que está apagando.
        submitted_version = request.POST.get('row_version')
        if not submitted_version:
            return self._fail(
                request, encounter,
                'Envio sem a versão do atendimento. Recarregue a página e tente de novo.', 400,
            )

        submitted = [name for name in self.EDITABLE if name in request.POST]
        if not submitted:
            return self._fail(request, encounter, 'Nada para salvar.', 400)

        PartialForm = modelform_factory(Encounter, form=EncounterForm, fields=submitted)
        form = PartialForm(request.POST, instance=encounter)
        if not form.is_valid():
            first = next(iter(form.errors.values()))[0]
            return self._fail(request, encounter, first, 400)

        # Ler a versão, comparar e gravar eram três passos soltos: duas
        # abas liam a mesma versão, as duas passavam na conferência e a
        # segunda apagava a primeira. Pior, um salvamento iniciado antes da
        # finalização podia gravar depois dela, por cima do texto fechado.
        # `select_for_update` põe os três passos dentro da mesma transação —
        # a segunda aba espera, relê a versão já incrementada e recusa.
        with transaction.atomic():
            travado = (
                Encounter.objects
                .select_for_update()
                .filter(tenant_id=request.access_context.tenant_id, id=encounter.id)
                .first()
            )
            if travado is None:
                raise Http404
            if not travado.is_editable():
                return self._fail(
                    request, encounter,
                    'Atendimento finalizado enquanto você escrevia: o registro não pode '
                    'mais ser alterado. Use um adendo.', 409,
                )
            if str(travado.row_version) != submitted_version:
                return self._fail(
                    request, encounter,
                    'Este atendimento foi alterado em outra aba desde que você o abriu. '
                    'Recarregue a página para não sobrescrever o que já foi gravado.', 409,
                )
            for name in submitted:
                setattr(travado, name, form.cleaned_data[name])
            if travado.status == EncounterStatus.DRAFT:
                travado.status = EncounterStatus.IN_PROGRESS
            travado.row_version += 1
            travado.full_clean()
            travado.save()
        updated = travado

        if self._wants_json(request):
            return JsonResponse({'ok': True, 'row_version': updated.row_version})
        messages.success(request, 'Prontuário salvo.')
        return redirect(_detalhe(updated, _aba_pedida(request)))


class FindingUpsertView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.')
        form = FindingForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-exame')
        data = form.cleaned_data
        try:
            if data['domain'] == ExaminationDomain.CRANIAL_NERVE:
                upsert_cranial_nerve_finding(
                    request.access_context, encounter, data['item_code'], data['side'] or 'not_applicable',
                    data['body_site'], data['state'], data['qualifier'], data['note'],
                )
            else:
                upsert_finding(
                    request.access_context, encounter, data['domain'], data['item_code'],
                    data['side'] or 'not_applicable', data['body_site'], data['state'],
                    data['numeric_value'], data['qualifier'], data['note'],
                )
        except Exception as exc:
            return _blocked(request, encounter, _texto_do_erro(exc), anchor='tab-exame')
        messages.success(request, 'Achado registrado.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class ExamAxisSaveView(TenantScopedView):
    """Grava um eixo inteiro do roteiro de exame.

    O roteiro tem quase 400 itens; enviar tudo de uma vez a cada salvamento
    obrigaria o médico a esperar a página inteira. Um eixo por vez mantém o
    formulário pequeno e o que ele acabou de preencher é o que é gravado.
    """

    def post(self, request, encounter_id, axis):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exame')
        template = resolve_template(
            request.access_context.tenant_id, request.access_context.membership_id,
        )
        if template is None:
            return _blocked(
                request, encounter,
                'Nenhum roteiro de exame publicado nesta organização.', anchor='tab-exame',
            )
        saved, removed = save_axis(request.access_context, encounter, template, axis, request.POST)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_axis_saved',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'axis': axis, 'saved': saved, 'removed': removed},
        )
        messages.success(request, f'Exame salvo: {saved} item(ns) registrado(s) neste eixo.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class ExamGroupNormalView(TenantScopedView):
    """Marca (ou desfaz) "tudo normal" num grupo do roteiro.

    Ação deliberada, exigida explicitamente pelo PRD (11.1): nunca é
    pré-selecionada, diz quantos itens foram marcados e quantos foram
    ignorados por já terem registro manual, e pode ser desfeita enquanto o
    atendimento não estiver finalizado.
    """

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exame')
        template = resolve_template(
            request.access_context.tenant_id, request.access_context.membership_id,
        )
        if template is None:
            return _blocked(
                request, encounter,
                'Nenhum roteiro de exame publicado nesta organização.', anchor='tab-exame',
            )

        path = (request.POST.get('path') or '').strip()
        if not path:
            return _blocked(request, encounter, 'Grupo não informado.', anchor='tab-exame')
        undo = request.POST.get('undo') == '1'

        if undo:
            removed = undo_group_normal(request.access_context, encounter, template, path)
            outcome = {'removed': removed}
            messages.success(request, f'Marcação em bloco desfeita: {removed} item(ns) removido(s).')
        else:
            marked, skipped = mark_group_normal(
                request.access_context, encounter, template, path,
            )
            outcome = {'marked': marked, 'skipped': skipped}
            text = f'{marked} item(ns) marcado(s) como normal.'
            if skipped:
                text += f' {skipped} preservado(s) por já terem registro próprio.'
            messages.success(request, text)

        record_audit_event(
            request.user, request.access_context.tenant_id,
            'clinical.exam_group_normal_undone' if undo else 'clinical.exam_group_normal',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'path': path, **outcome},
        )
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class ScaleRecordView(TenantScopedView):
    """Aplica uma escala funcional ao atendimento.

    Vale para escala que não está amarrada a um ponto do roteiro — Barthel,
    Epworth, Pfeffer descrevem o paciente inteiro. Enviar sem nenhum item
    marcado remove a escala do atendimento.
    """

    def post(self, request, encounter_id, code):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exame')
        scale = get_object_or_404(
            ExamScale, tenant_id=request.access_context.tenant_id, code=code, active=True,
        )
        finding, removed = record_scale(request.access_context, encounter, scale, request.POST)
        if finding is None:
            messages.success(request, f'{scale.name} removida do atendimento.')
            detail = {'scale': scale.code, 'removed': removed}
        else:
            summary = f'{scale.name}: {finding.qualifier}' if finding.qualifier else f'{scale.name} registrada.'
            messages.success(request, summary)
            detail = {
                'scale': scale.code,
                'total': finding.value_json.get('total'),
                'complete': finding.value_json.get('complete'),
            }
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.scale_recorded',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata=detail,
        )
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class DiagnosisCreateView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.')
        form = DiagnosisForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-hipoteses')
        EncounterDiagnosis.objects.create(
            tenant_id=request.access_context.tenant_id, encounter=encounter,
            diagnosis_code_id=form.cleaned_data['diagnosis_code_id'],
            code_snapshot=form.cleaned_data['code_snapshot'],
            description_snapshot=form.cleaned_data['description_snapshot'],
            certainty=form.cleaned_data['certainty'], rank=form.cleaned_data['rank'],
            physician_note=form.cleaned_data['physician_note'],
        )
        # A recusa ja voltava para a aba de hipoteses; o sucesso, nao --
        # acrescentar uma hipotese devolvia a pessoa para a primeira aba,
        # e a lista que ela acabara de alimentar ficava fora da tela. Na
        # tela de texto livre a mesma view atende e nao ha aba nenhuma: a
        # ancora nao casa com nada e a pagina fica no topo, que e onde o
        # bloco de hipoteses dela esta.
        return redirect(_detalhe(encounter, 'tab-hipoteses'))


class CarryForwardReviewView(TenantScopedView):
    def post(self, request, encounter_id, item_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(
                request, encounter,
                'Atendimento finalizado: o registro não pode mais ser alterado. '
                'Use um adendo.', anchor='carry-forward',
            )
        item = get_object_or_404(encounter.carry_forward_items, id=item_id)
        action = request.POST.get('action')
        if action not in ('accepted', 'edited', 'rejected'):
            # Recusa legível, e não 404: a URL existe e o item existe — o que
            # falta é a ação. Um 404 aqui manda quem está atendendo para uma
            # página de erro sem dizer o que houve, e some com a tela do
            # atendimento junto.
            return _blocked(
                request, encounter,
                'Não deu para saber se era para trazer ou descartar. Clique de novo no botão.',
                anchor='carry-forward',
            )
        membership = _doctor_membership(request)
        try:
            cf.review_carry_forward_item(item, action, membership.id if membership else None)
        except cf.CarryForwardBlocked as exc:
            return _blocked(request, encounter, str(exc), anchor='carry-forward')
        return redirect(_detalhe(encounter, 'carry-forward'))


class CarryForwardAcceptAllView(TenantScopedView):
    """Traz de uma vez tudo o que a consulta anterior ofereceu.

    O retorno de um paciente em uso de seis medicamentos chega com dez
    itens para revisar, e revisar quase sempre quer dizer aceitar: a
    conduta, as impressoes, as hipoteses e a lista de medicacao sao o
    ponto de partida da consulta de hoje. Dez cliques, dez recarregamentos
    de pagina e dez voltas para a primeira aba -- e o que esse atrito
    produz nao e cuidado, e um medico que para de usar o recurso.

    **Nao e um caminho novo.** Cada item passa por
    `review_carry_forward_item`, o mesmo do botao individual, com as
    mesmas recusas: atendimento finalizado continua barrado la dentro, e
    nao so aqui. Isto e o botao individual clicado em todos, nada mais.

    **Tudo ou nada.** A transacao envolve o laco inteiro porque um "trazer
    tudo" que traz metade e pior do que um que falha: ninguem conta o que
    veio, e a diferenca so aparece na consulta seguinte, quando faltar a
    medicacao que ninguem percebeu que nao tinha entrado.

    Nao ha confirmacao antes. Aceitar e exatamente o que o botao diz, cada
    item ja esta escrito na tela acima do botao, e o que ele grava
    continua editavel ate a finalizacao -- pedir confirmacao aqui seria
    cobrar um clique a mais justamente de quem veio economizar nove.
    """

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(
                request, encounter,
                'Atendimento finalizado: o registro não pode mais ser alterado. '
                'Use um adendo.', anchor='carry-forward',
            )
        membership = _doctor_membership(request)
        pendentes = list(
            encounter.carry_forward_items.filter(review_action=ReviewAction.PENDING)
        )
        if not pendentes:
            # Sem erro: quem clicou duas vezes, ou clicou na aba velha
            # depois de ja ter revisado, nao fez nada de errado.
            messages.info(request, 'Não havia nada aguardando revisão.')
            return redirect(_detalhe(encounter))
        try:
            with transaction.atomic():
                for item in pendentes:
                    cf.review_carry_forward_item(
                        item, ReviewAction.ACCEPTED,
                        membership.id if membership else None,
                    )
        except cf.CarryForwardBlocked as exc:
            return _blocked(request, encounter, str(exc), anchor='carry-forward')
        record_audit_event(
            request.user, request.access_context.tenant_id,
            'clinical.carry_forward_accepted_all',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'itens': len(pendentes)},
        )
        quantos = len(pendentes)
        rotulo = 'itens trazidos' if quantos > 1 else 'item trazido'
        messages.success(
            request, f'{quantos} {rotulo} da consulta anterior para esta consulta.',
        )
        # Sem ancora: o cartao da consulta anterior desaparece agora que
        # nada esta pendente, e mandar para um id que nao existe mais
        # deixaria a pagina num lugar arbitrario. O topo e onde a pessoa
        # estava.
        return redirect(_detalhe(encounter))


class FinalizeEncounterView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        membership = _doctor_membership(request)
        if membership is None:
            raise Http404
        try:
            encounter = finalization.finalize_encounter(request.access_context, encounter, membership)
        except finalization.FinalizationError as exc:
            return _blocked(request, encounter, _texto_do_erro(exc))
        # O retorno **depois** da finalização, e não antes: se a finalização
        # for recusada por requisito faltando, não pode sobrar um retorno
        # previsto de um atendimento que não fechou.
        escolhido = (request.POST.get('retorno_meses') or '').strip()
        aviso = ''
        if escolhido.isdigit() and int(escolhido) in INTERVALOS_MESES:
            retorno = agendar_retorno(
                request.access_context, encounter, int(escolhido), membership,
            )
            aviso = f' Retorno previsto para {retorno.due_on:%d/%m/%Y}.'
        messages.success(
            request, f'Atendimento finalizado. O registro agora é imutável.{aviso}',
        )
        return redirect('clinical:detail', encounter_id=encounter.id)



class EncounterDiscardView(TenantScopedView):
    """Descarta um atendimento não finalizado.

    Existe porque abrir um atendimento no paciente errado, ou duas vezes no
    mesmo, acontece — e a linha ficava na história do paciente para sempre,
    vazia. Finalizado continua imutável: lá a correção é adendo.
    """

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        membership = _doctor_membership(request)
        if membership is None:
            return _blocked(
                request, encounter,
                'Só um médico com vínculo ativo pode descartar um atendimento.',
            )
        patient_id = encounter.patient_id
        try:
            finalization.discard_encounter(
                request.access_context, encounter, membership,
                reason=request.POST.get('reason', ''),
            )
        except finalization.FinalizationError as exc:
            return _blocked(request, encounter, _texto_do_erro(exc))
        messages.success(request, 'Atendimento descartado.')
        return redirect('clinical:timeline', patient_id=patient_id)


class AmendmentCreateView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        membership = _doctor_membership(request)
        if membership is None:
            raise Http404
        ancora = _ancora_de_adendos(encounter)
        form = AmendmentForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor=ancora)
        try:
            finalization.add_amendment(
                request.access_context, encounter, membership,
                form.cleaned_data['reason'], form.cleaned_data['text'],
            )
        except finalization.FinalizationError as exc:
            return _blocked(request, encounter, _texto_do_erro(exc), anchor=ancora)
        messages.success(request, 'Adendo registrado.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#{ancora}')


class EncounterSummaryView(TenantScopedView):
    """Resumo do caso em uma página, para leitura e impressão.

    Página própria e não um modal: o que se quer é levar o caso para fora da
    tela — imprimir, salvar em PDF pelo diálogo do navegador, ler ao lado do
    paciente. Sai sem menu, sem botões e sem formulário, com o cabeçalho de
    identificação que um documento impresso precisa ter.

    Não é documento assinado: é uma leitura do prontuário. Receita,
    relatório e encaminhamento continuam saindo pelo fluxo de documentos
    médicos, com assinatura digital.
    """

    def get(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        findings = list(
            encounter.examination_findings.select_related('template_node')
            .order_by('domain', 'item_code', 'side')
        )
        exam_results = list(
            encounter.exam_results.prefetch_related('lab_values').order_by('-performed_on', 'name')
        )
        for result in exam_results:
            values = list(result.lab_values.all())
            result.values_out = [v for v in values if v.flag in ('low', 'high', 'abnormal')]
            result.values_in_count = sum(1 for v in values if v.flag == 'normal')
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.encounter_summary_viewed',
            object_type='encounter', object_id=encounter.id, outcome='success',
        )
        return render(request, 'clinical/summary.html', {
            'encounter': encounter,
            'patient': encounter.patient,
            'findings_by_domain': group_findings_by_domain(findings),
            'findings_count': len(findings),
            'medications': list(encounter.medications.all()),
            'exam_results': exam_results,
            'diagnoses': encounter.diagnoses.all().order_by('rank'),
            'amendments': encounter.amendments.all().order_by('authored_at'),
            'printed_at': timezone.now(),
            'printed_by': request.user.get_full_name() or request.user.email,
        })


class MedicationCreateView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-medicacoes')
        form = MedicationForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-medicacoes')
        medication = form.save(commit=False)
        medication.tenant_id = request.access_context.tenant_id
        medication.encounter = encounter
        medication.save()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.medication_added',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': medication.name},
        )
        messages.success(request, f'{medication.name} incluído nas medicações em uso.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-medicacoes')


def _prefixo_da_medicacao(medication):
    return f'med{medication.id.hex}'


class MedicationUpdateView(TenantScopedView):
    """Altera uma medicação já registrada neste atendimento.

    Antes, mudar a dose era excluir e cadastrar de novo -- o que perdia o
    "em uso desde", a indicação e a observação, e deixava na trilha uma
    remoção e uma inclusão onde houve um ajuste. Vale a mesma regra das
    outras escritas do prontuário: só enquanto o atendimento não foi
    finalizado; depois, a correção é por adendo.

    A trilha guarda **quais campos** mudaram, e não os valores: dose é
    conteúdo clínico, e a trilha não guarda conteúdo clínico.
    """

    def post(self, request, encounter_id, medication_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-medicacoes')
        medication = get_object_or_404(
            Medication, tenant_id=request.access_context.tenant_id, encounter=encounter, id=medication_id,
        )
        form = MedicationForm(
            request.POST, instance=medication, prefix=_prefixo_da_medicacao(medication),
        )
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-medicacoes')
        if not form.has_changed():
            messages.info(request, f'Nada mudou em {medication.name}.')
            return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-medicacoes')
        medication = form.save()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.medication_updated',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': medication.name, 'campos': sorted(form.changed_data)},
        )
        messages.success(request, f'{medication.name} atualizado.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-medicacoes')


class MedicationDeleteView(TenantScopedView):
    def post(self, request, encounter_id, medication_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-medicacoes')
        medication = get_object_or_404(
            Medication, tenant_id=request.access_context.tenant_id, encounter=encounter, id=medication_id,
        )
        name = medication.name
        medication.delete()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.medication_removed',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': name},
        )
        messages.success(request, f'{name} removido das medicações em uso.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-medicacoes')


class ExamResultCreateView(TenantScopedView):
    """Registra um resultado de exame e, se houver PDF, pede a leitura à IA.

    O arquivo segue o mesmo caminho de qualquer anexo — quarentena,
    verificação de malware, publicação — e a leitura pela IA só começa
    depois disso. Nada do que a IA ler entra no prontuário sem revisão.
    """

    def post(self, request, encounter_id):
        from documents.models import AttachmentClassification
        from documents.storage import QuotaExceeded, receive_upload
        from documents.tasks import scan_attachment
        from documents.validators import UploadRejected
        from tenancy.models import Tenant

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        form = ExamResultForm(request.POST, request.FILES)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-exames')

        exam_result = form.save(commit=False)
        exam_result.tenant_id = request.access_context.tenant_id
        exam_result.encounter = encounter
        exam_result.patient = encounter.patient

        uploaded = form.cleaned_data.get('report_file')
        attachment = None
        if uploaded is not None:
            tenant = Tenant.objects.get(id=request.access_context.tenant_id)
            try:
                attachment = receive_upload(
                    request.access_context, tenant, encounter.patient, request.user,
                    uploaded.read(), uploaded.name, AttachmentClassification.CLINICAL,
                    encounter=encounter, document_date=form.cleaned_data.get('performed_on'),
                )
            except (UploadRejected, QuotaExceeded) as exc:
                return _blocked(request, encounter, _texto_do_erro(exc), anchor='tab-exames')
            exam_result.attachment = attachment

        exam_result.save()
        if attachment is not None:
            scan_attachment.delay(str(attachment.id))
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_result_added',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': exam_result.name, 'has_report': attachment is not None},
        )

        if attachment is not None and form.cleaned_data.get('run_extraction'):
            from ai.context import AIAuthorizationDenied
            from ai.extraction import ExtractionUnavailable, request_extraction

            try:
                job = request_extraction(request.access_context, exam_result)
            except (ExtractionUnavailable, AIAuthorizationDenied) as exc:
                messages.warning(request, f'Exame registrado, mas a leitura por IA não foi iniciada: {exc}')
                return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')
            if job.status == 'disabled':
                messages.warning(
                    request,
                    f'{exam_result.name} registrado. A leitura por IA está desligada nesta '
                    'instalação, então o laudo ficou anexado para transcrição manual.',
                )
            else:
                messages.success(
                    request,
                    f'{exam_result.name} registrado. A IA está lendo o laudo; o rascunho aparece '
                    'aqui para sua revisão em instantes.',
                )
        else:
            messages.success(request, f'{exam_result.name} registrado.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


def _exam_result_or_404(request, encounter, exam_result_id):
    return get_object_or_404(
        ExamResult.objects.select_related('attachment'),
        tenant_id=request.access_context.tenant_id, encounter=encounter, id=exam_result_id,
    )


class ExamResultDeleteView(TenantScopedView):
    def post(self, request, encounter_id, exam_result_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        name = exam_result.name
        # O anexo não é apagado junto: ele fica no prontuário do paciente,
        # com o histórico de retenção próprio. Remover o registro do exame
        # não é motivo para descartar o documento original.
        exam_result.delete()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_result_removed',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': name},
        )
        messages.success(request, f'{name} removido dos resultados de exame.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class LabValueCreateView(TenantScopedView):
    def post(self, request, encounter_id, exam_result_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        form = LabValueForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-exames')
        value = form.save(commit=False)
        value.tenant_id = request.access_context.tenant_id
        value.exam_result = exam_result
        value.order = exam_result.lab_values.count()
        value.source = 'manual'
        value.save()
        messages.success(request, f'{value.analyte}: {value.get_flag_display().lower()}.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class LabValueDeleteView(TenantScopedView):
    def post(self, request, encounter_id, value_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        value = get_object_or_404(
            LabValue, tenant_id=request.access_context.tenant_id,
            exam_result__encounter=encounter, id=value_id,
        )
        analyte = value.analyte
        value.delete()
        messages.success(request, f'{analyte} removido.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class ExamResultExtractView(TenantScopedView):
    """Pede (ou repete) a leitura do laudo pela IA."""

    def post(self, request, encounter_id, exam_result_id):
        from ai.context import AIAuthorizationDenied
        from ai.extraction import ExtractionUnavailable, request_extraction

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        try:
            job = request_extraction(request.access_context, exam_result)
        except (ExtractionUnavailable, AIAuthorizationDenied) as exc:
            return _blocked(request, encounter, _texto_do_erro(exc), anchor='tab-exames')
        if job.status == 'disabled':
            messages.warning(request, 'A leitura por IA está desligada nesta instalação.')
        else:
            messages.success(request, 'Leitura do laudo solicitada. O rascunho aparece aqui para revisão.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class ExamResultDraftReviewView(TenantScopedView):
    """Aceita ou recusa o rascunho da IA para um resultado de exame.

    É este passo — e só ele — que transforma leitura de PDF em conteúdo do
    prontuário (RF-11-B). Enquanto ninguém aceita, o rascunho existe como
    artefato revisável e o registro segue vazio.
    """

    def post(self, request, encounter_id, exam_result_id):
        from ai.extraction import (
            ExtractionUnavailable, accept_draft, accept_draft_as_amendment,
            latest_draft, reject_draft,
        )

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        artifact = latest_draft(exam_result)
        if artifact is None:
            return _blocked(request, encounter, 'Não há rascunho para revisar.', anchor='tab-exames')

        membership = _doctor_membership(request)
        if membership is None:
            return _blocked(
                request, encounter,
                'Só um médico com vínculo ativo pode revisar o rascunho da IA.', anchor='tab-exames',
            )
        action = request.POST.get('action')
        try:
            if action == 'accept':
                if encounter.is_editable():
                    accept_draft(artifact, exam_result, membership, request.access_context.user_id)
                    messages.success(request, 'Rascunho revisado e incorporado ao prontuário.')
                else:
                    accept_draft_as_amendment(
                        artifact, exam_result, membership, request.access_context,
                    )
                    messages.success(request, 'Leitura revisada e registrada como adendo ao atendimento finalizado.')
            elif action == 'reject':
                reject_draft(
                    artifact, exam_result, membership, request.access_context.user_id,
                    request.POST.get('reason', ''),
                )
                messages.success(request, 'Rascunho recusado. Nada foi gravado no prontuário.')
            else:
                return _blocked(request, encounter, 'Ação inválida.', anchor='tab-exames')
        except ExtractionUnavailable as exc:
            return _blocked(request, encounter, _texto_do_erro(exc), anchor='tab-exames')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class DiagnosticSupportRequestView(TenantScopedView):
    def post(self, request, encounter_id):
        from ai.context import AIAuthorizationDenied
        from ai.services import request_diagnostic_support

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        try:
            job = request_diagnostic_support(request.access_context, encounter)
        except AIAuthorizationDenied as exc:
            return _blocked(request, encounter, _texto_do_erro(exc), anchor='tab-hipoteses')
        if job.status == 'disabled':
            messages.warning(request, 'O apoio por IA está desligado nesta instalação.')
        elif job.status == 'succeeded':
            messages.info(request, 'O caso não mudou desde a última análise; o resultado abaixo é dela.')
        else:
            messages.success(
                request,
                'Análise solicitada. As hipóteses aparecem aqui por nível de prioridade, '
                'para sua avaliação.',
            )
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-hipoteses')


class DiagnosisFromSupportView(TenantScopedView):
    """Leva uma hipótese sugerida para a lista do prontuário.

    Entra sempre como `suspected` e com a nota dizendo que a sugestão veio
    da IA e foi aceita por quem clicou: a hipótese registrada é do médico, e
    o prontuário guarda de onde ela partiu.
    """

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-hipoteses')
        label = (request.POST.get('label') or '').strip()
        if not label:
            return _blocked(request, encounter, 'Hipótese não informada.', anchor='tab-hipoteses')
        rank = encounter.diagnoses.count() + 1
        EncounterDiagnosis.objects.create(
            tenant_id=request.access_context.tenant_id, encounter=encounter,
            code_snapshot='', description_snapshot=label[:4000],
            certainty='suspected', rank=rank,
            physician_note='Sugestão da IA revisada e aceita pelo médico.',
        )
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.diagnosis_from_ai',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'label': label[:255]},
        )
        messages.success(request, f'“{label}” registrada como hipótese.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-hipoteses')


class FindingDeleteView(TenantScopedView):
    """Remove um item registrado no exame, a partir do grid.

    Existe porque desmarcar no roteiro só funciona para item que ainda está
    no roteiro em vigor: achado do catálogo avulso, escala aplicada e item de
    uma versão anterior do roteiro não têm onde ser desmarcados. O grid é o
    lugar em que todos aparecem, então é dele que se apaga.
    """

    def post(self, request, encounter_id, finding_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(
                request, encounter,
                'Atendimento finalizado: o exame não pode mais ser alterado.',
                anchor='tab-exame',
            )
        finding = get_object_or_404(
            ExaminationFinding,
            tenant_id=request.access_context.tenant_id,
            encounter=encounter, id=finding_id,
        )
        label = finding.qualifier or finding.get_state_display()
        item = finding.item_code
        finding.delete()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_finding_deleted',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'item_code': item},
        )
        messages.success(request, f'Item removido do exame ({label}).')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')
