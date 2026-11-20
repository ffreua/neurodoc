"""Quem abriu o prontuário de quem (adotado do ProntDoc, PD-M02, em 2026-11-20).

Até aqui a trilha registrava **escrita e emissão**: criar, salvar, finalizar,
assinar. Ler não deixava rastro — só o resumo e o download de anexo. A LGPD (art. 37) e a Res. CFM 1.821/2007 pedem
que o controlador saiba quem acessou o dado de saúde, e a pergunta aparece
na prática quando um paciente reclama — "quem na clínica viu meu
prontuário?" — e hoje não teria resposta.

**Um registro por pessoa, paciente e tela a cada trinta minutos.** O médico
abre o mesmo atendimento dezenas de vezes numa consulta (cada envio de
formulário recarrega a tela); gravar cada abertura enterraria o que importa
numa trilha imutável que não se limpa. A janela é guardada no cache (Redis):
se ele falhar, o registro é gravado mesmo assim — na dúvida, sobra linha,
não falta.

O que vai à trilha é **onde** e **quando**, nunca o que estava na tela:
nenhum texto clínico, nenhum nome (o paciente é o `object_id`).
"""

import logging

from django.core.cache import cache

from base.net import client_ip

from .services import record_audit_event

logger = logging.getLogger(__name__)

ACAO = 'clinical.prontuario_aberto'
JANELA_SEGUNDOS = 30 * 60

#: Rótulo de cada tela, para a lista de acessos da ficha.
ONDE = {
    'ficha': 'Ficha do paciente',
    'atendimento': 'Atendimento',
    'resumo': 'Resumo de um atendimento',
    'resumo_completo': 'Resumo de todos os atendimentos',
    'linha_do_tempo': 'Linha do tempo',
    'grafico': 'Gráfico de evolução',
}


def registrar_leitura(request, patient_id, onde, objeto_id=None):
    """Grava a abertura, salvo se a mesma pessoa abriu a mesma tela há pouco."""
    ctx = getattr(request, 'access_context', None)
    if ctx is None or not getattr(request.user, 'is_authenticated', False):
        return None
    # O objeto entra na chave: sem ele, o segundo atendimento do mesmo
    # paciente aberto na janela não era anotado (auditoria externa de
    # 2026-11-20).
    chave = f'prontuario-aberto:{ctx.tenant_id}:{request.user.pk}:{patient_id}:{onde}:{objeto_id or ""}'
    try:
        if not cache.add(chave, 1, JANELA_SEGUNDOS):
            return None
    except Exception:  # cache fora do ar: grava, não perde o acesso
        logger.warning('acesso: cache indisponível, registrando sem janela')
    metadados = {'onde': onde}
    if objeto_id:
        metadados['objeto'] = str(objeto_id)
    return record_audit_event(
        request.user, ctx.tenant_id, ACAO, object_type='patient', object_id=patient_id,
        outcome='success', origin_ip=client_ip(request), integrity_metadata=metadados,
    )


def acessos_do_paciente(tenant_id, patient_id, limite=50):
    """As últimas aberturas do prontuário deste paciente, para a ficha."""
    from .models import AuditEvent

    linhas = (AuditEvent.objects.filter(
        tenant_id=tenant_id, action=ACAO, object_type='patient', object_id=patient_id,
    ).select_related('actor').order_by('-created_at')[:limite])
    return [{
        'quando': ev.created_at,
        'quem': (ev.actor.get_full_name() or ev.actor.email) if ev.actor_id else '—',
        'onde': ONDE.get((ev.integrity_metadata or {}).get('onde'), 'Prontuário'),
    } for ev in linhas]
