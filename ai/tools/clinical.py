from clinical.models import (
    DiagnosisCertainty, Encounter, EncounterDiagnosis, ExaminationFinding, ExamResult,
    Medication,
)

MAX_ENCOUNTERS = 20
MAX_FINDINGS = 100
MAX_DIAGNOSES = 50
MAX_MEDICATIONS = 60
MAX_EXAM_RESULTS = 40
MAX_LAB_VALUES = 120


class ToolScopeError(Exception):
    pass


def _encounter_in_scope(authorization, encounter_id):
    """Reautoriza o atendimento a cada chamada.

    A autorização é reconferida em toda leitura, e não uma vez no início:
    um `encounter_id` que não é do paciente em escopo — venha de erro de
    programação ou de um prompt tentando puxar outro prontuário — não passa
    daqui.
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    encounter = Encounter.objects.filter(
        tenant_id=authorization.tenant_id, id=encounter_id, patient_id=authorization.patient_id,
    ).first()
    if encounter is None:
        raise ToolScopeError('Encounter is not in scope for this authorization')
    return encounter


def get_patient_timeline(authorization, limit=MAX_ENCOUNTERS):
    """Revalidates scope on every call -- an authorization without a
    patient in scope can never enumerate any patient's encounters, no
    matter what the caller (or a compromised prompt) asks for.

    Os campos narrativos entram pelo mesmo motivo que entram no
    `Encounter.compute_content_hash`: são parte do registro clínico. Em um
    atendimento de texto livre, `free_text` e `impressions` são a consulta;
    no estruturado, `neurological_exam_text` complementa os achados da
    árvore. Omiti-los entregaria ao chat uma linha do tempo incompleta.
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    limit = min(int(limit), MAX_ENCOUNTERS)
    encounters = Encounter.objects.filter(
        tenant_id=authorization.tenant_id, patient_id=authorization.patient_id,
    ).order_by('-occurred_at')[:limit]
    return [
        {
            'encounter_id': str(e.id), 'occurred_at': e.occurred_at.isoformat(), 'status': e.status,
            'kind': e.kind,
            'chief_complaint': e.chief_complaint, 'hpi': e.hpi, 'plan_text': e.plan_text,
            'neurological_exam_text': e.neurological_exam_text,
            'free_text': e.free_text, 'impressions': e.impressions,
        }
        for e in encounters
    ]


def get_examination_findings(authorization, encounter_id, limit=MAX_FINDINGS):
    encounter = _encounter_in_scope(authorization, encounter_id)
    limit = min(int(limit), MAX_FINDINGS)
    findings = ExaminationFinding.objects.filter(
        tenant_id=authorization.tenant_id, encounter=encounter,
    ).select_related('template_node').order_by('domain', 'item_code')[:limit]
    # O rótulo legível vai junto: mandar `somatico.motricidade.forca.
    # flexao_cotovelo` para o modelo é pedir que ele adivinhe o que foi
    # examinado, e é justo o tipo de adivinhação que não se quer aqui.
    from clinical.examination import group_findings_by_domain

    rows = []
    for group in group_findings_by_domain(list(findings)):
        for f in group['findings']:
            rows.append({
                'domain': group['label'], 'item': f.label,
                'path': getattr(f, 'breadcrumb', '') or f.item_code,
                'side': f.get_side_display(), 'state': f.get_state_display(),
                'value': f.qualifier, 'note': f.note,
            })
    return rows


def get_medications(authorization, encounter_id, limit=MAX_MEDICATIONS):
    """Medicações em uso registradas neste atendimento."""
    encounter = _encounter_in_scope(authorization, encounter_id)
    limit = min(int(limit), MAX_MEDICATIONS)
    medications = Medication.objects.filter(
        tenant_id=authorization.tenant_id, encounter=encounter,
    ).order_by('name')[:limit]
    return [
        {
            'name': m.name, 'dose': m.dose, 'route': m.get_route_display(),
            'frequency': m.frequency, 'since': m.started_on.isoformat() if m.started_on else '',
            'indication': m.indication, 'status': m.get_status_display(), 'note': m.notes,
        }
        for m in medications
    ]


def get_exam_results(authorization, limit=MAX_EXAM_RESULTS):
    """Resultados de exame do paciente, com os analitos fora da referência.

    Traz os do paciente inteiro, não só do atendimento aberto: um TSH de
    três meses atrás continua sendo o TSH do caso, e o raciocínio
    diagnóstico depende justamente dessa série.

    Dos analitos, sobem os que estão **fora** da faixa do próprio laudo e
    uma contagem dos que estão dentro. Enviar duzentas linhas normais de um
    hemograma completo enche o contexto e afoga o que importa.
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    limit = min(int(limit), MAX_EXAM_RESULTS)
    results = ExamResult.objects.filter(
        tenant_id=authorization.tenant_id, patient_id=authorization.patient_id,
    ).prefetch_related('lab_values').order_by('-performed_on')[:limit]

    rows = []
    for result in results:
        values = list(result.lab_values.all())[:MAX_LAB_VALUES]
        abnormal = [v for v in values if v.flag in ('low', 'high', 'abnormal')]
        rows.append({
            'exam': result.name, 'category': result.get_category_display(),
            'performed_on': result.performed_on.isoformat() if result.performed_on else '',
            'service': result.service_name,
            'report': result.report_text, 'conclusion': result.conclusion,
            'out_of_reference': [
                {
                    'analyte': v.analyte, 'value': f'{v.value_text} {v.unit}'.strip(),
                    'reference': v.reference_display, 'flag': v.get_flag_display(),
                }
                for v in abnormal
            ],
            'within_reference_count': len(values) - len(abnormal),
        })
    return rows


def get_diagnoses(authorization, encounter_id, limit=MAX_DIAGNOSES):
    encounter = _encounter_in_scope(authorization, encounter_id)
    limit = min(int(limit), MAX_DIAGNOSES)
    diagnoses = EncounterDiagnosis.objects.filter(
        tenant_id=authorization.tenant_id, encounter=encounter,
    ).order_by('rank')[:limit]
    return [
        {'code': d.code_snapshot, 'description': d.description_snapshot, 'certainty': d.certainty}
        for d in diagnoses
    ]


def get_patient_diagnoses(authorization, limit=MAX_DIAGNOSES):
    """Diagnósticos do paciente inteiro, com a última palavra sobre cada código.

    Duas diferenças em relação a `get_diagnoses`, que lê um atendimento só,
    e as duas existem por causa do relatório que o paciente leva na mão:

    - **vale a última palavra.** Um código registrado como suspeita em
      março e refutado em agosto não é diagnóstico do paciente: é hipótese
      descartada. Listá-lo num relatório afirmaria doença que o próprio
      médico já excluiu. A regra é a mesma de `clinical/por_cid.py`, e pelo
      mesmo motivo — lá ela evita que a busca devolva quem não tem a
      doença, aqui evita que o papel diga que tem.
    - **a data que importa é a primeira.** "Desde quando" é a pergunta que
      o relatório precisa responder, e a resposta está no atendimento mais
      antigo em que o código aparece. A mais recente diz quando se falou
      dele pela última vez, que é outra coisa.

    O refutado não some: volta em `refutados`, porque o que foi investigado
    e descartado também é informação clínica — e é o médico, não esta
    função, quem decide se cabe no relatório.
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    limit = min(int(limit), MAX_DIAGNOSES)
    linhas = (
        EncounterDiagnosis.objects
        .filter(tenant_id=authorization.tenant_id, encounter__patient_id=authorization.patient_id)
        .order_by('encounter__occurred_at')
        .values('code_snapshot', 'description_snapshot', 'certainty', 'encounter__occurred_at')
    )
    por_codigo = {}
    for linha in linhas:
        chave = linha['code_snapshot'] or linha['description_snapshot']
        quando = linha['encounter__occurred_at']
        registro = por_codigo.get(chave)
        if registro is None:
            por_codigo[chave] = {
                'codigo': linha['code_snapshot'], 'descricao': linha['description_snapshot'],
                'primeiro_registro': quando, 'ultimo_registro': quando,
                'certeza': linha['certainty'],
            }
            continue
        # A ordenação é crescente, então o que chega por último é o mais
        # recente -- e é ele quem define a certeza vigente.
        registro['ultimo_registro'] = quando
        registro['certeza'] = linha['certainty']
        if linha['description_snapshot']:
            registro['descricao'] = linha['description_snapshot']

    vigentes, refutados = [], []
    for registro in list(por_codigo.values())[:limit]:
        saida = {
            'codigo': registro['codigo'], 'descricao': registro['descricao'],
            'certeza': dict(DiagnosisCertainty.choices).get(registro['certeza'], registro['certeza']),
            'registrado_desde': registro['primeiro_registro'].date().isoformat(),
            'ultima_mencao': registro['ultimo_registro'].date().isoformat(),
        }
        if registro['certeza'] == DiagnosisCertainty.REFUTED:
            refutados.append(saida)
        else:
            vigentes.append(saida)
    return vigentes, refutados


def get_patient_medications(authorization, limit=MAX_MEDICATIONS):
    """Medicações do paciente, a mais recente de cada nome.

    A medicação é registrada por atendimento, então um anticonvulsivante
    mantido por cinco anos aparece em dez linhas iguais. O relatório
    precisa de "em uso desde quando, em que dose hoje" -- e isso é a
    primeira menção com o último registro, não dez repetições.
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    limit = min(int(limit), MAX_MEDICATIONS)
    medications = (
        Medication.objects
        .filter(tenant_id=authorization.tenant_id, encounter__patient_id=authorization.patient_id)
        .select_related('encounter')
        .order_by('encounter__occurred_at')
    )
    por_nome = {}
    for m in medications:
        chave = (m.name or '').strip().lower()
        if not chave:
            continue
        anterior = por_nome.get(chave)
        desde = anterior['desde'] if anterior else (
            m.started_on.isoformat() if m.started_on
            else m.encounter.occurred_at.date().isoformat()
        )
        por_nome[chave] = {
            'nome': m.name, 'dose': m.dose, 'via': m.get_route_display(),
            'frequencia': m.frequency, 'desde': desde,
            'indicacao': m.indication, 'situacao': m.get_status_display(),
            'observacao': m.notes,
        }
    return list(por_nome.values())[:limit]
