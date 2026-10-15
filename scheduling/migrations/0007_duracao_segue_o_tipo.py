from datetime import timedelta

from django.db import migrations
from django.utils import timezone

#: Copiado de `scheduling.models.DEFAULT_TYPE_MINUTES` na data desta
#: migração: migração não importa o modelo vivo, que pode mudar depois.
PADRAO = {
    'first_visit': 80, 'follow_up': 80, 'return_visit': 40, 'procedure': 40, 'other': 40,
}


def encurta(apps, schema_editor):
    """A consulta futura que ficou mais longa que o seu tipo volta à duração dele.

    Relatado pelo Dr. Fernando em 2026-10-15: um retorno das 17h do dia 22
    ocupava até 18h20 (80 min), e o horário das 17h40 não existia para
    marcar nem para incluir. Até a 1.13, trocar o tipo não mexia no fim, e
    a remarcação copiava a duração que a consulta tinha; as consultas
    gravadas assim continuaram longas depois que as duas portas foram
    corrigidas.

    **Só encurta, e só o que ainda vai acontecer** (agendado ou
    confirmado, fora de encaixe). Encurtar sempre cabe -- libera tempo, não
    toma de ninguém --, e o passado fica como aconteceu. Esticar poderia
    invadir o paciente seguinte, e não é o caso relatado. O intervalo
    pós-consulta que a reserva tinha é preservado, medido do novo fim.
    """
    from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

    Appointment = apps.get_model('scheduling', 'Appointment')
    Duracao = apps.get_model('scheduling', 'AppointmentTypeDuration')
    configurado = {
        (d.physician_membership_id, d.appointment_type): d.minutes for d in Duracao.objects.all()
    }
    encurtadas = 0
    for a in Appointment.objects.filter(
        status__in=['scheduled', 'confirmed'], is_overbook=False, starts_at__gte=timezone.now(),
    ):
        minutos = configurado.get((a.physician_membership_id, a.type), PADRAO.get(a.type))
        if not minutos:
            continue
        novo_fim = a.starts_at + timedelta(minutes=minutos)
        if novo_fim >= a.ends_at:
            continue
        upper = getattr(a.occupied_range, 'upper', None)
        folga = (upper - a.ends_at) if upper and upper > a.ends_at else timedelta(0)
        a.ends_at = novo_fim
        a.occupied_range = DateTimeTZRange(a.starts_at, novo_fim + folga, bounds='[)')
        a.row_version += 1
        a.save(update_fields=['ends_at', 'occupied_range', 'row_version'])
        encurtadas += 1
    if encurtadas:
        print(f'\n  {encurtadas} consulta(s) futura(s) encurtada(s) para a duração do tipo.')


class Migration(migrations.Migration):
    """Só dados, nenhuma coluna. Sem volta: a duração antiga era o defeito,
    e a imagem anterior lê a nova sem estranhar."""

    dependencies = [
        ('scheduling', '0006_horario_excluido'),
    ]

    operations = [
        migrations.RunPython(encurta, migrations.RunPython.noop),
    ]
