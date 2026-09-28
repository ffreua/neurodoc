from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from audit.services import record_audit_event
# A lista de atendimentos da ficha usa o MESMO seletor do prontuario, com a
# mesma tabela fechada de ordenacao: duas consultas paralelas divergiriam, e
# a ficha acabaria mostrando uma ordem que o prontuario nao conhece.
from clinical import selectors as clinical_selectors
from integrations.cep import lookup_cep
from tenancy.limits import PlanLimitReached, assert_can_add_patient, patient_status
from tenancy.permissions import Capability, CapabilityRequiredView

from . import photo as photo_storage
from . import selectors
from .contacts import create_contact, sync_self_contact_name
from .coverage import add_coverage, set_patient_coverage
from .forms import (
    PatientContactForm, PatientCoverageForm, PatientForm, PatientMeasurementForm,
)
from .models import Patient, PatientStatus, RegistrationStage
from .observations import age_at, compute_bmi, missing_measurement_hint, record_observation


class TenantScopedView(CapabilityRequiredView):
    """Cadastro do paciente é administrativo, e os quatro papéis o fazem.

    Dados demográficos, contato e convênio não são prontuário: o PRD dá
    esta linha a dono, médico, secretaria e gestor. O que a ficha do
    paciente **não** pode fazer é abrir nota clínica, e isso é decidido nas
    telas do prontuário, não aqui.
    """

    required_capability = Capability.PATIENT_ADMIN


class PatientListView(TenantScopedView):
    def get(self, request):
        query = request.GET.get('q', '')
        page = request.GET.get('page', 1)
        patients = selectors.list_patients(request.access_context, query=query, page=page)
        return render(request, 'patients/list.html', {
            'patients': patients, 'query': query,
            # O aviso aparece a partir de 80% da cota. O bloqueio não pode
            # ser a primeira notícia: quem o descobre com o paciente no
            # balcão não tem o que fazer naquele momento.
            'limite': patient_status(request.access_context.tenant_id),
        })


class PatientAutocompleteView(TenantScopedView):
    def get(self, request):
        query = request.GET.get('q', '')
        results = selectors.autocomplete_patients(request.access_context, query)
        return JsonResponse({'results': [
            # O número vai junto para a busca da agenda distinguir dois
            # homônimos — que é exatamente quando escolher o paciente errado
            # é mais fácil.
            {'id': str(p.id), 'full_name': p.full_name, 'record_number': p.record_number}
            for p in results
        ]})


def mascarar_cpf(cpf):
    """`123.***.**9-01` — o bastante para conferir, longe de um documento.

    A busca rápida abre por cima de qualquer tela, inclusive a do balcão
    com gente do outro lado. Quem procura precisa distinguir dois
    homônimos, e para isso bastam alguns dígitos; o CPF inteiro na ficha
    do paciente é outro contexto, com a tela virada para quem atende.
    """
    digitos = ''.join(c for c in (cpf or '') if c.isdigit())
    if len(digitos) != 11:
        return ''
    return f'{digitos[:3]}.***.**{digitos[8]}-{digitos[9:]}'


class PatientGlobalSearchView(TenantScopedView):
    """Busca rápida do topo (Ctrl+K), em JSON.

    Mesma capacidade da lista de pacientes: quem não pode abrir a lista
    não pode procurar por aqui. A consulta sai de
    `selectors.busca_rapida`, que nasce de `scope_to_tenant` — o parâmetro
    `q` escolhe **dentro** da clínica da sessão e não tem como sair dela.

    Devolve o link pronto em vez de deixar a tela montar a URL: rota é
    assunto do servidor, e um `/app/patients/<id>/` escrito à mão no
    JavaScript é a primeira coisa a quebrar quando a rota muda.
    """

    def get(self, request):
        encontrados = selectors.busca_rapida(request.access_context, request.GET.get('q', ''))
        return JsonResponse({'resultados': [
            {
                'id': str(p.id),
                'nome': p.full_name,
                'cpf_mascarado': mascarar_cpf(p.cpf),
                'nascimento': p.birth_date.strftime('%d/%m/%Y') if p.birth_date else '',
                'prontuario': p.record_number or '',
                'url': reverse('patients:detail', args=[p.id]),
            }
            for p in encontrados
        ]})


def _photo_context(request=None):
    """O que o bloco da fotografia precisa saber, num lugar só.

    O limite em MB sai de `photo.MAX_PHOTO_BYTES` em vez de estar escrito
    no template: um número repetido na tela e no validador vira mentira no
    dia em que um dos dois mudar, e a mentira aparece como "envie uma
    versão menor" para um arquivo que já está dentro do limite anunciado.

    `photo_capture_value` devolve a captura ao formulário que volta com
    aviso. Campo de arquivo o navegador esvazia sempre; este é oculto, e
    por isso a foto tirada pela câmera sobrevive ao re-render.
    """
    return {
        'max_photo_mb': photo_storage.MAX_PHOTO_BYTES // (1024 * 1024),
        'photo_capture_value': (request.POST.get('photo_capture', '') if request is not None else ''),
    }


def _incoming_photo(request):
    """Bytes da fotografia enviada neste POST, ou None quando não veio nenhuma.

    Duas origens, um resultado: o arquivo escolhido (`photo`) e a captura
    da câmera (`photo_capture`, uma data URL). A captura ganha quando as
    duas vêm juntas — o fluxo da câmera termina numa prévia na tela, então
    quem capturou **viu** o que está mandando, e o JS limpa o campo de
    arquivo ao capturar. A regra está aqui também porque o navegador não é
    de confiança para garantir o que o JS combinou.

    Levanta `PhotoRejected`. Quem chama valida **antes** de abrir a
    transação do cadastro: descobrir que o arquivo é um PDF renomeado
    depois de gravar o paciente obrigaria a desfazer a gravação, e a
    alternativa — gravar o paciente e engolir a foto — salvaria o cadastro
    sem o retrato sem dizer nada a ninguém.
    """
    capture = photo_storage.decode_capture(request.POST.get('photo_capture'))
    if capture is not None:
        photo_storage.validate_photo(capture)
        return capture
    uploaded = request.FILES.get('photo')
    if uploaded is None:
        return None
    content = uploaded.read()
    photo_storage.validate_photo(content)
    return content


class PatientCreateView(TenantScopedView):
    def get(self, request):
        form = PatientForm(tenant_id=request.access_context.tenant_id)
        return render(request, 'patients/form.html',
                      {'form': form, 'duplicates': [], **_photo_context()})

    def post(self, request):
        # Antes de validar o formulário: recusar depois de a pessoa
        # preencher trinta campos é pior, e o limite não depende de nada do
        # que ela digitou. A verificação se repete dentro da transação, que
        # é onde ela vale contra duas recepcionistas cadastrando ao mesmo
        # tempo.
        try:
            assert_can_add_patient(request.access_context.tenant_id)
        except PlanLimitReached as limite:
            return render(request, 'patients/limit_reached.html',
                          {'limite': limite}, status=409)
        form = PatientForm(request.POST, tenant_id=request.access_context.tenant_id)
        duplicates = []
        photo_error = None
        incoming_photo = None
        try:
            incoming_photo = _incoming_photo(request)
        except photo_storage.PhotoRejected as exc:
            photo_error = str(exc)
        if form.is_valid() and photo_error is None:
            duplicates = selectors.find_possible_duplicates(
                request.access_context, form.cleaned_data['full_name'], form.cleaned_data.get('birth_date'),
            )
            if duplicates and not request.POST.get('confirm_duplicate'):
                # `_photo_context(request)` devolve a captura ao formulário.
                # Este é o re-render mais comum do cadastro, e sem ele quem
                # tirou a foto pela câmera a perderia ao confirmar a
                # duplicidade — o cadastro seguiria sem retrato, calado.
                return render(request, 'patients/form.html', {
                    'form': form, 'duplicates': duplicates, **_photo_context(request),
                })
            coverage_data = form.coverage_data
            # Paciente e carteirinha entram juntos: um cadastro "por plano"
            # sem cobertura faria a cobrança cair em particular.
            measurements = form.measurements
            # Telefone e e-mail informados no cadastro viram um contato de
            # verdade, o mesmo que a área de Contatos lista e que a agenda lê
            # para confirmar horário. Guardá-los em outro lugar criaria um
            # segundo endereço do paciente que metade do sistema não enxerga.
            contact_data = form.contact_data
            with transaction.atomic():
                # De novo, e agora valendo. A verificação de cima evita o
                # preenchimento perdido; esta é a que impede duas
                # recepcionistas de passarem juntas pela última vaga.
                assert_can_add_patient(request.access_context.tenant_id)
                patient = form.save(commit=False)
                patient.tenant_id = request.access_context.tenant_id
                patient.full_clean()
                patient.save()
                if coverage_data:
                    set_patient_coverage(request.access_context, patient, **coverage_data)
                # Peso e altura viram medidas com data (`Observation`), que é
                # o que o IMC da ficha lê. Sem isto o cálculo existia e nunca
                # tinha o que calcular.
                for kind, value, unit in measurements:
                    record_observation(request.access_context, patient, kind, value, unit)
                if contact_data:
                    create_contact(request.access_context, patient, **contact_data)
                if incoming_photo is not None:
                    # Por último de propósito. `store_photo` escreve no
                    # disco, e disco não entra em rollback: se a cobertura
                    # ou a medida estourassem depois, o arquivo ficaria
                    # órfão numa pasta cujo paciente nunca existiu, sem
                    # nada que o alcançasse para apagar.
                    photo_storage.store_photo(patient, incoming_photo)
                    patient.save(update_fields=photo_storage.PHOTO_FIELDS)
            record_audit_event(
                request.user, request.access_context.tenant_id, 'patients.patient_created', object_type='patient',
                object_id=patient.id, outcome='success',
            )
            if incoming_photo is not None:
                record_audit_event(
                    request.user, request.access_context.tenant_id, 'patients.patient_photo_updated',
                    object_type='patient', object_id=patient.id, outcome='success',
                    integrity_metadata={'mime': patient.photo_mime, 'bytes': patient.photo_bytes},
                )
            return redirect('patients:detail', patient_id=patient.id)
        return render(request, 'patients/form.html', {
            'form': form, 'duplicates': duplicates, 'photo_error': photo_error,
            **_photo_context(request),
        })


def _detail_context(request, patient, **overrides):
    """Contexto da tela do paciente, num lugar só.

    Três views renderizam `patients/detail.html` (abrir, adicionar contato,
    adicionar cobertura); montar o contexto em cada uma já tinha deixado
    duas delas sem o formulário da outra.
    """
    ordenar = request.GET.get('ordenar', clinical_selectors.ORDEM_PADRAO)
    if ordenar not in clinical_selectors.ORDENS_DA_GRADE:
        ordenar = clinical_selectors.ORDEM_PADRAO
    decrescente = request.GET.get('desc') == '1'

    context = {
        'patient': patient,
        'bmi': compute_bmi(patient),
        'age': age_at(patient.birth_date),
        'contact_form': PatientContactForm(),
        'measurement_form': PatientMeasurementForm(),
        'measurement_hint': missing_measurement_hint(patient),
        'coverage_form': PatientCoverageForm(tenant_id=request.access_context.tenant_id),
        # **Todos** os atendimentos, e não os cinco últimos.
        #
        # Cortar em cinco obrigava a ir ao prontuário para ver o sexto, e a
        # ficha é onde se olha a história do paciente antes de atendê-lo. A
        # lista rola dentro do cartão; a tela não cresce com o paciente
        # antigo.
        #
        # A ordem é do usuário: abertura responde "quando ele veio?" e
        # fechamento "quando este registro foi fechado?" — com atendimento
        # aberto num dia e finalizado em outro, as duas deixam de coincidir.
        # Validada contra a tabela fechada do selector, nunca interpolada.
        'encounters': clinical_selectors.patient_timeline(
            request.access_context, patient, ordenar=ordenar, decrescente=decrescente,
        ),
        'ordenar': ordenar,
        'decrescente': decrescente,
    }
    context.update(overrides)
    return context


class PatientDetailView(TenantScopedView):
    def get(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        return render(request, 'patients/detail.html', _detail_context(request, patient))


class PatientUpdateView(TenantScopedView):
    def get(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        form = PatientForm(instance=patient, tenant_id=request.access_context.tenant_id)
        return render(request, 'patients/form.html',
                      {'form': form, 'patient': patient, 'duplicates': [], **_photo_context()})

    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        submitted_version = request.POST.get('row_version')
        if submitted_version and str(patient.row_version) != submitted_version:
            return HttpResponse('Conflict: this record changed since you opened it.', status=409)
        form = PatientForm(request.POST, instance=patient, tenant_id=request.access_context.tenant_id)
        if form.is_valid():
            confirmando_cadastro = patient.registration_stage == RegistrationStage.PRELIMINARY
            updated = form.save(commit=False)
            if confirmando_cadastro:
                # Um POST valido passou por todos os campos obrigatorios da
                # ficha. Este e o ato de confirmacao: manter `preliminary`
                # faria o cadastro completo continuar invisivel na lista.
                updated.registration_stage = RegistrationStage.COMPLETE
            updated.row_version += 1
            coverage_data = form.coverage_data
            measurements = form.measurements
            with transaction.atomic():
                updated.full_clean()
                updated.save()
                if coverage_data:
                    set_patient_coverage(request.access_context, updated, **coverage_data)
                # Só o que mudou: salvar a ficha sem tocar no peso não pode
                # inserir uma segunda medida idêntica na série.
                for kind, value, unit in measurements:
                    record_observation(request.access_context, updated, kind, value, unit)
                # O contato do próprio paciente guarda uma cópia do nome, e
                # ela não acompanhava a ficha: renomear o paciente deixava a
                # lista de Contatos com o nome antigo ao lado do telefone
                # certo. O mesmo nome aparece no comprovante de entrega de
                # documento, onde responde "para quem esta receita foi
                # enviada" — errado ali, é registro apontando para outra
                # pessoa.
                renomeados = sync_self_contact_name(updated)
            metadados = {}
            if renomeados:
                metadados['self_contacts_renamed'] = renomeados
            if confirmando_cadastro:
                metadados['registration_stage'] = RegistrationStage.COMPLETE
            record_audit_event(
                request.user, request.access_context.tenant_id, 'patients.patient_updated', object_type='patient',
                object_id=updated.id, outcome='success',
                integrity_metadata=metadados or None,
            )
            return redirect('patients:detail', patient_id=updated.id)
        return render(request, 'patients/form.html', {
            'form': form, 'patient': patient, 'duplicates': [], **_photo_context(request),
        })


class PatientPhotoView(TenantScopedView):
    """Envia, substitui ou remove a fotografia de quem já está cadastrado.

    Rota própria, e não um campo do formulário do cadastro, por duas
    razões que se somam:

    - **`row_version`.** O cadastro usa versão de linha para recusar edição
      concorrente com 409. Trocar o retrato não é editar o cadastro: fazer
      a foto passar por ali obrigaria quem só quer atualizar a foto a
      carregar a versão inteira da ficha, e daria conflito quando duas
      pessoas mexessem em coisas diferentes do mesmo paciente.
    - **O arquivo não sobrevive ao re-render.** Quando o cadastro volta com
      aviso de duplicidade ou erro de campo, o navegador não repovoa
      `<input type="file">` — a foto escolhida sumiria calada. Aqui o
      envio tem efeito imediato e não depende de o resto do formulário
      estar válido.

    No cadastro **novo** não há paciente a que anexar o arquivo, e por isso
    lá a foto viaja no POST principal (`PatientCreateView`). As duas
    entradas gravam pela mesma `photo.store_photo`.
    """

    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)

        if request.POST.get('action') == 'remove':
            if not patient.has_photo:
                messages.info(request, 'Este paciente não tem fotografia.')
                return redirect('patients:update', patient_id=patient.id)
            photo_storage.discard_photo(patient)
            patient.save(update_fields=photo_storage.PHOTO_FIELDS)
            record_audit_event(
                request.user, request.access_context.tenant_id, 'patients.patient_photo_removed',
                object_type='patient', object_id=patient.id, outcome='success',
            )
            messages.success(request, 'Fotografia removida.')
            return redirect('patients:update', patient_id=patient.id)

        try:
            content = _incoming_photo(request)
        except photo_storage.PhotoRejected as exc:
            messages.error(request, str(exc))
            return redirect('patients:update', patient_id=patient.id)
        if content is None:
            messages.error(request, 'Escolha um arquivo de imagem ou use a câmera.')
            return redirect('patients:update', patient_id=patient.id)

        photo_storage.store_photo(patient, content)
        # `update_fields` com os campos da foto: sem isso, uma gravação
        # completa levaria junto o que estivesse carregado na instância e
        # desfaria, por cima, uma edição do cadastro salva entre o carregar
        # desta tela e o envio da foto.
        patient.save(update_fields=photo_storage.PHOTO_FIELDS)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'patients.patient_photo_updated',
            object_type='patient', object_id=patient.id, outcome='success',
            integrity_metadata={'mime': patient.photo_mime, 'bytes': patient.photo_bytes},
        )
        messages.success(
            request,
            'Fotografia atualizada. A autorização do paciente para o uso da imagem '
            'é colhida em papel — guarde o termo assinado junto ao prontuário.',
        )
        return redirect('patients:update', patient_id=patient.id)


class PatientPhotoFileView(TenantScopedView):
    """Serve a fotografia de um paciente da organização da sessão.

    O paciente é resolvido por `get_patient_or_404`, que filtra pelo
    inquilino do contexto: um id de outra clínica responde 404 aqui pelo
    mesmo caminho que responde na ficha. É por isso que a rota pode
    receber `patient_id` — o que ela **não** recebe é `tenant_id`, que
    transformaria este endereço num enumerador de retratos de toda a
    instalação. `/data/media` não é servido pelo servidor web exatamente
    para que esta seja a única porta.

    Arquivo ausente é 404, não 500: ver `photo.read_photo`.
    """

    def get(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        content = photo_storage.read_photo(patient)
        if content is None:
            raise Http404
        response = HttpResponse(content, content_type=patient.photo_mime)
        # Privado e curto: a imagem identifica um paciente, e não pode
        # ficar num cache compartilhado. Cinco minutos bastam para a
        # mesma tela não rebaixar a imagem a cada navegação, e a troca
        # aparece na hora porque a URL carrega `?v=<atualizada em>`.
        response['Cache-Control'] = 'private, max-age=300'
        response['X-Content-Type-Options'] = 'nosniff'
        # Conteúdo enviado por usuário, servido do domínio da clínica:
        # impede que o arquivo seja interpretado como página se alguém
        # abrir o endereço direto.
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'"
        return response


class PatientArchiveView(TenantScopedView):
    """Arquivar exige justificativa escrita e confirmação explícita.

    Arquivar tira o paciente da carteira ativa e dos indicadores; sem
    justificativa não há como saber depois por que aquele prontuário saiu
    de circulação, e sem confirmação o botão fica a um clique acidental de
    distância numa tela cheia de outros botões.
    """

    MIN_REASON = 5

    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        if patient.status == PatientStatus.ARCHIVED:
            messages.warning(request, 'Este paciente já está arquivado.')
            return redirect('patients:detail', patient_id=patient.id)

        reason = (request.POST.get('reason') or '').strip()
        if request.POST.get('confirm') != 'archive':
            messages.error(request, 'Arquivamento não confirmado — nada foi alterado.')
            return redirect('patients:detail', patient_id=patient.id)
        if len(reason) < self.MIN_REASON:
            messages.error(
                request,
                'Informe o motivo do arquivamento (pelo menos '
                f'{self.MIN_REASON} caracteres) — nada foi alterado.',
            )
            return redirect('patients:detail', patient_id=patient.id)

        patient.status = PatientStatus.ARCHIVED
        patient.archived_at = timezone.now()
        patient.archived_reason = reason[:255]
        patient.row_version += 1
        patient.save(update_fields=['status', 'archived_at', 'archived_reason', 'row_version', 'updated_at'])
        record_audit_event(
            request.user, request.access_context.tenant_id, 'patients.patient_archived', object_type='patient',
            object_id=patient.id, outcome='success',
        )
        messages.success(request, f'{patient.full_name} foi arquivado.')
        return redirect('patients:detail', patient_id=patient.id)


class PatientContactCreateView(TenantScopedView):
    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        form = PatientContactForm(request.POST)
        if form.is_valid():
            try:
                create_contact(request.access_context, patient, **form.cleaned_data)
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                record_audit_event(
                    request.user, request.access_context.tenant_id, 'patients.contact_added',
                    object_type='patient', object_id=patient.id, outcome='success',
                )
                return redirect('patients:detail', patient_id=patient.id)
        return render(request, 'patients/detail.html', _detail_context(request, patient, contact_form=form))


class PatientCoverageCreateView(TenantScopedView):
    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        form = PatientCoverageForm(request.POST, tenant_id=request.access_context.tenant_id)
        if form.is_valid():
            try:
                add_coverage(
                    request.access_context, patient, form.cleaned_data['plan'].id,
                    member_number=form.cleaned_data['member_number'],
                    starts_on=form.cleaned_data['starts_on'], ends_on=form.cleaned_data.get('ends_on'),
                )
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                record_audit_event(
                    request.user, request.access_context.tenant_id, 'patients.coverage_added',
                    object_type='patient', object_id=patient.id, outcome='success',
                )
                return redirect('patients:detail', patient_id=patient.id)
        return render(request, 'patients/detail.html', _detail_context(request, patient, coverage_form=form))



class PatientMeasurementCreateView(TenantScopedView):
    """Registra peso e/ou altura como medida com data.

    Grava uma `Observation` por medida, e é dela que o IMC da ficha é
    calculado. Não sobrescreve a anterior: a série é o que permite ver a
    evolução.
    """

    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        form = PatientMeasurementForm(request.POST)
        if not form.is_valid():
            return render(
                request, 'patients/detail.html',
                _detail_context(request, patient, measurement_form=form),
            )
        observed_on = form.cleaned_data.get('observed_on')
        observed_at = None
        if observed_on:
            from datetime import datetime, time

            observed_at = timezone.make_aware(datetime.combine(observed_on, time(12, 0)))
        with transaction.atomic():
            for kind, value, unit in form.measurements:
                record_observation(
                    request.access_context, patient, kind, value, unit, observed_at=observed_at,
                )
        record_audit_event(
            request.user, request.access_context.tenant_id, 'patients.measurement_recorded',
            object_type='patient', object_id=patient.id, outcome='success',
            integrity_metadata={kind: str(value) for kind, value, _ in form.measurements},
        )
        messages.success(request, 'Medida registrada.')
        return redirect('patients:detail', patient_id=patient.id)


class CepLookupView(TenantScopedView):
    def get(self, request):
        cep = request.GET.get('cep', '')
        address = lookup_cep(cep)
        if address is None:
            return JsonResponse({'found': False})
        return JsonResponse({'found': True, 'address': address})
