"""Número do prontuário: sequencial por clínica.

Separado do modelo porque a atribuição precisa de trava de banco, e um
`save()` com trava dentro fica ilegível.
"""

from django.db import transaction

from .models import PatientNumberSequence

#: Seis dígitos: um consultório leva décadas para passar de um milhão de
#: pacientes, e seis dígitos ainda se ditam ao telefone sem cansar. Números
#: acima disso simplesmente ficam mais largos — a sequência não trava.
WIDTH = 6


def format_number(value):
    return f'{value:0{WIDTH}d}'


@transaction.atomic
def next_record_number(tenant_id):
    """O próximo número desta clínica, e nunca um já emitido.

    `select_for_update` serializa dois cadastros simultâneos na linha do
    contador. Sem isso, duas secretárias cadastrando ao mesmo tempo leriam
    o mesmo valor e a segunda gravação seria recusada pela restrição de
    unicidade — erro na cara de quem só estava cadastrando um paciente.

    O contador só avança. Apagar um paciente não devolve o número dele ao
    bolo: o número pode já estar impresso numa receita entregue, e dois
    prontuários com o mesmo número na história da clínica é ambiguidade
    permanente.
    """
    sequence, _ = PatientNumberSequence.objects.get_or_create(tenant_id=tenant_id)
    locked = PatientNumberSequence.objects.select_for_update().get(id=sequence.id)
    locked.last_number += 1
    locked.save(update_fields=['last_number'])
    return format_number(locked.last_number)
