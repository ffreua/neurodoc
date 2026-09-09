"""Fila de pedidos vindos do portal do paciente.

Do lado de dentro. O que o paciente escreveu no portal chega aqui como
**pedido**, e sai daqui como rascunho de documento — nunca como documento
pronto. Entre uma coisa e outra existe um médico lendo.

A tela exige capacidade clínica porque o texto do pedido é o paciente
falando da própria saúde: uma lista de medicações em uso é prontuário no
momento em que é escrita, ainda que tenha entrado por um formulário
público.
"""

from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from audit.services import record_audit_event
from tenancy.selectors import scope_to_tenant

from . import issuance
from .models import DocumentRequest, DocumentRequestKind, DocumentRequestStatus
from .views import ClinicalDocumentView, _own_doctor_membership_or_403

#: De cada tipo de pedido nasce um tipo de documento. O mapa é explícito
#: porque os nomes não coincidem: receita simples e receita de controle
#: especial são o mesmo `prescription`, mudando só o formato de impressão.
REQUEST_TO_DOCUMENT = {
    DocumentRequestKind.PRESCRIPTION_SIMPLE: ('prescription', 'simple'),
    DocumentRequestKind.PRESCRIPTION_SPECIAL: ('prescription', 'special_control'),
    DocumentRequestKind.REPORT: ('report', None),
    DocumentRequestKind.EXAMS: ('request', None),
}


def _request_or_404(request, request_id):
    return get_object_or_404(
        scope_to_tenant(DocumentRequest.objects.all(), request.access_context), id=request_id,
    )


class DocumentRequestQueueView(ClinicalDocumentView):
    def get(self, request):
        abertos = (
            DocumentRequest.objects
            .filter(tenant_id=request.access_context.tenant_id,
                    status__in=[DocumentRequestStatus.RECEIVED, DocumentRequestStatus.IN_REVIEW])
            .select_related('patient').order_by('created_at')
        )
        fechados = (
            DocumentRequest.objects
            .filter(tenant_id=request.access_context.tenant_id,
                    status__in=[DocumentRequestStatus.FULFILLED, DocumentRequestStatus.DECLINED])
            .select_related('patient', 'reviewed_by__user', 'resulting_document')
            .order_by('-reviewed_at')[:30]
        )
        return render(request, 'documents/request_queue.html', {
            'open_requests': list(abertos),
            'closed_requests': list(fechados),
        })


class DocumentRequestDetailView(ClinicalDocumentView):
    def get(self, request, request_id):
        pedido = _request_or_404(request, request_id)
        return render(request, 'documents/request_detail.html', {
            'req': pedido,
            'items': _readable_payload(pedido),
            'can_draft': _own_doctor_membership_or_403(request) is not None,
        })


class DocumentRequestActionView(ClinicalDocumentView):
    """Recusar o pedido, ou transformá-lo em rascunho de documento."""

    def post(self, request, request_id, action):
        pedido = _request_or_404(request, request_id)
        physician = _own_doctor_membership_or_403(request)
        if physician is None:
            return HttpResponseForbidden('Só um vínculo médico revisa pedido do portal.')
        if not pedido.is_open:
            messages.error(request, 'Este pedido já foi respondido.')
            return redirect('documents:request-detail', request_id=pedido.id)

        if action == 'recusar':
            return self._decline(request, pedido, physician)
        if action == 'rascunho':
            return self._draft(request, pedido, physician)
        raise Http404

    def _decline(self, request, pedido, physician):
        motivo = (request.POST.get('note') or '').strip()
        if not motivo:
            messages.error(
                request,
                'Explique o motivo. O paciente pediu alguma coisa e merece saber por '
                'que não foi atendido — ainda que o aviso saia por telefone.',
            )
            return redirect('documents:request-detail', request_id=pedido.id)
        pedido.status = DocumentRequestStatus.DECLINED
        pedido.review_note = motivo[:500]
        pedido.reviewed_by = physician
        pedido.reviewed_at = timezone.now()
        pedido.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at'])
        record_audit_event(
            request.user, pedido.tenant_id, 'documents.portal_request_declined',
            object_type='document_request', object_id=pedido.id, outcome='success',
        )
        messages.success(request, 'Pedido recusado, com o motivo registrado.')
        return redirect('documents:request-queue')

    def _draft(self, request, pedido, physician):
        from clinical.models import Encounter, EncounterStatus
        from tenancy.models import Tenant

        kind, formato = REQUEST_TO_DOCUMENT.get(pedido.kind, (None, None))
        if kind is None:
            raise Http404

        # Todo documento pende de um atendimento, e pedido de portal não
        # nasce de consulta. Usa o último atendimento do paciente; na falta
        # dele, abre um registro próprio. Pendurar o documento na consulta
        # errada só para ter onde pendurá-lo seria pior: a receita passaria
        # a constar de um atendimento em que ela não foi discutida.
        encounter = (
            Encounter.objects.filter(tenant_id=pedido.tenant_id, patient=pedido.patient)
            .order_by('-occurred_at').first()
        )
        if encounter is None:
            encounter = Encounter.objects.create(
                tenant_id=pedido.tenant_id, patient=pedido.patient,
                physician_membership=physician, occurred_at=timezone.now(),
                status=EncounterStatus.DRAFT,
                chief_complaint='Registro aberto a partir de pedido no portal do paciente.',
            )

        tenant = Tenant.objects.get(id=pedido.tenant_id)
        try:
            documento = issuance.create_draft(
                tenant, pedido.patient, encounter, physician, request.user.id,
                kind, _content_from_request(pedido, kind, formato),
            )
        except (ValueError, issuance.MissingPhysicianProfile) as exc:
            messages.error(request, str(exc))
            return redirect('documents:request-detail', request_id=pedido.id)

        pedido.status = DocumentRequestStatus.FULFILLED
        pedido.resulting_document = documento
        pedido.reviewed_by = physician
        pedido.reviewed_at = timezone.now()
        pedido.save(update_fields=[
            'status', 'resulting_document', 'reviewed_by', 'reviewed_at',
        ])
        record_audit_event(
            request.user, pedido.tenant_id, 'documents.portal_request_drafted',
            object_type='document_request', object_id=pedido.id, outcome='success',
            integrity_metadata={'document': str(documento.id)},
        )
        messages.success(
            request,
            'Rascunho criado a partir do pedido. Revise o conteúdo antes de assinar: '
            'o texto veio do paciente e ninguém o conferiu ainda.',
        )
        return redirect('documents:medical-detail', document_id=documento.id)


def _content_from_request(pedido, kind, formato):
    """Traduz o pedido do paciente em campos do documento.

    O texto entra como **ponto de partida**, e o rascunho vai ao médico
    justamente para ser reescrito. O que não se faz aqui é acrescentar
    posologia, indicação ou justificativa que o paciente não escreveu: um
    documento assinado que contém frase inventada pelo sistema é
    indistinguível, para quem o lê, de frase escrita pelo médico.
    """
    payload = pedido.payload or {}
    if kind == 'prescription':
        linhas = [
            ' — '.join(p for p in [m.get('nome', ''), m.get('dose', ''), m.get('uso', '')] if p)
            for m in payload.get('medicacoes', [])
        ]
        return {
            'prescription_text': '\n'.join(linhas),
            'special_instructions': '',
            'prescription_format': formato or 'simple',
        }
    if kind == 'report':
        return {
            'report_text': (
                f'Finalidade informada pelo paciente: {payload.get("finalidade", "")}\n\n'
                f'{payload.get("conteudo", "")}'
            ),
        }
    return {
        'requested_procedure': payload.get('exames', ''),
        'justification': payload.get('observacao', '') or 'A preencher pelo médico.',
    }


def _readable_payload(pedido):
    """O conteúdo do pedido em pares rótulo/valor, para a tela ler.

    Feito em Python e não no template porque o formato do `payload` muda
    com o tipo, e um template que decide isso vira uma cadeia de `if` que
    ninguém revisa.
    """
    payload = pedido.payload or {}
    if pedido.kind in (DocumentRequestKind.PRESCRIPTION_SIMPLE,
                       DocumentRequestKind.PRESCRIPTION_SPECIAL):
        return [
            (m.get('nome', ''), ' — '.join(p for p in [m.get('dose', ''), m.get('uso', '')] if p))
            for m in payload.get('medicacoes', [])
        ]
    if pedido.kind == DocumentRequestKind.REPORT:
        return [
            ('Finalidade', payload.get('finalidade', '')),
            ('O que precisa constar', payload.get('conteudo', '')),
        ]
    return [
        ('Exames', payload.get('exames', '')),
        ('Observação', payload.get('observacao', '')),
    ]
