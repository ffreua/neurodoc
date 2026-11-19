"""Ordem em que o prontuário mostra medicações e resultados de exame.

Mora num lugar só porque as mesmas listas são lidas pela aba do
atendimento, pelos resumos, pela gaveta da consulta anterior, pelo acervo e
pelas ferramentas da IA. Ordem escrita à mão em cada uma já divergiu: o
modelo dizia `-performed_on` e a IA também, mas no PostgreSQL a ordem
decrescente põe o **nulo primeiro**, e um exame sem data subia acima do
mais recente -- na tela e nas quinze vagas que a IA lê.
"""

from django.db.models import Case, F, IntegerField, Value, When

from .models import MedicationStatus

# Exame: o mais recente em cima. Sem data vai para o fim, porque não dá
# para afirmar que é recente. No mesmo dia, o registrado por último em cima.
ORDEM_DOS_EXAMES = (
    F('performed_on').desc(nulls_last=True),
    F('created_at').desc(),
    'name',
)

# Medicação: as em uso juntas, depois as suspensas, depois as concluídas;
# dentro de cada grupo, por nome, como já era. Situação desconhecida (não
# deveria existir) vai para o fim em vez de sumir ou quebrar a tela.
_PESO_DA_SITUACAO = {
    MedicationStatus.IN_USE: 0,
    MedicationStatus.SUSPENDED: 1,
    MedicationStatus.FINISHED: 2,
}


def _situacao_em_ordem():
    return Case(
        *[When(status=s, then=Value(peso)) for s, peso in _PESO_DA_SITUACAO.items()],
        default=Value(len(_PESO_DA_SITUACAO)),
        output_field=IntegerField(),
    )


def exames_em_ordem(queryset):
    return queryset.order_by(*ORDEM_DOS_EXAMES)


def medicacoes_em_ordem(queryset):
    return queryset.order_by(_situacao_em_ordem(), 'name')


def chave_da_medicacao(medicacao):
    """A mesma ordem para listas já carregadas (prefetch), sem nova consulta."""
    return (_PESO_DA_SITUACAO.get(medicacao.status, len(_PESO_DA_SITUACAO)), medicacao.name)


def chave_do_exame(exame):
    """A mesma ordem de `ORDEM_DOS_EXAMES` para listas já carregadas."""
    sem_data = exame.performed_on is None
    dia = exame.performed_on.toordinal() if exame.performed_on else 0
    criado = exame.created_at.timestamp() if exame.created_at else 0
    return (sem_data, -dia, -criado, exame.name)
