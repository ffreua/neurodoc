"""Comunicados da instalação: o console escreve, o sino e o celular entregam.

**O mesmo arquivo nos dois produtos** (NeuroDoc e ProntDoc). Pedido do
titular em 2026-11-27: do console do superadministrador, mandar avisos do
sistema **e propaganda**, sem opção de recusa. Decisões em
`docs/homologation/pwa.md` (Comunicados).

Duas categorias, e a diferença entre elas é o contrato:

- **aviso do sistema** (manutenção, versão nova, mudança de funcionamento)
  está coberto pela cláusula 18.1 — comunicações "ao centro de notificações
  do aplicativo" — e vale já;
- **propaganda** não está no contrato: o Aviso de Privacidade não lista
  marketing entre as finalidades e diz que uso para publicidade "deverá ser
  informado em versão complementar antes de sua ativação". Por isso ela só
  sai para a clínica cujo **último aceite** é de uma redação a partir de
  `tenancy.plans.CONTRATO_COM_PROPAGANDA` — a minuta está com a Dra. Karina
  (`docs/governance/comunicados-minuta.md`). Até lá, o console mostra a
  opção travada e diz por quê; publicada a redação, cada clínica passa a
  receber quando aceitar a versão nova, sem outro deploy.

O que o comunicado **não** é: canal de dado de paciente. O console não abre
prontuário, e o texto é da casa.
"""

import logging

from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

TITULO_MAX = 60
TEXTO_MAX = 1000
#: Quanto do texto vai na notificação do celular. A tela bloqueada mostra
#: duas ou três linhas; o resto se lê ao tocar.
RESUMO_NO_CELULAR = 160


class ComunicadoRecusado(ValueError):
    """O que o console mandou não pode virar comunicado."""


def propaganda_liberada():
    """A redação vigente já prevê propaganda? (Sem ela, nenhuma clínica recebe.)"""
    from tenancy import contract
    from tenancy.plans import CONTRATO_COM_PROPAGANDA, _versao

    return _versao(contract.VERSAO) >= _versao(CONTRATO_COM_PROPAGANDA)


def _clinicas_com_propaganda(tenant_ids):
    """Das clínicas dadas, as que **aceitaram** uma redação com propaganda.

    O último aceite de cada uma, e não o texto vigente: quem aceitou a
    versão anterior continua nela até renovar, como no parcelamento.
    """
    from tenancy.models import ContractAcceptance
    from tenancy.plans import CONTRATO_COM_PROPAGANDA, _versao

    ultimo = {}
    for tenant_id, versao in (ContractAcceptance.objects.filter(tenant_id__in=tenant_ids)
                              .order_by('tenant_id', 'created_at')
                              .values_list('tenant_id', 'version')):
        ultimo[tenant_id] = versao
    minimo = _versao(CONTRATO_COM_PROPAGANDA)
    return {t for t, v in ultimo.items() if _versao(v) >= minimo}


def destinatarios(categoria, publico, filtro=''):
    """Os pares `(tenant_id, user_id)` que recebem, já com as regras aplicadas.

    Vínculo ativo, em clínica que não foi encerrada. Aviso do sistema chega
    também à clínica suspensa (ela segue lendo o sistema, e a manutenção é
    dela também); propaganda só à ativa e só com o aceite que a prevê.
    """
    from notifications.models import Comunicado
    from tenancy.models import Membership, MembershipStatus, TenantStatus

    situacoes = [TenantStatus.ACTIVE]
    if categoria == Comunicado.Categoria.AVISO:
        situacoes.append(TenantStatus.SUSPENDED)
    consulta = Membership.objects.filter(
        status=MembershipStatus.ACTIVE, tenant__status__in=situacoes,
        user__is_active=True,
    )
    if publico == Comunicado.Publico.PLANO:
        consulta = consulta.filter(tenant__plan=filtro)
    elif publico == Comunicado.Publico.CLINICA:
        consulta = consulta.filter(tenant_id=filtro)
    elif publico == Comunicado.Publico.PAPEL:
        consulta = consulta.filter(roles__contains=[filtro])
    pares = list(consulta.values_list('tenant_id', 'user_id').distinct())
    if categoria == Comunicado.Categoria.PROPAGANDA:
        if not propaganda_liberada():
            return []
        liberadas = _clinicas_com_propaganda({t for t, _ in pares})
        pares = [(t, u) for t, u in pares if t in liberadas]
    return pares


def previa(categoria, publico, filtro=''):
    """Quantos recebem — o que a tela mostra antes de pedir a confirmação."""
    from notifications.models import PushSubscription

    pares = destinatarios(categoria, publico, filtro)
    pessoas = {u for _, u in pares}
    return {
        'clinicas': len({t for t, _ in pares}),
        'pessoas': len(pessoas),
        'aparelhos': PushSubscription.objects.filter(user_id__in=pessoas).count(),
    }


def validar(dados):
    """Confere o formulário do console e devolve os campos limpos."""
    from notifications.models import Comunicado
    from tenancy.models import Role, Tenant
    from tenancy.plans import PLANS

    categoria = (dados.get('categoria') or '').strip()
    publico = (dados.get('publico') or '').strip()
    titulo = (dados.get('titulo') or '').strip()
    texto = (dados.get('texto') or '').strip().replace('\r\n', '\n')
    link = (dados.get('link') or '').strip()
    filtro = ''
    if categoria not in Comunicado.Categoria.values:
        raise ComunicadoRecusado('Escolha se é aviso do sistema ou propaganda.')
    if categoria == Comunicado.Categoria.PROPAGANDA and not propaganda_liberada():
        raise ComunicadoRecusado(
            'A propaganda ainda não está prevista no contrato vigente. Ela libera '
            'quando a nova redação for publicada.')
    if not titulo or len(titulo) > TITULO_MAX:
        raise ComunicadoRecusado(f'O título é obrigatório, até {TITULO_MAX} caracteres.')
    if not texto or len(texto) > TEXTO_MAX:
        raise ComunicadoRecusado(f'O texto é obrigatório, até {TEXTO_MAX} caracteres.')
    if link and (not link.startswith('/') or link.startswith('//') or '\\' in link
                 or any(c.isspace() for c in link) or len(link) > 200):
        raise ComunicadoRecusado(
            'O link tem de ser um endereço deste sistema, começando por "/" (por '
            'exemplo /ajuda/instalar-app/).')
    if publico == Comunicado.Publico.PLANO:
        filtro = (dados.get('plano') or '').strip()
        if filtro not in PLANS:
            raise ComunicadoRecusado('Escolha o plano.')
    elif publico == Comunicado.Publico.CLINICA:
        filtro = (dados.get('clinica') or '').strip()
        try:
            existe = Tenant.objects.filter(pk=filtro).exists()
        except Exception:  # id que não é UUID: o banco recusa a comparação
            existe = False
        if not existe:
            raise ComunicadoRecusado('Escolha a clínica.')
    elif publico == Comunicado.Publico.PAPEL:
        filtro = (dados.get('papel') or '').strip()
        if filtro not in Role.values:
            raise ComunicadoRecusado('Escolha o papel.')
    elif publico != Comunicado.Publico.TODOS:
        raise ComunicadoRecusado('Escolha para quem vai.')
    return {'categoria': categoria, 'publico': publico, 'filtro': filtro,
            'titulo': titulo, 'texto': texto, 'link': link}


def criar(user, dados):
    """Grava o comunicado e o põe na fila do worker. Devolve o comunicado."""
    from audit.services import record_audit_event
    from notifications.models import Comunicado

    from .tasks import enviar_comunicado

    campos = validar(dados)
    with transaction.atomic():
        comunicado = Comunicado.objects.create(criado_por=user, **campos)
        record_audit_event(
            user, None, 'superadmin.comunicado_criado',
            object_type='comunicado', object_id=comunicado.id,
            integrity_metadata={'categoria': campos['categoria'], 'publico': campos['publico']},
        )
        transaction.on_commit(lambda: enviar_comunicado.delay(str(comunicado.id)))
    return comunicado


def enviar(comunicado_id):
    """Entrega o comunicado: uma linha no sino por vínculo, e o celular. No worker.

    Os destinatários são calculados **agora**, e não na criação: entre a
    fila e o envio uma clínica pode ter sido encerrada ou um vínculo
    revogado. A passagem de "na fila" para "enviando" é um `UPDATE`
    condicional, para a tarefa repetida pelo broker não entregar duas vezes.
    """
    from notifications import push
    from notifications.models import Comunicado, Notification

    if not Comunicado.objects.filter(pk=comunicado_id, situacao=Comunicado.Situacao.NA_FILA).update(
            situacao=Comunicado.Situacao.ENVIANDO):
        return None
    comunicado = Comunicado.objects.get(pk=comunicado_id)
    try:
        pares = destinatarios(comunicado.categoria, comunicado.publico, comunicado.filtro)
        linhas = [
            Notification(
                tenant_id=t, user_id=u, kind='comunicado', target_type='comunicado',
                target_id=comunicado.id, sanitized_title=comunicado.titulo,
                context={'assunto': comunicado.get_categoria_display()},
            )
            for t, u in pares
        ]
        Notification.objects.bulk_create(linhas, batch_size=1000)
        pessoas = sorted({str(u) for _, u in pares})
        resultado = push.enviar(
            pessoas, 'comunicado', reverse('notifications:comunicado', args=[comunicado.id]),
            f'comunicado-{comunicado.id}', 3 * 86400,
            titulo=comunicado.titulo, corpo=_resumo(comunicado.texto),
        ) if pessoas else {'enviados': 0, 'falhas': 0}
    except Exception:
        Comunicado.objects.filter(pk=comunicado.pk).update(situacao=Comunicado.Situacao.FALHOU)
        logger.exception('comunicado %s: falha no envio', comunicado.pk)
        raise
    Comunicado.objects.filter(pk=comunicado.pk).update(
        situacao=Comunicado.Situacao.ENVIADO, enviado_em=timezone.now(),
        pessoas=len(pessoas),
        aparelhos_entregues=F('aparelhos_entregues') + resultado.get('enviados', 0),
        aparelhos_falhas=F('aparelhos_falhas') + resultado.get('falhas', 0),
    )
    return resultado


def _resumo(texto):
    linha = ' '.join(texto.split())
    if len(linha) <= RESUMO_NO_CELULAR:
        return linha
    return linha[:RESUMO_NO_CELULAR - 1].rsplit(' ', 1)[0] + '…'
