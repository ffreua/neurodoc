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
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from audit.services import record_audit_event
from tenancy.selectors import scope_to_tenant

from . import document_kinds, issuance, pedidos_do_portal
from .forms import MedicalDocumentForm
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
            .select_related('patient', 'reviewed_by__user__physician_profile', 'resulting_document')
            .order_by('-reviewed_at')[:30]
        )
        from tenancy.models import PORTAL_RECENT_VISIT_DAYS, ClinicProfile, Membership

        clinica = ClinicProfile.objects.filter(
            tenant_id=request.access_context.tenant_id,
        ).first()
        meu = Membership.objects.filter(
            id=request.access_context.membership_id,
        ).values_list('patient_portal_requires_recent_visit', flat=True).first()
        return render(request, 'documents/request_queue.html', {
            'open_requests': list(abertos),
            'closed_requests': list(fechados),
            # A escolha de barrar fica aqui, e nao numa tela de
            # configuracao: e aqui que o medico ve o efeito dela -- os
            # pedidos que chegaram, e a ausencia dos que foram barrados.
            #
            # `None` e um terceiro estado, e nao "False": significa seguir
            # a clinica, e e o que permite o responsavel mudar o padrao e
            # valer para quem nao se manifestou.
            'barra_do_medico': meu,
            'barra_da_clinica': getattr(
                clinica, 'patient_portal_requires_recent_visit', True,
            ),
            'dias_da_norma': PORTAL_RECENT_VISIT_DAYS,
        })

    def post(self, request):
        """O medico decide se barra consulta antiga nos proprios pacientes.

        So o proprio vinculo: ele vem de `access_context`, e nao de um
        campo do formulario. Aceitar um `membership_id` postado deixaria um
        medico desligar a barreira de outro -- e a responsabilidade do art.
        37 e de quem atende, nao de quem tem o formulario aberto.
        """
        from tenancy.models import Membership

        escolhas = {'clinica': None, 'sim': True, 'nao': False}
        bruto = (request.POST.get('barrar') or '').strip()
        if bruto not in escolhas:
            raise Http404
        valor = escolhas[bruto]

        Membership.objects.filter(id=request.access_context.membership_id).update(
            patient_portal_requires_recent_visit=valor,
        )
        record_audit_event(
            request.user, request.access_context.tenant_id,
            'documents.portal_recent_visit_rule_set',
            object_type='membership', object_id=request.access_context.membership_id,
            outcome='success', integrity_metadata={'barrar': valor},
        )
        messages.success(request, {
            None: 'Atualizado: os seus pacientes seguem a regra da clínica.',
            True: 'Atualizado: pedidos de quem não consulta há mais de 180 dias '
                  'serão recusados pelo portal.',
            False: 'Atualizado: o portal aceitará pedidos independentemente da data '
                   'da última consulta. A avaliação de cada pedido continua sendo sua.',
        }[valor])
        return redirect('documents:request-queue')


def _draft_form(pedido, data=None):
    """O conteúdo do documento a ser criado, aberto para edição.

    O médico precisava aceitar o texto do paciente como veio: o único
    botão criava o rascunho e só depois, na tela do documento, dava para
    corrigir — com o rascunho já gravado, já com PDF gerado e já contando
    como pedido atendido. Corrigir aqui é mais barato e é onde a decisão
    de fato acontece.

    **O pedido do paciente não é editado.** O que se edita é o rascunho
    que nasce dele. `DocumentRequest.payload` é o registro do que a pessoa
    pediu, e é isso que ele prova; reescrevê-lo faria a fila mostrar as
    palavras do médico atribuídas ao paciente, e sumiria com a diferença
    entre o que foi pedido e o que foi emitido.
    """
    kind, formato = REQUEST_TO_DOCUMENT.get(pedido.kind, (None, None))
    if kind is None:
        return None
    if data is not None:
        return MedicalDocumentForm(data, locked_kind=kind)
    initial = {'kind': kind}
    initial.update(_content_from_request(pedido, kind, formato))
    if kind == 'prescription':
        initial['prescription_format'] = _formato_inicial(pedido, formato)
    return MedicalDocumentForm(initial=initial, locked_kind=kind)


def _formato_inicial(pedido, formato):
    """O formato com que a receita do pedido abre.

    Com a numeração do SNCR ligada, o controlado vai para a receita
    eletrônica — a impressa de controle especial não se assina mais
    digitalmente desde 31/10/2026 (`documents/rce_impressa.py`) — e no tipo
    que a lista oficial indica para o que o paciente pediu
    (`sncr.receita.formato_sugerido`): clonazepam abre na Notificação B, e
    não na RCE que o recusaria. O pedido de controle especial que a lista não
    reconhece abre na RCE, que pede a confirmação do médico. Com o SNCR
    desligado nada muda: o formato é o do pedido.

    É o valor **inicial** do seletor; a escolha é do médico.
    """
    from sncr import receita
    from sncr.models import Configuracao

    padrao = formato or 'simple'
    if not Configuracao.carregar().ativo:
        return padrao
    nomes = [m['nome'] for m in pedidos_do_portal.medicacoes(pedido)[:receita.LIMITE_MEDICAMENTOS]]
    sugerido = receita.formato_sugerido(nomes) if nomes else None
    if sugerido:
        return sugerido
    if pedido.kind == DocumentRequestKind.PRESCRIPTION_SPECIAL:
        return receita.SNCR_RCE
    return padrao


#: Quais campos do formulário aparecem em cada tipo de pedido. O
#: formulário declara os sete campos de todos os tipos, e mostrá-los todos
#: obrigaria a dizer "ignore os demais" — o mesmo defeito já corrigido na
#: tela de emissão.
DRAFT_FIELDS = {
    'prescription': ('prescription_format', 'prescription_text', 'special_instructions'),
    'report': ('report_text',),
    'request': ('requested_procedure', 'justification'),
    'referral': ('referral_specialty', 'reason'),
}


def _draft_context(request, pedido, form=None, motivo_erro=None):
    from sncr import receita

    kind, _ = REQUEST_TO_DOCUMENT.get(pedido.kind, (None, None))
    form = form if form is not None else _draft_form(pedido)
    fields = []
    if form is not None and kind != 'prescription':
        fields = [form[name] for name in DRAFT_FIELDS.get(kind, ())]
    medicacoes = pedidos_do_portal.medicacoes(pedido) if kind == 'prescription' else []
    return {
        'req': pedido,
        'items': _readable_payload(pedido),
        'can_draft': _own_doctor_membership_or_403(request) is not None,
        'draft_form': form,
        'draft_fields': fields,
        # A receita usa o mesmo bloco da tela de emissão
        # (`documents/_campos_da_receita.html`), com os itens do SNCR; os
        # outros tipos seguem com os campos de `DRAFT_FIELDS`.
        'e_receita': kind == 'prescription',
        'medicacoes_alem_do_limite': max(0, len(medicacoes) - receita.LIMITE_MEDICAMENTOS),
        'limite_de_medicamentos': receita.LIMITE_MEDICAMENTOS,
        'relatorios_da_ia': pedidos_do_portal.relatorios_da_ia(pedido),
        'motivo_erro': motivo_erro,
    }


class DocumentRequestDetailView(ClinicalDocumentView):
    def get(self, request, request_id):
        pedido = _request_or_404(request, request_id)
        return render(request, 'documents/request_detail.html',
                      _draft_context(request, pedido))


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
            # A recusa sem motivo voltava à tela com um aviso só no alto da
            # página, e o médico (2026-11-09) via a mesma tela de antes, com
            # o pedido ainda na fila e nada dizendo por quê. O erro agora fica
            # no próprio campo, e a tela é desenhada de novo em vez de
            # redirecionada — com o motivo obrigatório dito antes do clique.
            return render(request, 'documents/request_detail.html', _draft_context(
                request, pedido,
                motivo_erro='Toda recusa precisa de um motivo. Escreva por que o pedido '
                            'não será atendido: ele fica registrado, e a clínica o usa '
                            'para avisar o paciente.',
            ), status=400)
        # Só se ainda estiver aberto, num `UPDATE` condicional (auditoria de
        # 2026-11-11). Gravado a partir do pedido lido no começo da
        # requisição, a recusa de uma tela aberta desde antes passava por
        # cima do pedido que outro médico acabara de atender: ele ficava
        # "recusado" com o documento ainda ligado. `marcar_atendido` já
        # relia sob trava; a recusa é o mesmo cuidado do outro lado.
        from .models import DocumentRequest

        recusou = DocumentRequest.objects.filter(
            id=pedido.id,
            status__in=(DocumentRequestStatus.RECEIVED, DocumentRequestStatus.IN_REVIEW),
        ).update(
            status=DocumentRequestStatus.DECLINED, review_note=motivo[:500],
            reviewed_by=physician, reviewed_at=timezone.now(),
        )
        if not recusou:
            messages.error(request, 'Este pedido acabou de ser respondido por outra pessoa.')
            return redirect('documents:request-detail', request_id=pedido.id)
        record_audit_event(
            request.user, pedido.tenant_id, 'documents.portal_request_declined',
            object_type='document_request', object_id=pedido.id, outcome='success',
        )
        messages.success(request, 'Pedido recusado, com o motivo registrado.')
        return redirect('documents:request-queue')

    def _draft(self, request, pedido, physician):
        from clinical.models import Encounter
        from tenancy.models import Tenant

        kind, formato = REQUEST_TO_DOCUMENT.get(pedido.kind, (None, None))
        if kind is None:
            raise Http404

        # Pedido de portal não nasce de consulta. Só se pendura num
        # atendimento **de hoje** escrito aqui — o paciente que pede na
        # recepção, durante a visita. Fora disso, o documento nasce sem
        # atendimento (`MedicalDocument.encounter` é opcional desde a
        # renovação por telefone), e o PDF sai com a data da emissão.
        #
        # Até 2026-11-02 ele ia para o **último** atendimento do paciente,
        # e o PDF imprime a data do atendimento: a receita pedida em
        # novembro saía datada da consulta de junho — e, depois da migração
        # do iClin, da anotação de lá. Quando não havia atendimento, abria
        # um registro em rascunho, que contava como visita para a janela de
        # 180 dias do próprio portal sem o paciente ter vindo.
        encounter = (
            Encounter.objects.filter(
                tenant_id=pedido.tenant_id, patient=pedido.patient, legacy_id='',
                occurred_at__date=timezone.localdate(),
            ).order_by('-occurred_at').first()
        )

        # O conteúdo vem do formulário, e não mais direto do pedido: o
        # médico corrige antes de o rascunho existir. Se nada foi enviado
        # — envio antigo, JavaScript desligado — cai no texto do paciente,
        # que era o comportamento anterior.
        form = _draft_form(pedido, data=request.POST) if request.POST.get('conteudo_revisado') else None
        if form is not None:
            if not form.is_valid():
                messages.error(request, 'Confira o conteúdo do documento antes de gerar o rascunho.')
                return render(request, 'documents/request_detail.html',
                              _draft_context(request, pedido, form=form), status=400)
            # O valor como o formulário o limpou, como na tela de emissão: a
            # marca de uso contínuo e a confirmação da classificação são
            # booleanas, e virar texto aqui as perderia.
            conteudo = {name: form.cleaned_data.get(name) for name in document_kinds.all_fields(kind)}
            # O formato da receita não é escolha do paciente: quem pediu
            # "receita de controle especial" no portal descreveu o que
            # precisa, e é o médico quem decide a modalidade. O campo vem
            # do formulário, com o do pedido como valor inicial.
            if kind == 'prescription' and not conteudo.get('prescription_format'):
                conteudo['prescription_format'] = formato or 'simple'
        else:
            conteudo = _content_from_request(pedido, kind, formato)

        # A pergunta que a trilha responde é "o documento repete o que o
        # paciente escreveu, ou passou por revisão?".
        original = _content_from_request(pedido, kind, formato)
        alterado = any(
            _como_texto(conteudo.get(campo)) != _como_texto(original.get(campo))
            for campo in document_kinds.all_fields(kind)
        )

        tenant = Tenant.objects.get(id=pedido.tenant_id)
        try:
            with transaction.atomic():
                documento = issuance.create_draft(
                    tenant, pedido.patient, encounter, physician, request.user.id,
                    kind, conteudo,
                )
                atendido = pedidos_do_portal.marcar_atendido(
                    pedido, documento, physician, request.user.id, alterado,
                )
                if not atendido:
                    # Outro médico respondeu enquanto esta tela estava
                    # aberta: nada é criado, para não sobrar um rascunho
                    # pendurado num pedido que teve outro desfecho.
                    transaction.set_rollback(True)
        except (ValueError, issuance.MissingPhysicianProfile) as exc:
            # A recusa da receita (a classificação da lista oficial, o limite
            # de medicamentos, o endereço do controle especial) volta para o
            # formulário com o que foi digitado. Redirecionar, como era,
            # apagava a receita inteira da tela junto com o erro.
            if form is not None:
                form.add_error(None, str(exc))
                return render(request, 'documents/request_detail.html',
                              _draft_context(request, pedido, form=form), status=400)
            messages.error(request, str(exc))
            return redirect('documents:request-detail', request_id=pedido.id)
        if not atendido:
            messages.error(request, 'Este pedido já foi respondido.')
            return redirect('documents:request-detail', request_id=pedido.id)

        messages.success(
            request,
            'Rascunho criado. Revise o conteúdo antes de assinar.'
            if alterado else
            'Rascunho criado com o texto do paciente, sem alteração. Revise o conteúdo '
            'antes de assinar: ninguém o conferiu ainda.',
        )
        return redirect('documents:medical-detail', document_id=documento.id)


def _como_texto(valor):
    """Valor de campo para comparar: booleano falso e vazio são a mesma ausência."""
    if valor is None or valor is False:
        return ''
    return str(valor).strip()


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
        from sncr import receita

        linhas = [
            ' — '.join(p for p in [m.get('nome', ''), m.get('dose', ''), m.get('uso', '')] if p)
            for m in payload.get('medicacoes', [])
        ]
        conteudo = {
            'prescription_text': '\n'.join(linhas),
            'special_instructions': '',
            'prescription_format': formato or 'simple',
        }
        # Os itens da receita eletrônica, do mesmo pedido: o nome, a dose
        # como concentração e o modo de usar como posologia. A forma
        # farmacêutica e a quantidade o paciente não informa, e ficam em
        # branco para o médico — inventá-las seria escrever na receita o que
        # ninguém disse. Na receita impressa, `issuance` descarta os itens.
        for n, med in enumerate(pedidos_do_portal.medicacoes(pedido)[:receita.LIMITE_MEDICAMENTOS], 1):
            conteudo[f'item{n}_nome'] = (med.get('nome') or '').strip()
            conteudo[f'item{n}_concentracao'] = (med.get('dose') or '').strip()
            conteudo[f'item{n}_posologia'] = (med.get('uso') or '').strip()
        return conteudo
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
