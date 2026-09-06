from clinical.models import Encounter

from .receivables import create_receivable_for_encounter


def handle_encounter_finalized(event):
    encounter = Encounter.objects.filter(id=event.payload_minimal['encounter_id']).first()
    if encounter is None:
        return
    create_receivable_for_encounter(encounter, actor_id=encounter.finalized_by.user_id if encounter.finalized_by_id else None)
