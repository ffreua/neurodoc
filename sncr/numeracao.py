"""Blocos e números: registrar o que a Anvisa entregou, e reservar sem repetir.

Decisões I7 e I8 de `docs/sncr/DECISOES.md`. Duas regras, e as duas
existem porque o SNCR não tem consulta nem cancelamento:

- **um número, uma receita.** A reserva trava a linha
  (`select_for_update(skip_locked)`) e a restrição única do banco segura
  o resto — duas abas, duas réplicas do `app` e dois médicos ao mesmo
  tempo nunca levam o mesmo número;
- **nada é inventado.** Se início e fim do bloco não formam uma faixa
  que se saiba enumerar, o bloco fica registrado como **não utilizável**,
  e a receita não sai com número adivinhado.

Nenhuma chamada externa acontece aqui: a reserva é só banco, e o lock
nunca fica aberto durante uma requisição à Anvisa.
"""

import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import BlocoNumeracao, EstadoNumero, NumeroSncr

_FAIXA = re.compile(r'^(?P<prefixo>.*?)(?P<numero>\d+)$')


class SemNumeroLivre(Exception):
    pass


def enumerar(inicio, fim, quantidade=None):
    """Os números de `inicio` a `fim`, como texto, ou `None` se não der.

    Aceita só a forma "mesmo prefixo + dígitos de mesmo comprimento"
    (inclusive prefixo vazio). Qualquer outra coisa — prefixos diferentes,
    comprimentos diferentes, fim antes do início, quantidade que não bate
    — devolve `None` e o bloco fica não utilizável.
    """
    a, b = _FAIXA.match(inicio or ''), _FAIXA.match(fim or '')
    if not a or not b or a['prefixo'] != b['prefixo'] or len(a['numero']) != len(b['numero']):
        return None
    primeiro, ultimo, largura = int(a['numero']), int(b['numero']), len(a['numero'])
    total = ultimo - primeiro + 1
    if total < 1 or total > 10_000 or (quantidade is not None and quantidade != total):
        return None
    return [f'{a["prefixo"]}{n:0{largura}d}' for n in range(primeiro, ultimo + 1)]


@transaction.atomic
def registrar_bloco(pedido, resposta):
    """Grava o bloco recebido e um registro por número. Devolve o bloco."""
    bloco = BlocoNumeracao.objects.create(
        pedido=pedido, medico=pedido.medico, tipo=pedido.tipo, ambiente=pedido.ambiente,
        inicio=resposta['inicio'], fim=resposta['fim'], quantidade=resposta.get('quantidade'),
    )
    numeros = enumerar(bloco.inicio, bloco.fim, bloco.quantidade)
    if numeros is None:
        bloco.utilizavel = False
        bloco.motivo_bloqueio = 'Início e fim do bloco não formam uma faixa reconhecida; nenhum número foi gerado.'
        bloco.save(update_fields=['utilizavel', 'motivo_bloqueio'])
        return bloco
    try:
        with transaction.atomic():
            NumeroSncr.objects.bulk_create([
                NumeroSncr(
                    bloco=bloco, medico=pedido.medico, tipo=pedido.tipo, ambiente=pedido.ambiente,
                    numero=numero, ordem=ordem,
                )
                for ordem, numero in enumerate(numeros)
            ])
    except IntegrityError:
        # Um número deste bloco já existe noutro: a Anvisa entregou faixa
        # sobreposta, ou o mesmo bloco chegou duas vezes. Usar seria
        # arriscar o mesmo número em duas receitas — condição de parada.
        bloco.utilizavel = False
        bloco.motivo_bloqueio = 'O bloco repete números já registrados; ele não será usado até conferência.'
        bloco.save(update_fields=['utilizavel', 'motivo_bloqueio'])
    return bloco


def saldo(medico, tipo, ambiente):
    return NumeroSncr.objects.filter(
        medico=medico, tipo=tipo, ambiente=ambiente, estado=EstadoNumero.LIVRE, bloco__utilizavel=True,
    ).count()


@transaction.atomic
def reservar(medico, tipo, ambiente, documento, tenant_id):
    """O próximo número livre do médico para este documento.

    Idempotente por documento: pedir de novo devolve o mesmo número, e não
    um segundo — a receita reaberta não queima a faixa.
    """
    ja = NumeroSncr.objects.select_for_update().filter(
        documento=documento, tipo=tipo, ambiente=ambiente, estado__in=[EstadoNumero.RESERVADO, EstadoNumero.CONSUMIDO],
    ).first()
    if ja is not None:
        return ja
    # `of=('self',)`: trava só a linha do número. Sem isso o `FOR UPDATE`
    # trava também a do **bloco**, que entra na consulta pelo filtro — e,
    # como todos os números são do mesmo bloco, a segunda reserva
    # simultânea pulava todos eles e dizia "não há número livre" com 998
    # sobrando. Foi o que o roteiro pegou na primeira rodada.
    numero = (
        NumeroSncr.objects.select_for_update(skip_locked=True, of=('self',))
        .filter(medico=medico, tipo=tipo, ambiente=ambiente, estado=EstadoNumero.LIVRE, bloco__utilizavel=True)
        .order_by('bloco__created_at', 'ordem')
        .first()
    )
    if numero is None:
        raise SemNumeroLivre('Não há número SNCR livre deste tipo. Peça um bloco novo.')
    numero.estado = EstadoNumero.RESERVADO
    numero.documento = documento
    numero.tenant_id = tenant_id
    numero.reservado_em = timezone.now()
    numero.save(update_fields=['estado', 'documento', 'tenant', 'reservado_em', 'updated_at'])
    return numero


@transaction.atomic
def consumir(numero):
    """O número foi impresso numa receita emitida e assinada. Não volta."""
    travado = NumeroSncr.objects.select_for_update().get(pk=numero.pk)
    if travado.estado != EstadoNumero.RESERVADO:
        raise ValueError(f'Número {travado.numero} não está reservado ({travado.estado}).')
    travado.estado = EstadoNumero.CONSUMIDO
    travado.consumido_em = timezone.now()
    travado.save(update_fields=['estado', 'consumido_em', 'updated_at'])
    return travado


@transaction.atomic
def marcar_perdido(numero, motivo):
    """O número não será usado (rascunho descartado depois de impresso, erro).

    Não volta a livre: ele pode ter aparecido num PDF que saiu da tela, e
    a Anvisa não cancela número (FAQ P35–36).
    """
    travado = NumeroSncr.objects.select_for_update().get(pk=numero.pk)
    if travado.estado == EstadoNumero.CONSUMIDO:
        raise ValueError(f'Número {travado.numero} já foi usado numa receita emitida.')
    travado.estado = EstadoNumero.PERDIDO
    travado.motivo_perda = motivo[:300]
    travado.save(update_fields=['estado', 'motivo_perda', 'updated_at'])
    return travado
