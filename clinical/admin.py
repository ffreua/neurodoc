"""Prontuário no admin: **ver, nunca escrever.**

O Django admin não conhece a regra deste domínio. Ele oferece formulário
editável e botão de apagar para qualquer modelo registrado, e era por aí
que passava a única porta do sistema capaz de reescrever um atendimento
finalizado sem adendo, sem recalcular `content_hash` e sem deixar rastro
no lugar certo — bastava ter acesso ao `/admin/`.

Somente leitura para o app inteiro, e não só para o que está finalizado:
o rascunho tem a tela de atendimento, o finalizado tem o adendo
(`clinical/finalization.py`), e nenhum dos dois precisa do admin para ser
corrigido. O admin aqui serve para olhar quando alguém pergunta "o que
está gravado nesta linha?".

`ClinicalAmendment` entra na mesma regra pelo motivo mais forte de todos:
é o registro que existe justamente para corrigir sem apagar. Um adendo
editável não corrige coisa nenhuma.
"""

from django.contrib import admin

from .models import (
    CarryForwardItem, ClinicalAmendment, Encounter, EncounterDiagnosis, ExaminationFinding,
)


class SomenteLeituraAdmin(admin.ModelAdmin):
    """Registro visível e imutável pelo admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Encounter)
class EncounterAdmin(SomenteLeituraAdmin):
    list_display = ['patient', 'physician_membership', 'occurred_at', 'status']
    list_filter = ['tenant', 'status']
    search_fields = ['patient__full_name']


@admin.register(ExaminationFinding)
class ExaminationFindingAdmin(SomenteLeituraAdmin):
    list_display = ['encounter', 'domain', 'item_code', 'side', 'state']
    list_filter = ['domain', 'state']


@admin.register(EncounterDiagnosis)
class EncounterDiagnosisAdmin(SomenteLeituraAdmin):
    list_display = ['encounter', 'code_snapshot', 'certainty', 'rank']


@admin.register(CarryForwardItem)
class CarryForwardItemAdmin(SomenteLeituraAdmin):
    list_display = ['target_encounter', 'source_encounter', 'field_path', 'review_action']
    list_filter = ['review_action']


@admin.register(ClinicalAmendment)
class ClinicalAmendmentAdmin(SomenteLeituraAdmin):
    list_display = ['encounter', 'author', 'authored_at']
