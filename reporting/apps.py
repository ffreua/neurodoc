from django.apps import AppConfig


class ReportingConfig(AppConfig):
    name = 'reporting'

    def ready(self):
        from . import patients
        from .services import register_report

        register_report(
            'patients_seen_detail', patients.patients_seen_detail_rows,
            ['patient_id', 'full_name', 'first_encounter_at'],
        )
