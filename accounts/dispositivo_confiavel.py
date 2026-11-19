"""Confiar num dispositivo: entrar sem o código do segundo fator (2026-11-18).

**Por que existe.** O segundo fator é obrigatório para dono e médico
(`mfa.segundo_fator_exigido_hoje`), e o código pedido a cada entrada torna
o acesso ao prontuário mais lento no consultório. Decisão do titular,
autorizada pela Dra. Karina: a pessoa pode confiar no próprio dispositivo e,
nele, entrar só com a senha -- **por tempo indeterminado**, até revogar.

**O que não muda**, e é o que torna a opção defensável perante a LGPD
(art. 46, dado de saúde): o segundo fator continua obrigatório para
cadastrar e continua pedido em qualquer outro navegador. Quem rouba só a
senha não entra. E o login por dispositivo confiável **não** carimba o
código recente (`mfa.mark_recent_mfa`): assinar, mexer em certificado,
exportar o acervo, o TISS e o console continuam pedindo o código.

**Quem decide.** A clínica é a controladora; o contrato já põe "o MFA dos
usuários" sob controle do CONTRATANTE (Anexo I, 6.3). Por isso a opção
nasce **proibida** em toda clínica (`Tenant.dispositivo_confiavel_permitido`)
e só o responsável a libera. Quem atende em várias clínicas só usa se
**todas** permitirem: a mais restritiva vence, porque é a mesma sessão que
abre o prontuário de todas. Superadministrador e equipe técnica nunca: o
console e o admin perguntam `is_verified()`, que este login concede.

**Sem prazo, mas não sem fim.** O servidor não guarda validade. A cada
entrada, confere: dispositivo não revogado, da mesma pessoa, com o token
certo, com a mesma senha (`senha_marca`) e o mesmo segundo fator
(`totp_device_id`). Senha trocada ou segundo fator refeito revogam na hora,
com o motivo. O navegador limita a vida de um cookie (o Chrome, a 400
dias); por isso o cookie é renovado a cada entrada, e só um dispositivo sem
uso por mais de um ano perde a marca -- e aí pede o código, que é o lado
seguro.

**Prova.** Cada dispositivo guarda o termo aceito inteiro, com versão e
SHA-256, o navegador e o IP protegido; e a trilha registra o aceite, cada
entrada sem o código, a revogação e o motivo. Nada clínico entra em nada
disso.

**O cookie** vale só em `/accounts/` (é lá que ficam o login e a lista em
Minha conta): o resto do sistema nunca o recebe, e um vazamento numa tela
qualquer não o alcança. `HttpOnly`, `Secure` em produção, `SameSite=Lax`.
"""
import hashlib
import hmac
import secrets
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

#: Nome neutro, igual nos dois sistemas: o domínio já separa um do outro.
COOKIE = 'dispositivo_confiavel'
COOKIE_CAMINHO = '/accounts/'
#: O teto que o Chrome aplica (400 dias). Pedir mais não dá mais: o
#: navegador corta em silêncio. A renovação a cada entrada é o que faz o
#: "sem prazo" valer para quem usa.
COOKIE_SEGUNDOS = 400 * 24 * 3600

TERMO_VERSAO = '1.0'
TERMO_TEXTO = (
    'TERMO DE CONFIANÇA DE DISPOSITIVO — versão 1.0\n'
    '\n'
    'Ao marcar a opção "Confiar neste dispositivo", declaro que:\n'
    '\n'
    '1. Este dispositivo (computador, celular ou tablet) e este navegador são de uso '
    'pessoal meu, protegidos por senha ou bloqueio de tela, e não são compartilhados com '
    'outras pessoas — por exemplo, o computador da recepção.\n'
    '\n'
    '2. Entendo que, neste dispositivo, o código do aplicativo autenticador deixará de ser '
    'pedido ao entrar, por tempo indeterminado, até que a confiança seja revogada. A senha '
    'continua sendo pedida. O código continua sendo pedido em qualquer outro dispositivo e '
    'para as ações sensíveis: assinatura digital, certificados, exportação de dados e '
    'faturamento TISS.\n'
    '\n'
    '3. Quem tiver acesso a este dispositivo e souber a minha senha poderá entrar na minha '
    'conta e ver tudo o que eu posso ver, inclusive prontuários. São dados de saúde, '
    'protegidos pela Lei Geral de Proteção de Dados. Cabe a mim proteger o dispositivo e a '
    'senha, como prevê o Contrato de Adesão (cláusula 6.1 e Anexo I, item 6.3).\n'
    '\n'
    '4. Posso revogar a confiança a qualquer momento, em Minha conta. Ela é revogada '
    'automaticamente se eu trocar a senha, se o meu segundo fator for refeito ou se a '
    'organização deixar de permitir esta opção. Se o dispositivo for perdido, roubado ou '
    'passar a outra pessoa, revogarei a confiança imediatamente e trocarei a minha senha.\n'
    '\n'
    '5. A confiança, cada entrada feita sem o código e a revogação ficam registradas na '
    'trilha de auditoria do sistema, com data, hora, endereço de rede e navegador.\n'
    '\n'
    '6. A organização em que atendo autorizou esta opção. Usá-la é escolha minha, e não '
    'dispensa as demais medidas de segurança previstas no contrato.'
)
TERMO_SHA256 = hashlib.sha256(TERMO_TEXTO.encode('utf-8')).hexdigest()


def _hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def senha_marca(user):
    """Marca da senha atual, que muda quando a senha muda.

    HMAC com a `SECRET_KEY` sobre o hash já guardado da senha: não revela
    nada da senha e não é comparável fora desta instalação. Trocar a
    `SECRET_KEY` derruba todos os dispositivos -- o lado seguro.
    """
    return hmac.new(
        settings.SECRET_KEY.encode('utf-8'), (user.password or '').encode('utf-8'), hashlib.sha256,
    ).hexdigest()


def descrever_navegador(user_agent):
    """'Chrome no Windows', para a lista em Minha conta. Só aproximação."""
    ua = user_agent or ''
    if 'Edg/' in ua:
        navegador = 'Edge'
    elif 'Firefox/' in ua:
        navegador = 'Firefox'
    elif 'Chrome/' in ua or 'CriOS/' in ua:
        navegador = 'Chrome'
    elif 'Safari/' in ua:
        navegador = 'Safari'
    else:
        navegador = 'Navegador'
    if 'Android' in ua:
        sistema = 'Android'
    elif 'iPhone' in ua or 'iPad' in ua:
        sistema = 'iPhone/iPad'
    elif 'Windows' in ua:
        sistema = 'Windows'
    elif 'Mac OS X' in ua or 'Macintosh' in ua:
        sistema = 'macOS'
    elif 'Linux' in ua:
        sistema = 'Linux'
    else:
        sistema = 'sistema desconhecido'
    return f'{navegador} no {sistema}'


def politica_permite(user):
    """Se esta pessoa pode usar dispositivo confiável **agora**.

    Lido do banco a cada entrada, como o `AccessContext`: o vínculo
    revogado e a clínica que mudou de ideia valem na hora. Sem vínculo
    ativo nenhum, não: não há controladora que tenha autorizado.
    """
    from tenancy.models import Membership, MembershipStatus

    if not user.is_active or user.is_superuser or user.is_staff:
        return False
    permissoes = list(
        Membership.objects.filter(user=user, status=MembershipStatus.ACTIVE)
        .values_list('tenant__dispositivo_confiavel_permitido', flat=True)
    )
    return bool(permissoes) and all(permissoes)


def _ler_cookie(request):
    valor = request.COOKIES.get(COOKIE) or ''
    ident, _, token = valor.partition('.')
    if not ident or not token or len(token) > 100:
        return None, None
    try:
        uuid.UUID(ident)
    except ValueError:
        return None, None
    return ident, token


def dispositivo_do_pedido(request, user):
    """O dispositivo confiável que este navegador apresenta, ou None.

    Não olha a política da clínica: isso é com quem chama. Senha trocada ou
    segundo fator refeito revogam aqui mesmo, com o motivo e na trilha, e o
    resultado é None.
    """
    from .mfa import get_confirmed_device
    from .models import DispositivoConfiavel

    ident, token = _ler_cookie(request)
    if ident is None:
        return None
    dispositivo = DispositivoConfiavel.objects.filter(id=ident, user=user, revogado_em=None).first()
    if dispositivo is None or not hmac.compare_digest(dispositivo.token_hash, _hash(token)):
        return None
    if not hmac.compare_digest(dispositivo.senha_marca, senha_marca(user)):
        revogar(dispositivo, DispositivoConfiavel.Motivo.SENHA_TROCADA, ator=user, request=request)
        return None
    totp = get_confirmed_device(user)
    if totp is None or totp.id != dispositivo.totp_device_id:
        revogar(dispositivo, DispositivoConfiavel.Motivo.SEGUNDO_FATOR_REFEITO, ator=user, request=request)
        return None
    return dispositivo


def dispositivo_atual_id(request):
    """O id que o cookie deste navegador traz, só para marcar a lista."""
    ident, _ = _ler_cookie(request)
    return ident


@transaction.atomic
def confiar(request, user, response):
    """Cria o dispositivo, grava o termo aceito e põe o cookie na resposta."""
    from audit.services import protect_ip, record_audit_event
    from base.net import client_ip

    from .mfa import get_confirmed_device
    from .models import DispositivoConfiavel

    totp = get_confirmed_device(user)
    token = secrets.token_urlsafe(32)
    user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:300]
    ip = client_ip(request)
    dispositivo = DispositivoConfiavel.objects.create(
        user=user, token_hash=_hash(token), senha_marca=senha_marca(user),
        totp_device_id=totp.id, descricao=descrever_navegador(user_agent)[:80],
        user_agent=user_agent, ip_protegido=protect_ip(ip),
        termo_versao=TERMO_VERSAO, termo_sha256=TERMO_SHA256, termo_texto=TERMO_TEXTO,
        ultimo_uso_em=timezone.now(),
    )
    record_audit_event(
        user, None, 'accounts.dispositivo_confiado', object_type='dispositivo_confiavel',
        object_id=dispositivo.id, outcome='success', origin_ip=ip,
        integrity_metadata={
            'termo_versao': TERMO_VERSAO, 'termo_sha256': TERMO_SHA256,
            'navegador': dispositivo.descricao,
        },
    )
    por_cookie(response, dispositivo.id, token)
    return dispositivo


def por_cookie(response, ident, token):
    response.set_cookie(
        COOKIE, f'{ident}.{token}', max_age=COOKIE_SEGUNDOS, path=COOKIE_CAMINHO,
        secure=settings.SESSION_COOKIE_SECURE, httponly=True, samesite='Lax',
    )


def renovar_cookie(request, response):
    """Devolve o mesmo cookie com o prazo do navegador zerado de novo."""
    ident, token = _ler_cookie(request)
    if ident is not None:
        por_cookie(response, ident, token)


def apagar_cookie(response):
    response.delete_cookie(COOKIE, path=COOKIE_CAMINHO, samesite='Lax')


def registrar_uso(request, dispositivo):
    """A entrada sem o código, na trilha como login, marcada como tal."""
    from audit.services import record_audit_event
    from base.net import client_ip

    from .models import DispositivoConfiavel

    agora = timezone.now()
    DispositivoConfiavel.objects.filter(id=dispositivo.id).update(ultimo_uso_em=agora, updated_at=agora)
    record_audit_event(
        dispositivo.user, None, 'auth.login', outcome='success', origin_ip=client_ip(request),
        object_type='dispositivo_confiavel', object_id=dispositivo.id,
        integrity_metadata={'mfa': 'dispositivo_confiavel'},
    )


def revogar(dispositivo, motivo, *, ator=None, tenant=None, request=None):
    """Revoga um dispositivo, uma vez só, e registra quem e por quê."""
    from audit.services import record_audit_event
    from base.net import client_ip

    from .models import DispositivoConfiavel

    agora = timezone.now()
    mudou = DispositivoConfiavel.objects.filter(id=dispositivo.id, revogado_em=None).update(
        revogado_em=agora, revogado_motivo=motivo, updated_at=agora,
    )
    if mudou:
        record_audit_event(
            ator, tenant, 'accounts.dispositivo_revogado', object_type='dispositivo_confiavel',
            object_id=dispositivo.id, outcome='success',
            origin_ip=client_ip(request) if request is not None else None,
            integrity_metadata={'motivo': motivo, 'titular_id': str(dispositivo.user_id)},
        )
    return bool(mudou)


def revogar_da_pessoa(user, motivo, *, ator=None, tenant=None, request=None):
    from .models import DispositivoConfiavel

    return sum(
        revogar(d, motivo, ator=ator, tenant=tenant, request=request)
        for d in DispositivoConfiavel.objects.filter(user=user, revogado_em=None)
    )


def revogar_da_clinica(tenant, *, ator, request=None):
    """Quando a clínica deixa de permitir: revoga os de toda a equipe ativa.

    A política já recusaria na entrada seguinte; revogar é para que um
    "permitir" mais tarde não ressuscite em silêncio a confiança dada sob a
    autorização anterior. Quem quiser de novo aceita o termo de novo.
    """
    from tenancy.models import Membership, MembershipStatus

    from .models import DispositivoConfiavel

    usuarios = list(
        Membership.objects.filter(tenant=tenant, status=MembershipStatus.ACTIVE)
        .values_list('user_id', flat=True)
    )
    return sum(
        revogar(d, DispositivoConfiavel.Motivo.CLINICA_PROIBIU, ator=ator, tenant=tenant, request=request)
        for d in DispositivoConfiavel.objects.filter(user_id__in=usuarios, revogado_em=None)
    )


def ativos_da_pessoa(user):
    from .models import DispositivoConfiavel

    return (
        DispositivoConfiavel.objects.filter(user=user, revogado_em=None)
        .order_by('-ultimo_uso_em', '-created_at')
    )
