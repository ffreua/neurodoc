"""Portal público de solicitações do paciente.

O paciente se identifica, descreve o que precisa, e o pedido entra numa
fila que o médico revisa. Nada do que se escreve aqui vira documento
sozinho: o médico decide o que emitir, inclusive não emitir.

O que este arquivo protege, e por quê:

**A identificação é um oráculo, se descuidada.** Um formulário que aceita
CPF e data de nascimento e responde "encontrado" ou "não encontrado"
permite a quem tiver uma lista de CPFs descobrir quem é paciente daquela
clínica — e ser paciente de uma clínica de neurologia é informação de
saúde. Por isso: limite de tentativas por IP, resposta idêntica para os
dois casos, e nenhum dado do paciente na resposta antes de acertar.

**O portal não mostra prontuário.** Ele aceita pedido. Não lista receitas
anteriores, não mostra diagnóstico e não confirma nada sobre o
tratamento — para isso existe o link do documento, que já tem a própria
prova de identidade.

**A sessão verificada expira.** Trinta minutos, como no portal que este
substitui: o computador da lan house não pode ficar com uma sessão aberta
capaz de pedir receita em nome de alguém.
"""

import secrets

from django.utils import timezone

from audit.services import protect_ip
from base.validators import is_valid_cpf
from base.net import client_ip

#: Versão do aviso de privacidade aceito. Muda quando o texto muda, e fica
#: gravado no pedido: demonstrar consentimento exige saber **a que** a
#: pessoa consentiu, não só que consentiu.
#:
#: `2026-10-v2`: a finalidade passou a incluir receber os laudos de exames
#: que o paciente envia (1.16). Os pedidos e envios anteriores continuam
#: com a versão que foi aceita.
PRIVACY_NOTICE_VERSION = '2026-10-v2'

SESSION_KEY = 'portal_patient'
SESSION_MAX_AGE_SECONDS = 30 * 60

#: Tentativas de identificação por IP, por janela. Oito é folgado para
#: quem erra a digitação e curto para quem varre uma lista.
LOOKUP_MAX_ATTEMPTS = 8
LOOKUP_WINDOW_SECONDS = 900

#: Pedidos por IP, por hora. Impede que o portal vire fila de mil pedidos
#: de um script — e mil pedidos falsos numa fila de revisão médica
#: escondem os verdadeiros.
SUBMIT_MAX_PER_HOUR = 12


class PortalUnavailable(Exception):
    """A clínica não publicou o portal."""


class TooManyAttempts(Exception):
    pass


def clinic_or_none(slug):
    """A clínica, se ela publicou o portal.

    Devolve `None` também quando a clínica existe e não publicou: a
    diferença entre "não existe" e "existe e está fechado" é informação
    sobre a clínica, e a página de erro é a mesma nos dois casos.
    """
    from tenancy.models import ClinicProfile, Tenant, TenantStatus

    tenant = Tenant.objects.filter(slug=slug, status=TenantStatus.ACTIVE).first()
    if tenant is None:
        return None, None
    profile = ClinicProfile.objects.filter(tenant=tenant).first()
    if profile is None or not profile.patient_portal_enabled:
        return None, None
    return tenant, profile


def _rate_limit(request, bucket, limit, window):
    """Conta tentativas por IP. Falha aberto se a cache estiver fora.

    Falhar fechado deixaria o portal inacessível numa indisponibilidade do
    Redis, o que transforma um problema de infraestrutura em paciente sem
    receita. O risco aceito é o inverso: durante a indisponibilidade, uma
    varredura passaria — e ela fica no log de auditoria.
    """
    from django.core.cache import cache

    ip = client_ip(request)
    key = f'portal:{bucket}:{ip}'
    try:
        cache.get_or_set(key, 0, window)
        return cache.incr(key) > limit
    except Exception:                                   # noqa: BLE001
        return False


def find_patient(tenant, cpf, birth_date):
    """O paciente daquela clínica com aquele CPF e aquela data.

    As duas coisas juntas, e sempre: só o CPF identificaria alguém a quem
    o CPF vazou, e só a data não identifica ninguém. Não é autenticação
    forte — é o mesmo par que o balcão pede ao telefone, e o que ele abre
    é a possibilidade de **pedir**, não de ler prontuário.
    """
    from patients.models import Patient, PatientStatus

    digits = ''.join(c for c in (cpf or '') if c.isdigit())
    if not is_valid_cpf(digits) or birth_date is None:
        return None
    return (
        Patient.objects
        .filter(tenant=tenant, cpf=digits, birth_date=birth_date, status=PatientStatus.ACTIVE)
        .first()
    )


def identify(request, tenant, cpf, birth_date):
    """Verifica e guarda o paciente na sessão. Levanta em excesso de tentativas."""
    from audit.services import record_audit_event

    if _rate_limit(request, 'lookup', LOOKUP_MAX_ATTEMPTS, LOOKUP_WINDOW_SECONDS):
        record_audit_event(
            None, tenant.id, 'documents.portal_lookup_throttled',
            object_type='tenant', object_id=tenant.id, outcome='denied',
        )
        raise TooManyAttempts(
            'Muitas tentativas a partir deste endereço. Aguarde alguns minutos.'
        )

    patient = find_patient(tenant, cpf, birth_date)
    record_audit_event(
        None, tenant.id, 'documents.portal_lookup',
        object_type='patient', object_id=patient.id if patient else None,
        outcome='success' if patient else 'denied',
    )
    if patient is None:
        return None

    request.session[SESSION_KEY] = {
        'patient_id': str(patient.id),
        'tenant_id': str(tenant.id),
        'at': timezone.now().isoformat(),
        # Token na sessão e no formulário: o envio só é aceito se os dois
        # baterem, o que impede reaproveitar uma sessão aberta noutra aba
        # para enviar um formulário montado à mão.
        'token': secrets.token_urlsafe(24),
        'privacy_at': timezone.now().isoformat(),
    }
    return patient


def verified_patient(request, tenant):
    """O paciente verificado nesta sessão, se ainda vale.

    Confere também o inquilino: uma sessão aberta no portal de uma clínica
    não pode valer no portal de outra, e as duas usam a mesma chave de
    sessão do mesmo navegador.
    """
    from patients.models import Patient

    data = request.session.get(SESSION_KEY)
    if not data or data.get('tenant_id') != str(tenant.id):
        return None
    quando = timezone.datetime.fromisoformat(data['at'])
    if (timezone.now() - quando).total_seconds() > SESSION_MAX_AGE_SECONDS:
        request.session.pop(SESSION_KEY, None)
        return None
    return Patient.objects.filter(id=data['patient_id'], tenant=tenant).first()


def identity_token(request):
    """O token da identificação em vigor, para ir no formulário."""
    return (request.session.get(SESSION_KEY) or {}).get('token', '')


def token_confere(request, enviado):
    """O formulário foi aberto para **esta** identificação?

    O token existia desde o começo, com o comentário prometendo a
    conferência, e nem o formulário o mandava nem o envio o conferia
    (auditoria de 2026-10-09, ND-1121-017). O caso real é o de quem pede
    por duas pessoas no mesmo navegador -- a mãe que pede a receita de um
    filho numa aba e identifica o outro na seguinte: o formulário da
    primeira aba era gravado na ficha do segundo filho.
    """
    atual = identity_token(request)
    return bool(atual) and bool(enviado) and secrets.compare_digest(str(atual), str(enviado))


def clear(request):
    request.session.pop(SESSION_KEY, None)


def submit(request, tenant, patient, kind, requester_name, requester_is_patient, payload):
    """Registra o pedido e encerra a sessão verificada.

    A sessão é encerrada de propósito: quem terminou de pedir não precisa
    de uma sessão aberta, e o computador compartilhado deixa de carregar
    uma identificação viva.
    """
    from audit.services import record_audit_event

    from .models import DocumentRequest

    if _rate_limit(request, 'submit', SUBMIT_MAX_PER_HOUR, 3600):
        raise TooManyAttempts(
            'Muitos pedidos a partir deste endereço. Aguarde e tente novamente.'
        )

    data = request.session.get(SESSION_KEY) or {}
    pedido = DocumentRequest.objects.create(
        tenant=tenant, patient=patient, kind=kind,
        requester_name=requester_name[:255],
        requester_is_patient=requester_is_patient,
        payload=payload,
        privacy_ack_at=timezone.datetime.fromisoformat(data['privacy_at'])
        if data.get('privacy_at') else timezone.now(),
        privacy_notice_version=PRIVACY_NOTICE_VERSION,
        origin_ip_protected=protect_ip(client_ip(request)),
    )
    record_audit_event(
        None, tenant.id, 'documents.portal_request_created',
        object_type='document_request', object_id=pedido.id, outcome='success',
        integrity_metadata={'kind': kind},
    )
    # Por capacidade, e não por papel: a fila exige capacidade clínica, e
    # avisar a secretária de um pedido que ela não pode abrir a informa de
    # que aquele paciente pediu alguma coisa e entrega um link que responde
    # 404.
    from notifications.services import notify_capability, patient_context
    from tenancy.permissions import Capability

    notify_capability(
        tenant, Capability.READ_CLINICAL, kind='portal_request',
        sanitized_title=f'{pedido.get_kind_display()} solicitada no portal',
        target_type='document_request', target_id=pedido.id,
        context=patient_context(
            patient,
            requester=('' if requester_is_patient else requester_name),
        ),
    )
    clear(request)
    return pedido
