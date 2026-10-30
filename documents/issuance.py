import hashlib
import secrets

from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event
from events.models import OutboxEvent, OutboxEventStatus

from sncr import receita as sncr_receita

from . import document_kinds, rce_impressa
from .credentials import credential_is_usable, decrypt_pfx_bytes
from .models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from .pdf import render_medical_document_pdf
from .retention import soft_delete_attachment
from .signing import InvalidPfxPassword, SigningFailed, sign_pdf
from .signing_sessions import SigningSessionKeyMissing, get_active_session, unlock_password
from .storage import store_generated_attachment

DOCUMENT_ISSUED_TOPIC = 'documents.document_issued'


class NotReadyToSign(Exception):
    pass


class SigningNotAuthorized(Exception):
    pass


class MissingPhysicianProfile(Exception):
    pass


def _validate_special_control(kind, content_fields, patient):
    """Receita de controle especial exige endereço completo do paciente.

    A recusa acontece aqui, na criação do rascunho, e não na impressão: a
    farmácia devolve a receita de controle especial sem endereço, e
    descobrir isso com o paciente no balcão significa que ele volta ao
    consultório. Barrar antes de assinar é o único momento em que corrigir
    ainda é barato.

    Portaria SVS/MS 344/98 e sua regulamentação (Portaria 6/99, anexo XVII):
    a 1ª via fica retida na farmácia e precisa identificar o comprador.
    """
    from .pdf.prescription import SPECIAL_CONTROL

    if kind != MedicalDocumentKind.PRESCRIPTION:
        return
    if (content_fields.get('prescription_format') or '') != SPECIAL_CONTROL:
        return
    if not (patient.street and patient.city and patient.state):
        raise ValueError(
            'A receita de controle especial exige o endereço completo do paciente '
            '(logradouro, município e UF). Complete o cadastro antes de emitir, '
            'ou use a receita simples.'
        )


def _conteudo_da_receita(kind, content_fields, patient):
    """Prepara o conteúdo da receita conforme o formato.

    A receita **eletrônica do SNCR** passa por `sncr.receita.preparar`, que
    classifica cada item pela lista oficial, aplica os limites e devolve o
    conteúdo com os itens estruturados (e a prescrição em texto, para quem
    já lê esse campo). Qualquer outro documento só perde os campos dos itens,
    que o formulário manda vazios.
    """
    from sncr import receita

    campos = dict(content_fields)
    confirmada = bool(campos.pop('classificacao_confirmada', False))
    if kind == MedicalDocumentKind.PRESCRIPTION and campos.get('prescription_format') in receita.FORMATOS:
        return receita.preparar(campos, patient, confirmada=confirmada)
    for nome in receita.CAMPOS_DO_FORMULARIO:
        campos.pop(nome, None)
    return campos


def _as_issued(document):
    """O documento com estado `issued` **só em memória**, para desenhar.

    O PDF final precisa sair sem a tarja de rascunho e com a data de
    emissão, mas gravar `status=issued` antes de a assinatura existir
    deixaria, se a assinatura falhasse, um documento marcado como emitido
    sem arquivo assinado nenhum. O objeto real segue em `signing` até o
    fim; o que muda aqui é uma cópia que só o desenho enxerga.
    """
    document.status = MedicalDocumentStatus.ISSUED
    return document


def _as_paper(document):
    """Cópia em memória marcada como emitida no papel, só para desenhar.

    Mesma razão de `_as_issued`: o estado real só muda depois de o arquivo
    existir.
    """
    document.status = MedicalDocumentStatus.ISSUED_ON_PAPER
    return document


@transaction.atomic
def issue_on_paper(document, actor_id):
    """Emite para ser assinado à caneta e carimbado.

    É o caminho de quem não usa certificado digital, ou de quem está sem
    ele naquele dia. O documento ganha número e data como qualquer outro, e
    o PDF sai **sem** a tarja de rascunho e **sem** QR — ver
    `MedicalDocumentStatus.ISSUED_ON_PAPER` e `pdf/common._qr_flowable`.

    Sem `SELECT ... FOR UPDATE` seria possível emitir duas vezes em duas
    abas e gastar dois números de documento para a mesma receita; o
    `select_for_update` fecha isso, como no caminho da assinatura digital.
    """
    locked = MedicalDocument.objects.select_for_update().get(pk=document.pk)
    if locked.status not in (MedicalDocumentStatus.DRAFT, MedicalDocumentStatus.READY_TO_SIGN):
        raise ValueError('Só um rascunho ou documento pronto para assinar pode ser emitido em papel.')
    if sncr_receita.eh_eletronica(locked):
        # O modelo eletrônico impresso sem número nem assinatura digital
        # pareceria uma receita válida e não é (decisão I10). O papel é outro
        # documento: a Receita de Controle Especial no leiaute da clínica.
        raise ValueError(
            'A receita eletrônica do SNCR só existe assinada digitalmente, com o número da Anvisa. '
            'Para emitir em papel, crie uma receita de controle especial (ou simples) impressa.'
        )
    locked.document_number = _next_document_number(locked.tenant_id, locked.kind)
    locked.issued_at = timezone.now()
    pdf_bytes = render_medical_document_pdf(_as_paper(locked))
    locked.status = MedicalDocumentStatus.ISSUED_ON_PAPER
    locked.pdf_attachment = store_generated_attachment(
        locked.tenant, locked.patient, locked.physician.user, pdf_bytes,
        f'{locked.kind}_{locked.id}_papel.pdf', encounter=locked.encounter,
    )
    locked.save(update_fields=['document_number', 'issued_at', 'status', 'pdf_attachment'])
    record_audit_event(
        actor_id, locked.tenant_id, 'documents.medicaldocument_issued_on_paper',
        object_type='medical_document', object_id=locked.id, outcome='success',
        purpose='Emitido para assinatura de proprio punho',
    )
    return locked


def new_validation_token():
    """Código do QR e da página pública de verificação.

    16 caracteres hexadecimais — 64 bits — porque ele é a única coisa que
    protege a página de verificação: quem tiver o código vê os metadados
    daquele documento. Curto o bastante para caber impresso e para alguém
    digitar quando o QR não lê; longo o bastante para não se descobrir um
    código por tentativa.

    Aleatório, e nunca derivado do número do documento: uma sequência no QR
    permitiria, a partir da própria receita, montar o código da receita
    seguinte e consultar o documento de outro paciente.
    """
    return secrets.token_hex(8).upper()


def _lock_document_number(tenant_id, year):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
            [f'medicaldocument_number:{tenant_id}:{year}'],
        )


@transaction.atomic
def _next_document_number(tenant_id, kind):
    year = timezone.now().year
    _lock_document_number(tenant_id, year)
    prefix = document_kinds.NUMBER_PREFIX[kind]
    count = MedicalDocument.objects.filter(
        tenant_id=tenant_id, document_number__startswith=f'{prefix}-{year}-',
    ).count()
    return f'{prefix}-{year}-{count + 1:06d}'


@transaction.atomic
def create_draft(tenant, patient, encounter, physician_membership, actor_id, kind, content_fields,
                  version=1, replaces_document=None):
    from accounts.models import PhysicianProfile

    if not PhysicianProfile.objects.filter(user_id=physician_membership.user_id).exists():
        raise MissingPhysicianProfile('Este médico ainda não tem CRM registrado no perfil. '
            'Preencha em Minha conta antes de emitir documento.')
    content_fields = _conteudo_da_receita(kind, content_fields, patient)
    document_kinds.validate_content(kind, content_fields)
    _validate_special_control(kind, content_fields, patient)
    document = MedicalDocument.objects.create(
        tenant=tenant, patient=patient, encounter=encounter, physician=physician_membership,
        kind=kind, version=version, replaces_document=replaces_document,
        content_snapshot=dict(content_fields), status=MedicalDocumentStatus.DRAFT,
        validation_token=new_validation_token(),
    )
    pdf_bytes = render_medical_document_pdf(document)
    document.pdf_attachment = store_generated_attachment(
        tenant, patient, physician_membership.user, pdf_bytes,
        f'{kind}_{document.id}_draft.pdf', encounter=encounter,
    )
    document.save(update_fields=['pdf_attachment'])
    record_audit_event(
        actor_id, tenant.id, 'documents.medicaldocument_created',
        object_type='medical_document', object_id=document.id, outcome='success',
    )
    return document


@transaction.atomic
def create_correction(original, actor_id, content_fields, reason=''):
    if original.status != MedicalDocumentStatus.ISSUED:
        raise NotReadyToSign('Só documento emitido pode ser corrigido.')
    if sncr_receita.eh_eletronica(original):
        # O número do SNCR da original já foi usado e não se cancela (FAQ
        # P35–36); a "correção" seria outra receita, com outro número, e a
        # primeira continuaria valendo na farmácia. Emite-se uma nova.
        raise ValueError(
            'A receita eletrônica do SNCR não é retificada: o número dela já foi usado. '
            'Emita uma receita nova.'
        )
    corrected = create_draft(
        original.tenant, original.patient, original.encounter, original.physician, actor_id,
        original.kind, content_fields, version=original.version + 1, replaces_document=original,
    )
    # O motivo vai para a trilha, e não para o documento.
    #
    # A tela pedia o motivo da correção e o descartava: o campo tinha o
    # mesmo nome do "Motivo" do encaminhamento e, nos demais tipos, não
    # existia no conteúdo — o médico escrevia e nada era guardado. O motivo
    # de uma retificação é registro de quem alterou o quê e por quê, e é na
    # auditoria que ele responde a isso, não no papel entregue ao paciente.
    record_audit_event(
        actor_id, original.tenant_id, 'documents.medicaldocument_corrected',
        object_type='medical_document', object_id=corrected.id, outcome='success',
        purpose=(reason or '')[:255],
        integrity_metadata={
            'replaces': str(original.id),
            'replaces_number': original.document_number,
            'version': corrected.version,
        },
    )
    return corrected


def mark_reviewed(document, actor_id):
    if document.status != MedicalDocumentStatus.DRAFT:
        raise NotReadyToSign('Este documento não está mais em rascunho.')
    document.status = MedicalDocumentStatus.READY_TO_SIGN
    document.save(update_fields=['status'])
    record_audit_event(
        actor_id, document.tenant_id, 'documents.medicaldocument_reviewed',
        object_type='medical_document', object_id=document.id, outcome='success',
    )
    return document


def discard_document(document, actor_id):
    if document.status not in (MedicalDocumentStatus.DRAFT, MedicalDocumentStatus.READY_TO_SIGN, MedicalDocumentStatus.FAILED):
        raise NotReadyToSign('Documento já emitido não pode ser descartado.')
    if document.pdf_attachment_id:
        soft_delete_attachment(document.pdf_attachment, actor_id, 'medical document discarded')
    record_audit_event(
        actor_id, document.tenant_id, 'documents.medicaldocument_discarded',
        object_type='medical_document', object_id=document.id, outcome='success',
    )
    document.delete()


@transaction.atomic
def converter_para_impressa(document, actor_id):
    """A contingência da receita eletrônica: refazê-la como receita impressa.

    Quando o SNCR não dá — integração desligada, número que falta, bloco
    que não chegou —, o médico pode seguir pelo papel, **escolhendo** isso
    (decisão I15): nada converte sozinho. Cria um rascunho novo no formato
    impresso correspondente — a RCE eletrônica vira a RCE impressa no
    leiaute da clínica (D6); a RET vira a receita simples, que é como a
    retenção sai no papel — com a mesma prescrição em texto, e descarta o
    rascunho eletrônico. Os dois na mesma transação: ou fica o eletrônico,
    ou fica o impresso.

    Só rascunho: a eletrônica emitida já tem número da Anvisa e vale como
    está (decisão I10).
    """
    from .pdf.prescription import SIMPLE, SPECIAL_CONTROL

    locked = MedicalDocument.objects.select_for_update().get(pk=document.pk)
    tipo = sncr_receita.tipo_do_documento(locked)
    if tipo is None:
        raise ValueError('Só a receita eletrônica do SNCR é refeita como impressa.')
    if locked.status not in (MedicalDocumentStatus.DRAFT, MedicalDocumentStatus.READY_TO_SIGN):
        raise ValueError('Só o rascunho da receita eletrônica pode ser refeito como impresso.')
    snapshot = locked.content_snapshot or {}
    formato = SPECIAL_CONTROL if tipo == 'RCE' else SIMPLE
    novo = create_draft(
        locked.tenant, locked.patient, locked.encounter, locked.physician, actor_id,
        MedicalDocumentKind.PRESCRIPTION, {
            'prescription_format': formato,
            'prescription_text': snapshot.get('prescription_text', ''),
            'special_instructions': snapshot.get('special_instructions', ''),
        },
    )
    record_audit_event(
        actor_id, locked.tenant_id, 'documents.medicaldocument_converted_to_paper',
        object_type='medical_document', object_id=novo.id, outcome='success',
        integrity_metadata={'origem': str(locked.id), 'de': snapshot.get('prescription_format'), 'para': formato},
    )
    discard_document(locked, actor_id)
    return novo


def sign_and_issue(document, request, physician_membership):
    """Assina e emite; a falha é registrada **depois** de desfeita.

    Enforces the full authorization chain per document, per PRD 12.2:
    active signing session bound to *this* web session, a still-usable
    credential, and the ephemeral tmpfs key actually present.

    Qualquer falha desfaz a transação inteira -- o número do documento, o
    estado "assinando", o PDF desenhado -- e o documento continua "pronto
    para assinar", para o médico tentar de novo. Era o que acontecia na
    prática, embora este texto prometesse um estado terminal `failed` para
    o erro inesperado: o `except` gravava `failed` e o evento de auditoria
    e relançava a exceção **dentro** do `atomic`, que desfazia os dois
    (auditoria de 2026-10-09, ND-1121-015). Ficou o comportamento que o
    médico vê, que é o certo -- o erro inesperado da biblioteca de
    assinatura não é culpa do documento --, e voltou o que se perdia: o
    registro. Senha errada no certificado, chave de sessão ausente e erro
    da assinatura entram na trilha numa transação própria, depois do
    rollback.
    """
    try:
        return _sign_and_issue(document, request, physician_membership)
    except Exception as exc:
        falha = getattr(exc, 'nd_falha_de_assinatura', None)
        if falha is not None:
            outcome, motivo = falha
            record_audit_event(
                physician_membership.user_id, physician_membership.tenant_id,
                'documents.medicaldocument_sign_failed',
                object_type='medical_document', object_id=document.id, outcome=outcome,
                integrity_metadata={'reason': motivo},
            )
        raise


def _reservar_numeros_sncr(locked, physician_membership, session):
    """Reserva os números do SNCR da receita eletrônica, ou `None` para as outras.

    **Um número por medicamento** (decisão I12): cada medicamento sai na sua
    folha do modelo oficial, e cada folha é uma receita com número próprio —
    o paciente que compra em farmácias diferentes leva a cada uma a folha
    dela, e a farmácia registra o uso daquele número só. Falta número para
    uma folha, nenhuma sai: a exceção desfaz a transação e as reservas.

    Dentro da transação da assinatura, de propósito: se o desenho ou a
    assinatura falharem, o rollback devolve o número a livre — e é seguro,
    porque o PDF com aquele número só existiu na memória e nunca saiu do
    servidor. O número é **do médico** (o bloco é dele, decisão D3): outro
    médico da mesma clínica nunca o recebe. Consumido só depois de assinado.
    """
    tipo = sncr_receita.tipo_do_documento(locked)
    if tipo is None:
        return None
    from sncr import numeracao
    from sncr.models import Configuracao

    config = Configuracao.carregar()
    if not config.ativo:
        raise _falhou(NotReadyToSign(
            'A receita eletrônica com numeração do SNCR está desligada nesta instalação. '
            'Use “Refazer como receita impressa”.'
        ), 'denied', 'sncr_desligado')
    perfil = physician_membership.user.physician_profile
    folhas = len((locked.content_snapshot or {}).get('itens') or [])
    try:
        numeros = numeracao.reservar_varios(perfil, tipo, config.ambiente, locked, locked.tenant_id, folhas)
    except numeracao.SemNumeroLivre as exc:
        raise _falhou(NotReadyToSign(
            f'Você não tem números do SNCR livres para as {folhas} folha(s) desta receita (um por '
            'medicamento). Peça um bloco em “Numeração SNCR” (entrando com o Gov.br) e assine de '
            'novo — o rascunho continua pronto, e nenhum número foi gasto. Se não puder esperar, '
            'use “Refazer como receita impressa”.'
        ), 'denied', 'sncr_sem_numero') from exc
    locked.nd_numeros_sncr = [n.numero for n in numeros]
    locked.nd_ambiente_sncr = config.ambiente
    locked.nd_registro_assinatura = ''
    return numeros


def _falhou(exc, outcome, motivo):
    """Marca a exceção com o que `sign_and_issue` registra depois do rollback."""
    exc.nd_falha_de_assinatura = (outcome, motivo)
    return exc


@transaction.atomic
def _sign_and_issue(document, request, physician_membership):
    locked = MedicalDocument.objects.select_for_update().get(id=document.id)
    if locked.status != MedicalDocumentStatus.READY_TO_SIGN:
        raise NotReadyToSign('O documento ainda não está pronto para assinar. Revise o rascunho antes.')
    if locked.physician_id != physician_membership.id:
        raise SigningNotAuthorized('Este documento é de outro médico.')
    # A RCE do leiaute da clínica não tem número do SNCR e, desde
    # 31/10/2026, não é assinada digitalmente (`rce_impressa`). A recusa vem
    # antes da sessão de assinatura, para o médico ler o motivo e não um
    # pedido de certificado.
    if rce_impressa.assinatura_digital_bloqueada(locked):
        raise _falhou(
            NotReadyToSign(rce_impressa.recusa()),
            'denied', rce_impressa.MOTIVO_AUDITORIA,
        )

    session = get_active_session(request, physician_membership)
    if session is None:
        raise SigningNotAuthorized('A sessão de assinatura não está aberta neste navegador. Desbloqueie o certificado de novo.')
    if not credential_is_usable(session.credential):
        raise SigningNotAuthorized('O certificado está revogado, vencido ou ainda não vale. Cadastre um certificado válido.')

    try:
        password = unlock_password(session)
    except SigningSessionKeyMissing as exc:
        raise _falhou(SigningNotAuthorized(str(exc)), 'denied', 'signing_session_key_missing') from exc

    locked.status = MedicalDocumentStatus.SIGNING
    locked.save(update_fields=['status'])

    numeros_sncr = _reservar_numeros_sncr(locked, physician_membership, session)

    # O PDF assinado é montado **agora**, e não é o rascunho.
    #
    # Antes se assinava o arquivo gerado na criação do rascunho, e aquele
    # arquivo trazia impresso "RASCUNHO SEM VALIDADE — só vale depois de
    # revisado e assinado" e, no lugar do número, "RASCUNHO — sem validade
    # até a emissão". O documento saía assinado dizendo de si mesmo que não
    # valia — e o número, que só é atribuído aqui, nunca chegava ao papel.
    #
    # A ordem tem de ser esta: número, estado, então desenhar, então
    # assinar. Assinar primeiro e carimbar depois invalidaria a assinatura,
    # que cobre os bytes do arquivo inteiro.
    locked.document_number = _next_document_number(locked.tenant_id, locked.kind)
    locked.issued_at = timezone.now()
    if numeros_sncr is not None:
        from sncr.pdf_oficial import registro_de_assinatura

        locked.nd_registro_assinatura = registro_de_assinatura(
            physician_membership.user.physician_profile, session.credential, locked.issued_at,
        )
    if not locked.validation_token:
        # Documento criado antes de o código de verificação existir.
        locked.validation_token = new_validation_token()
    final_pdf = render_medical_document_pdf(_as_issued(locked))

    pfx_bytes = decrypt_pfx_bytes(session.credential)
    profile = physician_membership.user.physician_profile
    try:
        signed_bytes = sign_pdf(
            final_pdf, pfx_bytes, password,
            signer_name=profile.professional_name,
            reason=f'{document_kinds.TITLE[locked.kind]} — CRM {profile.crm_number}/{profile.crm_state}',
        )
    except InvalidPfxPassword as exc:
        raise _falhou(SigningNotAuthorized(str(exc)), 'denied', 'invalid_pfx_password') from exc
    except SigningFailed as exc:
        raise _falhou(exc, 'failure', 'signing_exception')
    finally:
        del pfx_bytes

    locked.signed_pdf_attachment = store_generated_attachment(
        locked.tenant, locked.patient, physician_membership.user, signed_bytes,
        f'{locked.kind}_{locked.document_number}_signed.pdf', encounter=locked.encounter,
    )
    locked.status = MedicalDocumentStatus.ISSUED
    locked.signature_metadata = {
        'certificate_serial': session.credential.certificate_serial,
        'certificate_fingerprint': session.credential.certificate_fingerprint,
        'signed_at': locked.issued_at.isoformat(),
        # Impressão digital do arquivo **assinado**, que é o que a página de
        # verificação compara. O rodapé do PDF mostra o começo dela; o
        # arquivo em si não pode conter o próprio hash inteiro, porque
        # escrevê-lo mudaria o hash.
        'content_sha256': hashlib.sha256(signed_bytes).hexdigest(),
    }
    if numeros_sncr is not None:
        from sncr import numeracao

        for numero in numeros_sncr:
            numeracao.consumir(numero)
        # Na ordem das folhas: o n-ésimo número é o do n-ésimo medicamento.
        locked.signature_metadata['sncr'] = {
            'numeros': [n.numero for n in numeros_sncr],
            'tipo': numeros_sncr[0].tipo,
            'ambiente': numeros_sncr[0].ambiente,
            'registro_assinatura': locked.nd_registro_assinatura,
        }
    locked.save(update_fields=[
        'document_number', 'signed_pdf_attachment', 'status', 'issued_at',
        'signature_metadata', 'validation_token',
    ])

    OutboxEvent.objects.get_or_create(
        tenant_id=locked.tenant_id, topic=DOCUMENT_ISSUED_TOPIC, aggregate_type='medical_document',
        aggregate_id=locked.id, event_version=locked.version,
        defaults={
            'payload_minimal': {'medical_document_id': str(locked.id), 'patient_id': str(locked.patient_id)},
            'available_at': timezone.now(),
            'status': OutboxEventStatus.PENDING,
        },
    )
    record_audit_event(
        physician_membership.user_id, locked.tenant_id, 'documents.medicaldocument_signed',
        object_type='medical_document', object_id=locked.id, outcome='success',
    )
    return locked
