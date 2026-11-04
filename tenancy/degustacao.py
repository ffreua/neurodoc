"""A degustação do plano Completo: sete dias, e depois o Gratuito.

Qualquer pessoa abre, pelo cartão do Completo na página de vendas, uma
clínica que **está de fato no Completo** durante sete dias — `Tenant.plan`
vale `complete`, e não um plano de faz de conta. É essa a escolha que
deixa a degustação segura: o plano é lido em umas sessenta linhas do
sistema (limites, IA, SMS, menu, telas), e nenhuma delas precisou saber
que degustação existe. A alternativa recusada era um "plano efetivo"
calculado na leitura, que exigiria trocar as sessenta e deixaria a
sexagésima primeira, a que alguém escrever amanhã, lendo o plano errado.

**O contrato é o do Gratuito** (decisão de 2026-11-04, conferida com a
advogada): quem entra pela degustação adere ao plano Gratuito, de prazo
indeterminado, e o aceite registra a degustação do Completo e o fim dela
como condição comercial. Por isso o oitavo dia não rescinde nada — a
clínica volta ao plano que contratou.

**O oitavo dia**, em `encerrar`:

- o plano volta ao Gratuito, pela regra de sempre do rebaixamento: nada é
  apagado, e o que passa do limite só impede o próximo cadastro;
- **os médicos além do limite do Gratuito perdem o papel médico** (decisão
  1-a). Fica o que o responsável escolheu durante a degustação
  (`degustacao_medico_mantido`) ou, sem escolha, o vínculo médico mais
  antigo. Sem isso, a degustação seria a porta para cinco médicos no
  Gratuito para sempre. Quem fica sem papel nenhum tem o vínculo suspenso;
  a lista vai para `degustacao_retirados` e **volta** na conversão.

**Quem paga a IA e o SMS** durante a degustação é a instalação, então há
teto (decisão 2-a): `TETO_IA` pedidos de IA e `TETO_SMS` mensagens. O teto
de SMS vale só para a chave da instalação — a clínica que trouxe a própria
chave paga a própria conta, como em `communications/smsdev.py`. O e-mail
não tem teto: ele é o que leva a confirmação de conta e o aviso de horário.

**O fim é aplicado em três lugares**, e os três são necessários: a cada
requisição de `/app/` (`TenantMiddleware`), antes de todo trabalho de IA e
de todo SMS (o worker não passa pelo middleware), e por uma tarefa a cada
quinze minutos, que também manda os avisos. Só a tarefa deixaria uma clínica
no Completo até quinze minutos depois do prazo; só o middleware deixaria o
lembrete do worker saindo por SMS na madrugada do oitavo dia.

TISS e agenda de exames **não** vêm na degustação (decisão 3): seguem
dependendo da liberação no console, como em qualquer clínica do Completo.
"""
import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Dias de degustação. O último termina à meia-noite de Brasília.
DIAS = 7
#: O plano provado, e o plano para onde a clínica volta.
PLANO_DEGUSTADO = 'complete'
PLANO_DEPOIS = 'free'
#: Pedidos de IA (tarefas e perguntas do chat) durante a degustação.
TETO_IA = 30
#: SMS pela chave da instalação durante a degustação.
TETO_SMS = 20
#: Dias antes do fim em que sai o primeiro aviso por e-mail.
AVISO_DIAS_ANTES = 2


class CotaEsgotada(Exception):
    """O teto da degustação foi atingido. A mensagem é a que a tela mostra."""


# --------------------------------------------------------------------------
# Prazo
# --------------------------------------------------------------------------

def prazo_a_partir_de(inicio):
    """A meia-noite de Brasília que encerra o sétimo dia.

    Contado em dias de calendário de quem está na clínica, e não em 168
    horas: quem começa às 22h de segunda tem a segunda inteira como
    primeiro dia, e o prazo que a tela diz ("até domingo") é o que vale.
    """
    dia = timezone.localtime(inicio).date() + timedelta(days=DIAS)
    return timezone.make_aware(datetime.combine(dia, time.min), timezone.get_current_timezone())


def em_andamento(tenant, agora=None):
    agora = agora or timezone.now()
    return bool(
        tenant.degustacao_ate and tenant.degustacao_encerrada_em is None
        and tenant.degustacao_ate > agora
    )


def vencida(tenant, agora=None):
    agora = agora or timezone.now()
    return bool(
        tenant.degustacao_ate and tenant.degustacao_encerrada_em is None
        and tenant.degustacao_ate <= agora
    )


def dias_restantes(tenant, agora=None):
    """Quantos dias de calendário faltam, contando hoje. Zero se acabou."""
    if not em_andamento(tenant, agora):
        return 0
    hoje = timezone.localtime(agora or timezone.now()).date()
    ultimo = timezone.localtime(tenant.degustacao_ate).date() - timedelta(days=1)
    return max((ultimo - hoje).days + 1, 0)


def ultimo_dia(tenant):
    """O último dia da degustação, para escrever na tela e no e-mail."""
    if not tenant.degustacao_ate:
        return None
    return timezone.localtime(tenant.degustacao_ate).date() - timedelta(days=1)


def iniciar(tenant, agora=None):
    """Marca a clínica recém-criada como em degustação. Sem `save`."""
    agora = agora or timezone.now()
    tenant.plan = PLANO_DEGUSTADO
    tenant.degustacao_inicio = agora
    tenant.degustacao_ate = prazo_a_partir_de(agora)


# --------------------------------------------------------------------------
# Tetos de IA e SMS
# --------------------------------------------------------------------------

def uso_de_ia(tenant):
    """Tarefas de IA e perguntas do chat desde o início da degustação.

    Contado nas linhas que já existem, e não num contador à parte: o
    contador e o que de fato saiu poderiam divergir, e a tela diria uma
    coisa enquanto o provedor cobrou outra.
    """
    from ai.chat_models import ChatMessage, ChatMessageRole
    from ai.models import AIJob

    if not tenant.degustacao_inicio:
        return 0
    tarefas = AIJob.objects.filter(tenant_id=tenant.id, created_at__gte=tenant.degustacao_inicio).count()
    perguntas = ChatMessage.objects.filter(
        tenant_id=tenant.id, role=ChatMessageRole.USER, created_at__gte=tenant.degustacao_inicio,
    ).count()
    return tarefas + perguntas


def conferir_ia(tenant_id):
    """Recusa o próximo pedido de IA da clínica em degustação sem cota.

    Chamado antes de criar a tarefa e antes de gravar a pergunta do chat.
    Fora da degustação não faz nada — e o encerramento vencido acontece
    aqui também, porque o worker não passa pelo middleware.
    """
    tenant = encerrar_se_vencida(tenant_id)
    if tenant is None or not em_andamento(tenant):
        return
    if uso_de_ia(tenant) >= TETO_IA:
        raise CotaEsgotada(
            f'A degustação inclui {TETO_IA} pedidos à inteligência artificial, e todos já '
            'foram usados. Contrate o plano Completo para continuar usando a IA.'
        )


def conferir_sms(tenant_id):
    """Recusa SMS pela chave da instalação quando a cota acabou."""
    tenant = encerrar_se_vencida(tenant_id)
    if tenant is None or not em_andamento(tenant):
        return
    if tenant.degustacao_sms >= TETO_SMS:
        raise CotaEsgotada(
            f'A degustação inclui {TETO_SMS} SMS, e todos já foram usados. O aviso por '
            'e-mail continua funcionando.'
        )


def registrar_sms(tenant_id):
    """Conta um SMS enviado pela chave da instalação. Atômico, por `F()`."""
    from .models import Tenant

    Tenant.objects.filter(
        id=tenant_id, degustacao_ate__isnull=False, degustacao_encerrada_em__isnull=True,
    ).update(degustacao_sms=F('degustacao_sms') + 1)


# --------------------------------------------------------------------------
# O oitavo dia
# --------------------------------------------------------------------------

def encerrar_se_vencida(tenant_or_id):
    """Encerra a degustação vencida e devolve a clínica relida.

    Barata quando não há o que fazer — uma linha, e só os campos do prazo —,
    porque roda em toda requisição de `/app/`.
    """
    from .models import Tenant

    tenant_id = getattr(tenant_or_id, 'id', tenant_or_id)
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is not None and vencida(tenant):
        encerrar(tenant.id)
        tenant.refresh_from_db()
    return tenant


def _medico_que_fica(tenant, medicos):
    escolhido = next((m for m in medicos if m.id == tenant.degustacao_medico_mantido_id), None)
    if escolhido is not None:
        return escolhido
    return medicos[0] if medicos else None


def encerrar(tenant_id, agora=None):
    """Volta a clínica ao Gratuito. Idempotente e seguro contra corrida.

    A linha da clínica é travada: o middleware de duas abas e a tarefa
    podem chegar juntos, e só o primeiro encerra. Devolve `True` se foi
    este chamado que encerrou.
    """
    from audit.services import record_audit_event

    from .models import Membership, MembershipStatus, Role, Tenant
    from .plans import max_doctors

    agora = agora or timezone.now()
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().filter(id=tenant_id).first()
        if tenant is None or not vencida(tenant, agora):
            return False
        limite = max_doctors(PLANO_DEPOIS)
        medicos = list(
            Membership.objects.select_for_update()
            .filter(tenant_id=tenant.id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR])
            .order_by('activated_at', 'created_at')
        )
        ficam = []
        if limite is None:
            ficam = medicos
        elif medicos and limite:
            primeiro = _medico_que_fica(tenant, medicos)
            ficam = [primeiro] + [m for m in medicos if m.id != primeiro.id][:limite - 1]
        retirados = []
        for vinculo in medicos:
            if vinculo in ficam:
                continue
            vinculo.roles = [r for r in vinculo.roles if r != Role.DOCTOR]
            suspenso = not vinculo.roles
            campos = ['roles', 'row_version', 'updated_at']
            if suspenso:
                vinculo.status = MembershipStatus.SUSPENDED
                campos.append('status')
            vinculo.row_version = F('row_version') + 1
            vinculo.save(update_fields=campos)
            retirados.append({'membership': str(vinculo.id), 'suspenso': suspenso})
        anterior = tenant.plan
        tenant.plan = PLANO_DEPOIS
        tenant.degustacao_encerrada_em = agora
        tenant.degustacao_retirados = retirados
        tenant.save(update_fields=['plan', 'degustacao_encerrada_em', 'degustacao_retirados', 'updated_at'])
        record_audit_event(
            None, tenant, 'tenancy.degustacao_encerrada',
            object_type='tenant', object_id=tenant.id, outcome='success',
            integrity_metadata={
                'de': anterior, 'para': PLANO_DEPOIS,
                'medicos_retirados': len(retirados),
                'vinculos_suspensos': sum(1 for r in retirados if r['suspenso']),
            },
        )
    # Fora da transação: o e-mail não desfaz o encerramento.
    from .degustacao_avisos import avisar_fim

    avisar_fim(tenant)
    return True


def converter(tenant, por=None):
    """A clínica contratou: a degustação sai de cena e os médicos voltam.

    Chamado pela troca de plano do console. Vale durante a degustação (o
    prazo some, o plano é o que foi escolhido) e depois dela (os papéis
    retirados no oitavo dia voltam, até o limite do plano novo).
    """
    from audit.services import record_audit_event

    from .limits import PlanLimitReached, assert_can_add_doctor
    from .models import Membership, MembershipStatus, Role

    if not tenant.degustacao_ate:
        return 0
    devolvidos = 0
    with transaction.atomic():
        for item in tenant.degustacao_retirados or []:
            vinculo = Membership.objects.select_for_update().filter(
                id=item.get('membership'), tenant_id=tenant.id,
            ).first()
            if vinculo is None or vinculo.status == MembershipStatus.REVOKED:
                continue
            if item.get('suspenso') and vinculo.status != MembershipStatus.SUSPENDED:
                continue
            try:
                assert_can_add_doctor(tenant)
            except PlanLimitReached:
                break
            if Role.DOCTOR not in vinculo.roles:
                vinculo.roles = list(vinculo.roles) + [Role.DOCTOR]
            vinculo.status = MembershipStatus.ACTIVE
            vinculo.row_version = F('row_version') + 1
            vinculo.save(update_fields=['roles', 'status', 'row_version', 'updated_at'])
            devolvidos += 1
        tenant.degustacao_ate = None
        tenant.degustacao_retirados = []
        tenant.degustacao_medico_mantido = None
        tenant.save(update_fields=[
            'degustacao_ate', 'degustacao_retirados', 'degustacao_medico_mantido', 'updated_at',
        ])
        record_audit_event(
            por, tenant, 'tenancy.degustacao_convertida',
            object_type='tenant', object_id=tenant.id, outcome='success',
            integrity_metadata={'plano': tenant.plan, 'medicos_devolvidos': devolvidos},
        )
    return devolvidos


def estender(tenant, dias, por=None):
    """Mais `dias` de degustação, a partir do prazo atual. Só em andamento."""
    from audit.services import record_audit_event

    if not em_andamento(tenant):
        return False
    tenant.degustacao_ate = tenant.degustacao_ate + timedelta(days=dias)
    tenant.save(update_fields=['degustacao_ate', 'updated_at'])
    record_audit_event(
        por, tenant, 'tenancy.degustacao_estendida',
        object_type='tenant', object_id=tenant.id, outcome='success',
        integrity_metadata={'dias': dias, 'ate': tenant.degustacao_ate.isoformat()},
    )
    return True


def rodada(agora=None):
    """A tarefa periódica: encerra as vencidas e manda o aviso de véspera."""
    from .degustacao_avisos import avisar_que_acaba
    from .models import Tenant

    agora = agora or timezone.now()
    encerradas = 0
    for tenant_id in Tenant.objects.filter(
        degustacao_ate__lte=agora, degustacao_encerrada_em__isnull=True,
    ).values_list('id', flat=True):
        try:
            encerradas += int(encerrar(tenant_id, agora))
        except Exception:                                   # noqa: BLE001
            logger.exception('degustacao: falha ao encerrar (tenant=%s)', tenant_id)
    avisadas = 0
    for tenant in Tenant.objects.filter(
        degustacao_ate__gt=agora, degustacao_ate__lte=agora + timedelta(days=AVISO_DIAS_ANTES),
        degustacao_encerrada_em__isnull=True, degustacao_avisada_em__isnull=True,
    ):
        # Marcado antes de enviar, numa atualização condicional: duas
        # rodadas sobrepostas não mandam o aviso duas vezes.
        if Tenant.objects.filter(id=tenant.id, degustacao_avisada_em__isnull=True).update(
            degustacao_avisada_em=agora,
        ):
            avisar_que_acaba(tenant)
            avisadas += 1
    return {'encerradas': encerradas, 'avisadas': avisadas}
