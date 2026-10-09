from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from audit.services import record_audit_event
from patients.models import Patient
from tenancy.permissions import Capability, CapabilityRequiredView
from tenancy.selectors import scope_to_tenant

from . import credentials as credentials_services
from . import document_kinds
from . import issuance
from . import signing_sessions
from .forms import AttachmentUploadForm, CredentialUploadForm, MedicalDocumentForm, SigningSessionStartForm
from .models import (
    Attachment, AttachmentClassification, AttachmentScanStatus, MedicalDocument, MedicalDocumentStatus,
    SigningCredential,
)
from .preview import PreviewUnavailable, render_preview_png
from .retention import soft_delete_attachment
from .signing import InvalidPfxPassword
from .storage import QuotaExceeded, read_bytes, receive_upload
from .tasks import scan_attachment
from .validators import UploadRejected


class TenantScopedView(CapabilityRequiredView):
    """Anexar e listar documento é trabalho administrativo do cadastro.

    O PRD separa as duas coisas: anexar documento administrativo é `A` para
    dono, secretaria e gestor, mas **visualizar anexo clínico** é `—` para
    secretaria e gestor. A capacidade da tela é portanto a administrativa; o
    que protege o conteúdo clínico é a verificação por anexo, em
    `_attachment_or_404`, porque a classificação é do arquivo e não da tela.
    """

    required_capability = Capability.PATIENT_ADMIN


class ClinicalDocumentView(CapabilityRequiredView):
    """Documento médico: o conteúdo é clínico, então ler exige o prontuário."""

    required_capability = Capability.READ_CLINICAL


class SigningView(CapabilityRequiredView):
    """Certificado e sessão de assinatura — só médico habilitado."""

    required_capability = Capability.ISSUE_DOCUMENT


def _patient_or_404(request, patient_id):
    return get_object_or_404(scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id)


#: Estados em que o documento médico já saiu: é o que a recepção imprime.
DOCUMENTO_EMITIDO = (MedicalDocumentStatus.ISSUED, MedicalDocumentStatus.ISSUED_ON_PAPER)


def _documentos_dos_anexos(ids):
    """`{anexo_id: MedicalDocument}` para os anexos que são PDF de documento médico."""
    from django.db.models import Q

    ids = list(ids)
    if not ids:
        return {}
    mapa = {}
    for documento in MedicalDocument.objects.filter(
        Q(pdf_attachment_id__in=ids) | Q(signed_pdf_attachment_id__in=ids),
    ):
        for anexo_id in (documento.pdf_attachment_id, documento.signed_pdf_attachment_id):
            if anexo_id in ids:
                mapa[anexo_id] = documento
    return mapa


def _pode_abrir(access_context, attachment, documento):
    """Quem pode baixar e ver a prévia **deste** anexo.

    O PDF de um documento médico é clínico, mas a recepção imprime a
    receita e o relatório para entregar ao paciente -- decisão do
    controlador em 2026-10-09. Então a regra é a do documento, e não a da
    classificação: **emitido**, quem administra o cadastro do paciente
    abre; **rascunho**, só quem lê prontuário, porque ali há conteúdo
    clínico que o médico ainda não liberou.
    """
    if access_context.can(Capability.READ_CLINICAL):
        return True
    if documento is not None:
        return (documento.status in DOCUMENTO_EMITIDO
                and access_context.can(Capability.PATIENT_ADMIN))
    return attachment.classification != AttachmentClassification.CLINICAL


def _attachment_or_404(request, attachment_id):
    """O anexo, se quem pede tiver direito a **este** anexo.

    A verificação é por objeto porque a classificação é do arquivo: a mesma
    tela lista a carteirinha do convênio e o laudo de ressonância, e só o
    segundo é prontuário. Sem isto, a secretária que precisa anexar a guia
    baixaria também o laudo — e o PRD escreve `—` nessa célula.

    404 e não 403: existir ou não o anexo clínico já é informação clínica.
    """
    attachment = scope_to_tenant(Attachment.objects.all(), request.access_context).filter(
        id=attachment_id, deleted_at=None,
    ).first()
    if attachment is None:
        raise Http404
    documento = _documentos_dos_anexos([attachment.id]).get(attachment.id)
    attachment.documento_medico = documento
    if not _pode_abrir(request.access_context, attachment, documento):
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.clinical_attachment_denied',
            object_type='attachment', object_id=attachment.id, outcome='denied',
        )
        raise Http404
    return attachment


def _com_permissoes(request, attachments):
    """Cada anexo com o que **esta** pessoa pode fazer com ele.

    A tela pergunta aqui, e não refaz a regra no template: botão que
    devolve 404 é pior do que botão ausente, e duas cópias da mesma regra
    são duas chances de uma divergir de `_attachment_or_404`.
    """
    attachments = list(attachments)
    documentos = _documentos_dos_anexos(a.id for a in attachments)
    for anexo in attachments:
        documento = documentos.get(anexo.id)
        anexo.pode_abrir = _pode_abrir(request.access_context, anexo, documento)
        # Nome à vista para quem pode abrir: o da receita emitida é o que a
        # recepção procura para imprimir.
        anexo.mostra_nome = anexo.pode_abrir
        # O PDF de documento médico não se remove por esta tela, nem por
        # quem lê prontuário: ele é o documento, e o documento tem ciclo
        # próprio (rascunho, emissão, guarda). Removido aqui, a receita
        # emitida continuaria apontando para um arquivo que a coleta
        # apagaria.
        anexo.pode_remover = documento is None
    return attachments


class AttachmentListView(TenantScopedView):
    """A lista de anexos do paciente.

    Quem nao le prontuario ve a **linha** de um anexo clinico, e nao o
    nome dele. A diferenca importa: a secretaria precisa saber que o
    exame ja chegou, para responder ao paciente que ligou perguntando --
    e nao precisa saber que o exame e um eletroencefalograma.

    O conteudo ja estava protegido em `_attachment_or_404` (baixar e
    previa devolvem 404), mas o nome do arquivo escapava na listagem, e
    nome de arquivo e informacao clinica numa clinica de neurologia:
    `ressonancia_cranio.pdf` diz o que foi investigado. Mascarar aqui, e
    nao esconder a linha, e o que fecha a brecha sem tirar da recepcao a
    informacao de que ha documento.
    """

    def get(self, request, patient_id):
        patient = _patient_or_404(request, patient_id)
        attachments = _com_permissoes(
            request, patient.attachments.filter(deleted_at=None).order_by('-created_at'),
        )
        return render(request, 'documents/list.html', {
            'patient': patient, 'attachments': attachments,
            'pode_ver_clinico': request.access_context.can(Capability.READ_CLINICAL),
            'form': AttachmentUploadForm(),
        })

    def post(self, request, patient_id):
        patient = _patient_or_404(request, patient_id)
        form = AttachmentUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            attachments = _com_permissoes(request, patient.attachments.filter(deleted_at=None).order_by('-created_at'))
            return render(request, 'documents/list.html', {'patient': patient, 'attachments': attachments, 'form': form})
        uploaded = request.FILES['file']
        from tenancy.models import Tenant
        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        try:
            attachment = receive_upload(
                request.access_context, tenant, patient, request.user, uploaded.read(), uploaded.name,
                form.cleaned_data['classification'], document_date=form.cleaned_data.get('document_date'),
            )
        except (UploadRejected, QuotaExceeded) as exc:
            form.add_error('file', str(exc))
            attachments = _com_permissoes(request, patient.attachments.filter(deleted_at=None).order_by('-created_at'))
            return render(request, 'documents/list.html', {'patient': patient, 'attachments': attachments, 'form': form})
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.attachment_uploaded',
            object_type='attachment', object_id=attachment.id, outcome='success',
        )
        scan_attachment.delay(str(attachment.id))
        return redirect('documents:list', patient_id=patient.id)


class AttachmentDownloadView(TenantScopedView):
    def get(self, request, attachment_id):
        attachment = _attachment_or_404(request, attachment_id)
        if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
            record_audit_event(
                request.user, request.access_context.tenant_id, 'documents.attachment_download_denied',
                object_type='attachment', object_id=attachment.id, outcome='denied',
            )
            raise Http404
        # O arquivo pode nao estar la: backup restaurado sem a midia,
        # disco trocado, expurgo que apagou os bytes e deixou a linha. Sem
        # este `except`, a falta vira 500 com rastro -- o medico ve "erro
        # do servidor" e ninguem fica sabendo de qual anexo se trata. Com
        # ele, vira 404 e um evento na trilha dizendo qual arquivo sumiu.
        try:
            conteudo = read_bytes(attachment)
        except (FileNotFoundError, OSError):
            record_audit_event(
                request.user, request.access_context.tenant_id,
                'documents.attachment_file_missing',
                object_type='attachment', object_id=attachment.id, outcome='failure',
            )
            raise Http404
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.attachment_downloaded',
            object_type='attachment', object_id=attachment.id, outcome='success',
        )
        response = HttpResponse(conteudo, content_type=attachment.mime)
        response['Content-Disposition'] = f'attachment; filename="{attachment.original_name}"'
        response['Cache-Control'] = 'private, no-store'
        return response


class AttachmentPreviewView(TenantScopedView):
    def get(self, request, attachment_id):
        attachment = _attachment_or_404(request, attachment_id)
        # Mesma razao do download acima: arquivo ausente e 404, nao 500.
        try:
            png_bytes = render_preview_png(attachment)
        except (PreviewUnavailable, FileNotFoundError, OSError):
            raise Http404
        response = HttpResponse(png_bytes, content_type='image/png')
        response['Cache-Control'] = 'private, no-store'
        return response


class AttachmentDeleteView(TenantScopedView):
    def post(self, request, attachment_id):
        attachment = _attachment_or_404(request, attachment_id)
        if attachment.documento_medico is not None:
            # Ver `_com_permissoes`: o botão nem aparece, e isto é a recusa
            # no servidor para quem montar o POST à mão.
            record_audit_event(
                request.user, request.access_context.tenant_id, 'documents.attachment_delete_denied',
                object_type='attachment', object_id=attachment.id, outcome='denied',
            )
            messages.error(
                request,
                'Este PDF é de um documento médico e não pode ser removido pela lista de anexos.',
            )
            return redirect('documents:list', patient_id=attachment.patient_id)
        soft_delete_attachment(attachment, request.user.id, request.POST.get('reason', ''))
        return redirect('documents:list', patient_id=attachment.patient_id)


def _encounter_or_404(request, encounter_id):
    from clinical.models import Encounter

    encounter = scope_to_tenant(Encounter.objects.all(), request.access_context).filter(id=encounter_id).first()
    if encounter is None:
        raise Http404
    return encounter


def _medical_document_or_404(request, document_id):
    document = scope_to_tenant(MedicalDocument.objects.all(), request.access_context).filter(id=document_id).first()
    if document is None:
        raise Http404
    return document


def _own_doctor_membership_or_403(request):
    """Every signing-adjacent action acts strictly as *this* logged-in
    user's own membership -- there is no "act on behalf of" path, which is
    exactly what keeps a secretary/manager/AI session from ever touching a
    physician's signing session (S07-T08).
    """
    from tenancy.models import Membership

    if not request.access_context.has_role('doctor'):
        return None
    return Membership.objects.filter(id=request.access_context.membership_id).select_related('user').first()


class MedicalDocumentListView(ClinicalDocumentView):
    def get(self, request, encounter_id):
        encounter = _encounter_or_404(request, encounter_id)
        documents = encounter.medical_documents.order_by('-created_at')
        return render(request, 'documents/medical_list.html', {'encounter': encounter, 'documents': documents})


class PatientDocumentsView(ClinicalDocumentView):
    """Tudo o que existe de documento daquele paciente, num lugar só.

    As listas eram por atendimento: para achar a receita de fevereiro era
    preciso lembrar em qual consulta ela saiu e abrir aquele atendimento.
    O prontuário é do paciente, não da consulta — e quem procura um
    documento procura pelo paciente.

    Junta o que o sistema emitiu (receita, laudo, pedido, encaminhamento) e
    o que entrou de fora (upload e digitalização), porque para quem procura
    são a mesma coisa: um papel daquele paciente.
    """

    def get(self, request, patient_id):
        patient = _patient_or_404(request, patient_id)
        documents = (
            MedicalDocument.objects
            .filter(tenant_id=request.access_context.tenant_id, patient=patient)
            .select_related('encounter', 'physician__user')
            .order_by('-created_at')
        )
        attachments = (
            patient.attachments.filter(deleted_at=None)
            .select_related('encounter')
            .order_by('-created_at')
        )
        return render(request, 'documents/patient_documents.html', {
            'patient': patient,
            'documents': documents,
            'attachments': attachments,
            'issued_count': sum(1 for d in documents if d.status == 'issued'),
        })


class MedicalDocumentCreateView(ClinicalDocumentView):
    def get(self, request, encounter_id):
        encounter = _encounter_or_404(request, encounter_id)
        # O atendimento vai para o contexto para a tela saber de quem é o
        # documento que está sendo criado. Sem ele, a trilha de navegação
        # dizia "Início › Documentos › Novo" — sem paciente e sem
        # atendimento, como se o documento não pertencesse a ninguém.
        return render(request, 'documents/medical_form.html', {
            'form': MedicalDocumentForm(), 'encounter': encounter,
        })

    def post(self, request, encounter_id):
        encounter = _encounter_or_404(request, encounter_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Só um vínculo de médico pode emitir documento médico.')
        form = MedicalDocumentForm(request.POST)
        if not form.is_valid():
            return render(request, 'documents/medical_form.html',
                          {'form': form, 'encounter': encounter})
        kind = form.cleaned_data['kind']
        content_fields = {field: form.cleaned_data[field] for field in document_kinds.all_fields(kind)}
        from tenancy.models import Tenant

        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        try:
            document = issuance.create_draft(
                tenant, encounter.patient, encounter, physician_membership, request.user.id, kind, content_fields,
            )
        except (ValueError, issuance.MissingPhysicianProfile) as exc:
            form.add_error(None, str(exc))
            return render(request, 'documents/medical_form.html',
                          {'form': form, 'encounter': encounter})
        return redirect('documents:medical-detail', document_id=document.id)


class PatientDocumentCreateView(ClinicalDocumentView):
    """Emitir documento a partir da ficha do paciente, sem atendimento.

    É a receita que se renova por telefone, o pedido de exame que ficou
    faltando, o encaminhamento que o paciente voltou para buscar. Exigir um
    atendimento nesses casos levava a abrir uma consulta que não houve só
    para poder imprimir — e consulta inventada no prontuário é pior do que
    documento sem consulta.

    O caminho continua sendo o mesmo do atendimento daí em diante: gera
    rascunho, revisa, e então assina digitalmente ou emite para assinar à
    mão. O que muda é só a ausência do vínculo com o atendimento, que fica
    registrada no próprio documento e na trilha.
    """

    def _patient_or_404(self, request, patient_id):
        return get_object_or_404(
            Patient.objects.filter(tenant_id=request.access_context.tenant_id), id=patient_id,
        )

    def get(self, request, patient_id):
        paciente = self._patient_or_404(request, patient_id)
        return render(request, 'documents/medical_form.html', {
            'form': MedicalDocumentForm(), 'patient': paciente, 'sem_atendimento': True,
        })

    def post(self, request, patient_id):
        paciente = self._patient_or_404(request, patient_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Só um vínculo de médico pode emitir documento médico.')
        form = MedicalDocumentForm(request.POST)
        contexto = {'patient': paciente, 'sem_atendimento': True}
        if not form.is_valid():
            return render(request, 'documents/medical_form.html', dict(contexto, form=form))
        kind = form.cleaned_data['kind']
        content_fields = {field: form.cleaned_data[field] for field in document_kinds.all_fields(kind)}
        from tenancy.models import Tenant

        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        try:
            document = issuance.create_draft(
                tenant, paciente, None, physician_membership, request.user.id, kind, content_fields,
            )
        except (ValueError, issuance.MissingPhysicianProfile) as exc:
            form.add_error(None, str(exc))
            return render(request, 'documents/medical_form.html', dict(contexto, form=form))
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentIssueOnPaperView(ClinicalDocumentView):
    """Emite o documento para ser assinado à caneta e carimbado.

    `POST`, e nunca um link: atribui número de documento e muda o estado.
    """

    def post(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        try:
            issuance.issue_on_paper(document, request.user.id)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('documents:medical-detail', document_id=document.id)
        messages.success(
            request,
            'Documento emitido para assinatura de próprio punho. '
            'Imprima, assine e carimbe — ele não leva QR, porque quem responde por '
            'ele no papel é a sua assinatura.',
        )
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentDetailView(ClinicalDocumentView):
    def get(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        is_own_document = physician_membership is not None and physician_membership.id == document.physician_id
        active_session = None
        credentials = []
        if is_own_document:
            active_session = signing_sessions.get_active_session(request, physician_membership)
            credentials = SigningCredential.objects.filter(physician=physician_membership).order_by('-created_at')
        return render(request, 'documents/medical_detail.html', {
            'document': document, 'is_own_document': is_own_document,
            'active_session': active_session, 'credentials': credentials,
            'session_form': SigningSessionStartForm(), 'credential_form': CredentialUploadForm(),
            **_delivery_context(document),
        })


def _delivery_context(document):
    """O que aconteceu com a entrega deste documento.

    A entrega dispara sozinha na emissão, pela fila de eventos — e é
    justamente por ser automática que precisa aparecer: sem esta lista, o
    médico não tem como saber se o SMS saiu, se o e-mail voltou, ou se o
    paciente sequer tinha contato cadastrado. Descobrir isso pelo paciente
    ligando é tarde demais.
    """
    from communications.models import Delivery

    deliveries = list(
        Delivery.objects.filter(document=document)
        .select_related('contact')
        .prefetch_related('attempts')
        .order_by('-created_at')
    )
    for delivery in deliveries:
        ultimo = max(delivery.attempts.all(), key=lambda a: a.attempt_number, default=None)
        delivery.last_error = ultimo.sanitized_error if ultimo else ''
    return {
        'deliveries': deliveries,
        'delivered_ok': any(d.status in ('accepted', 'delivered') for d in deliveries),
    }


class MedicalDocumentSendView(ClinicalDocumentView):
    """Reenvia o documento ao paciente.

    **O primeiro envio não passa por aqui.** Ele é automático: assinar
    emite `documents.document_issued`, e `communications.handlers` entrega
    sozinho, no worker. Este botão é o reenvio — mensagem que não chegou,
    paciente que trocou de telefone, link que expirou. Cada reenvio gera um
    link novo e revoga o anterior, o que também é a saída quando se
    suspeita que o link foi parar em mãos erradas.

    **A entrega sai pelo worker, e não aqui.** Chamava `deliver_document`
    dentro da requisição: o e-mail escapava porque o backend dele enfileira
    sozinho, mas o SMS ia na hora, sem retentativa e com a tela presa ao
    tempo do provedor.

    A consequência para a tela é que o resultado não existe no instante da
    resposta. Em troca, a tela deixa de poder quebrar por causa de uma
    entrega: foi exatamente assim que um SMS longo demais virou
    `Server Error (500)` com o documento já assinado.

    Só documento emitido: um rascunho enviado ao paciente é um documento
    sem validade circulando com a cara de válido.
    """

    def post(self, request, document_id):
        from communications.services import _eligible_document_contacts
        from communications.tasks import deliver_document_task

        document = _medical_document_or_404(request, document_id)
        if document.status not in ('issued', 'issued_on_paper'):
            messages.error(
                request,
                'Só documento emitido pode ser enviado ao paciente. '
                'Assine antes de enviar.',
            )
            return redirect('documents:medical-detail', document_id=document.id)

        # A falta de contato é conferida aqui, e não só no worker: é o
        # único desfecho que a pessoa na tela pode resolver agora, e
        # descobri-lo por uma linha numa lista de entregas minutos depois
        # é descobrir tarde.
        if not _eligible_document_contacts(document.patient):
            messages.warning(
                request,
                'Nenhum contato do paciente está autorizado e verificado para receber '
                'documento. Complete o cadastro de contato na ficha dele.',
            )
            return redirect('documents:medical-detail', document_id=document.id)

        deliver_document_task.delay(str(document.id), force_new_link=True)
        messages.success(
            request,
            'Reenvio em andamento. O link anterior deixou de valer; o novo chega em '
            'instantes e pede os 4 últimos dígitos do CPF do paciente. '
            'O resultado aparece na lista de entregas abaixo.',
        )
        record_audit_event(
            request.user, document.tenant_id, 'documents.medicaldocument_sent',
            object_type='medical_document', object_id=document.id, outcome='success',
        )
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentReviewView(ClinicalDocumentView):
    def post(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None or physician_membership.id != document.physician_id:
            return HttpResponseForbidden('Só o médico que escreveu o documento pode revisá-lo.')
        try:
            issuance.mark_reviewed(document, request.user.id)
        except issuance.NotReadyToSign as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentDiscardView(ClinicalDocumentView):
    def post(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None or physician_membership.id != document.physician_id:
            return HttpResponseForbidden('Só o médico que escreveu o documento pode descartá-lo.')
        encounter_id = document.encounter_id
        try:
            issuance.discard_document(document, request.user.id)
        except issuance.NotReadyToSign as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('documents:medical-list', encounter_id=encounter_id)


class MedicalDocumentSignView(SigningView):
    def post(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Só um vínculo de médico pode assinar.')
        try:
            issuance.sign_and_issue(document, request, physician_membership)
        except (issuance.NotReadyToSign, issuance.SigningNotAuthorized) as exc:
            return render(request, 'documents/medical_detail.html', {
                'document': document, 'is_own_document': True, 'sign_error': str(exc),
                'active_session': signing_sessions.get_active_session(request, physician_membership),
                'credentials': SigningCredential.objects.filter(physician=physician_membership),
                'session_form': SigningSessionStartForm(), 'credential_form': CredentialUploadForm(),
            }, status=409)
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentCorrectionView(ClinicalDocumentView):
    def post(self, request, document_id):
        original = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None or physician_membership.id != original.physician_id:
            return HttpResponseForbidden('Só o médico que escreveu o documento pode retificá-lo.')
        # O tipo é o do documento original e não é escolhido de novo:
        # retificar é corrigir o conteúdo, não trocar uma receita por um
        # laudo. O formulário abre travado nesse tipo.
        form = MedicalDocumentForm(request.POST, locked_kind=original.kind)
        if not form.is_valid():
            return render(request, 'documents/medical_form.html', {
                'form': form, 'correcting': original,
            })
        content_fields = {field: form.cleaned_data[field] for field in document_kinds.all_fields(original.kind)}
        try:
            new_document = issuance.create_correction(
                original, request.user.id, content_fields,
                reason=request.POST.get('correction_reason', ''),
            )
        except ValueError as exc:
            # A criação recusa conteúdo incompleto e receita de controle
            # especial sem endereço. Sem este tratamento a recusa subia como
            # erro 500 e tirava o médico da tela com o texto já digitado.
            form.add_error(None, str(exc))
            return render(request, 'documents/medical_form.html', {
                'form': form, 'correcting': original,
            })
        return redirect('documents:medical-detail', document_id=new_document.id)


class SigningCredentialUploadView(SigningView):
    def post(self, request):
        from tenancy.models import Tenant

        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Só um vínculo de médico pode enviar certificado de assinatura.')
        from accounts import mfa

        if not mfa.user_has_confirmed_totp(request.user):
            messages.warning(
                request,
                'Configure a MFA antes de enviar seu certificado digital.',
            )
            setup_url = reverse('accounts:mfa-setup')
            return redirect(f'{setup_url}?{urlencode({"next": reverse("documents:credential-list")})}')
        if not mfa.mfa_verified_recently(request):
            # Antes isto pedia para **sair e entrar de novo**: derrubar a
            # sessao inteira para reconfirmar seis digitos, porque a tela
            # de reconfirmacao nao existia.
            messages.info(
                request,
                'Confirme o código do aplicativo autenticador para enviar o certificado.',
            )
            return mfa.redirect_to_mfa_confirm(request, reverse('documents:credential-list'))
        form = CredentialUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return HttpResponseForbidden('Formulário inválido.')
        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        try:
            credentials_services.upload_credential(
                tenant, physician_membership, form.cleaned_data['pfx_file'].read(), form.cleaned_data['password'],
            )
        except (credentials_services.InvalidPfxFile, credentials_services.CredentialTitleMismatch) as exc:
            return HttpResponseForbidden(str(exc))
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingcredential_uploaded',
            object_type='signing_credential', outcome='success',
        )
        return redirect('documents:credential-list')


class SigningCredentialListView(SigningView):
    def get(self, request):
        from accounts import mfa

        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Só um vínculo de médico tem certificado de assinatura.')
        creds = SigningCredential.objects.filter(physician=physician_membership).order_by('-created_at')
        active_session = signing_sessions.get_active_session(request, physician_membership)
        return render(request, 'documents/credentials.html', {
            'credentials': creds, 'active_session': active_session,
            'credential_form': CredentialUploadForm(), 'session_form': SigningSessionStartForm(),
            'mfa_ativa': mfa.user_has_confirmed_totp(request.user),
            'mfa_recente': mfa.mfa_verified_recently(request),
        })


class SigningCredentialRevokeView(SigningView):
    def post(self, request, credential_id):
        physician_membership = _own_doctor_membership_or_403(request)
        credential = SigningCredential.objects.filter(id=credential_id, physician=physician_membership).first() \
            if physician_membership else None
        if credential is None:
            return HttpResponseForbidden('Certificado não encontrado para este médico.')
        credentials_services.revoke_credential(credential)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingcredential_revoked',
            object_type='signing_credential', object_id=credential.id, outcome='success',
        )
        return redirect('documents:credential-list')


class SigningSessionStartView(SigningView):
    @staticmethod
    def _pedir_codigo(request):
        """Manda reconfirmar o segundo fator e voltar aos certificados.

        Devolvia `403` com a frase solta em fundo branco: dizia o que
        fazer e nao oferecia onde -- a tela de reconfirmacao nao existia.

        A senha do certificado **nao** e guardada para ser reenviada
        depois do codigo: ela abre a chave privada, e nada que a guarde
        (sessao, cache, campo oculto) vale a comodidade de nao redigita-la.
        O aviso diz isso, para a redigitacao nao parecer defeito.
        """
        from accounts.mfa import redirect_to_mfa_confirm

        messages.info(
            request,
            'Confirme o código do aplicativo autenticador para liberar a assinatura. '
            'Depois disso você digita a senha do certificado de novo.',
        )
        return redirect_to_mfa_confirm(request, reverse('documents:credential-list'))

    def post(self, request):
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Só um vínculo de médico pode abrir sessão de assinatura.')
        # A MFA e conferida **antes** do formulario e do certificado, e nao
        # dentro de `start_session`. Conferida depois, o medico que
        # esbarrasse na MFA vencida recebia primeiro uma recusa sobre o
        # certificado -- e, mesmo acertando tudo, so descobria no fim que
        # faltava o codigo, com a senha ja digitada e perdida. O codigo e
        # pre-condicao da operacao, nao da credencial.
        #
        # `start_session` continua conferindo por conta propria: esta e a
        # ordem da tela, nao a trava.
        from accounts.mfa import mfa_verified_recently

        if not mfa_verified_recently(request):
            return self._pedir_codigo(request)
        form = SigningSessionStartForm(request.POST)
        if not form.is_valid():
            return HttpResponseForbidden('Formulário inválido.')
        credential = SigningCredential.objects.filter(
            id=form.cleaned_data['credential_id'], physician=physician_membership,
        ).first()
        if credential is None:
            return HttpResponseForbidden('Certificado não encontrado para este médico.')
        try:
            signing_sessions.start_session(
                request, physician_membership, credential,
                form.cleaned_data['password'], int(form.cleaned_data['duration_hours']),
            )
        except signing_sessions.RecentMfaRequired:
            # Corrida: a MFA venceu entre a conferencia acima e esta linha.
            return self._pedir_codigo(request)
        except (signing_sessions.InvalidDuration, signing_sessions.CredentialNotUsable) as exc:
            return HttpResponseForbidden(str(exc))
        except InvalidPfxPassword:
            record_audit_event(
                request.user, request.access_context.tenant_id, 'documents.signingsession_start_failed',
                object_type='signing_credential', object_id=credential.id, outcome='denied',
            )
            return HttpResponseForbidden(
                'Senha do certificado incorreta. Confira e tente de novo.'
            )
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingsession_started',
            object_type='signing_credential', object_id=credential.id, outcome='success',
        )
        return redirect('documents:credential-list')


class SigningSessionRevokeView(SigningView):
    def post(self, request, session_id):
        from .models import SigningSession

        physician_membership = _own_doctor_membership_or_403(request)
        session = SigningSession.objects.filter(id=session_id, physician=physician_membership).first() \
            if physician_membership else None
        if session is None:
            return HttpResponseForbidden('Sessão de assinatura não encontrada para este médico.')
        signing_sessions.revoke_session(session)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingsession_revoked',
            object_type='signing_session', object_id=session.id, outcome='success',
        )
        return redirect('documents:credential-list')
