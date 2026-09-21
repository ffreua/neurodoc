from django.apps import AppConfig


class ReportingConfig(AppConfig):
    name = 'reporting'

    def ready(self):
        from tenancy.permissions import Capability

        from . import acervo, patients
        from .models import ReportExportKind
        from .services import register_report

        register_report(
            'patients_seen_detail', patients.patients_seen_detail_rows,
            ['patient_id', 'full_name', 'first_encounter_at'],
            count_fn=patients.patients_seen_detail_count,
            capability=Capability.MANAGERIAL_DASHBOARD,
            kinds=[ReportExportKind.CSV],
        )

        # ---------------------------------------------- acervo da clinica
        #
        # A exportacao que a clausula 13.1 do contrato promete. Duas
        # capacidades diferentes, e a diferenca nao e detalhe:
        #
        # `MANAGE_ORGANIZATION` so o dono tem, e e ela que corresponde a
        # "CONTRATANTE" do contrato -- quem tem direito de levar o acervo
        # embora e quem contratou, nao toda secretaria com acesso ao
        # cadastro. Sem ela, `PATIENT_ADMIN` bastaria, e ai qualquer
        # vinculo de balcao baixaria a base inteira de pacientes.
        #
        # O acervo clinico exige, **alem** dela, `READ_CLINICAL`. Um dono
        # que nao e medico nao abre um prontuario na tela (ver
        # `capabilities_for`), e nao pode baixar todos num arquivo: seria
        # atravessar por exportacao a linha que o produto inteiro
        # sustenta. Dono que tambem e medico soma as duas colunas e
        # exporta -- que e o caso do consultorio de um medico so.
        register_report(
            'acervo_pacientes', acervo.pacientes_rows, acervo.PACIENTES_COLUNAS,
            markdown_fn=acervo.pacientes_markdown,
            capability=Capability.MANAGE_ORGANIZATION,
            kinds=[ReportExportKind.MD, ReportExportKind.JSON],
        )
        register_report(
            'acervo_atendimentos', acervo.atendimentos_rows,
            acervo.ATENDIMENTOS_COLUNAS,
            markdown_fn=acervo.atendimentos_markdown,
            capability=(Capability.MANAGE_ORGANIZATION, Capability.READ_CLINICAL),
            kinds=[ReportExportKind.MD, ReportExportKind.JSON],
        )
