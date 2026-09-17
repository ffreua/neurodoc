from django.db.models import F
from django.http import Http404

from tenancy.selectors import scope_to_tenant

from .models import Encounter


#: Como a grade de atendimentos pode ser ordenada.
#:
#: Abertura e fechamento respondem a perguntas diferentes: "quando ele veio?"
#: e "quando este registro foi fechado?". Com atendimento que se abre num dia
#: e se finaliza em outro, as duas ordens deixam de coincidir — e quem procura
#: o que ficou pendente ordena por fechamento, onde os nulos vêm primeiro.
ORDENS_DA_GRADE = {
    'abertura': 'occurred_at',
    'fechamento': 'finalized_at',
}
ORDEM_PADRAO = 'abertura'


def patient_timeline(context, patient, ordenar=ORDEM_PADRAO, decrescente=False):
    """Atendimentos deste paciente, no inquilino do contexto.

    Clinical access-grant scoping (PatientAccessGrant) is not modeled yet;
    tenant scoping plus the caller's own view-level permission check are the
    isolation boundary until that model exists.

    `ordenar` vem da tela e é validado contra `ORDENS_DA_GRADE` — nunca
    interpolado na consulta. Um `order_by` montado com o que chega na URL
    aceita `patient__cpf` e vira um oráculo de ordenação sobre colunas que a
    tela não mostra.
    """
    campo = ORDENS_DA_GRADE.get(ordenar, ORDENS_DA_GRADE[ORDEM_PADRAO])
    consulta = (
        scope_to_tenant(Encounter.objects.all(), context)
        .filter(patient=patient)
        .select_related('physician_membership__user')
    )
    expressao = F(campo).desc(nulls_last=True) if decrescente else F(campo).asc(nulls_first=True)
    # Desempate por abertura: dois atendimentos ainda não finalizados têm o
    # mesmo `finalized_at` (nulo), e sem o segundo critério a ordem entre eles
    # muda a cada consulta — a mesma página recarregada troca duas linhas de
    # lugar.
    return consulta.order_by(expressao, '-occurred_at')


def get_encounter_or_404(context, encounter_id):
    encounter = scope_to_tenant(Encounter.objects.all(), context).filter(id=encounter_id).first()
    if encounter is None:
        raise Http404
    return encounter
