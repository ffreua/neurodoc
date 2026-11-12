"""O acervo da clínica, para sair do sistema.

Não é indicador: é o dado inteiro, no formato de quem vai levá-lo embora.
A cláusula 13.1 do contrato de adesão promete "a obtenção dos dados sob
sua gestão em formato tecnicamente adequado e de uso comum", e a 4.8 diz
que prontuário não é retido como garantia de pagamento. Estas duas
funções são o que torna aquilo verdade — sem elas, a promessa dependeria
de alguém com acesso ao banco.

**Dois relatórios, e não um.** Cadastro e prontuário são coisas de altura
diferente: o primeiro é administrativo e o dono da clínica o administra
todo dia; o segundo é conteúdo clínico, e quem o lê é o médico. Juntos num
arquivo só, o acesso ao mais sensível passaria a depender da permissão do
menos — ver `reporting/apps.py`, onde cada um declara a capacidade que
exige.

**Sem paginação, e por isso sem `count_fn`.** Exportar acervo é a operação
que se quer completa; devolvê-la em pedaços transformaria o direito da
cláusula 13.1 num quebra-cabeça. Sem `count_fn`, `request_export` manda
direto para o worker — que é onde uma clínica de dez anos deve ser lida,
e não dentro de uma requisição.
"""


def _texto(valor):
    return (valor or '').strip()


def pacientes_rows(tenant_id, **_parametros):
    """Cadastro completo dos pacientes da clínica.

    `iterator()` com `chunk_size` porque isto roda no worker sobre a
    clínica inteira: um `list()` de vinte mil pacientes com contatos e
    convênios carregados de uma vez é memória que o contêiner do worker
    não tem sobrando, e o processo morre sem dizer por quê.
    """
    from patients.models import Patient

    consulta = (
        Patient.objects.filter(tenant_id=tenant_id)
        .prefetch_related('contacts', 'coverages__plan')
        .order_by('record_number', 'full_name')
    )
    linhas = []
    for paciente in consulta.iterator(chunk_size=200):
        contatos = [
            {
                'nome': _texto(c.name), 'parentesco': _texto(c.relationship),
                'telefone': _texto(c.phone), 'email': _texto(c.email),
            }
            for c in paciente.contacts.all()
        ]
        convenios = [
            {
                'convenio': getattr(cob.plan, 'name', ''),
                'numero_da_carteirinha': _texto(cob.member_number),
                'inicio': cob.starts_on,
                'fim': cob.ends_on,
            }
            for cob in paciente.coverages.all()
        ]
        linhas.append({
            'numero_do_prontuario': _texto(paciente.record_number),
            'nome': paciente.full_name,
            'nascimento': paciente.birth_date,
            'sexo_no_cadastro': paciente.get_sex_at_registration_display(),
            'cpf': _texto(paciente.cpf),
            'documento_de_identidade': _texto(paciente.identity_number),
            'nome_da_mae': _texto(paciente.mother_name),
            'cep': _texto(paciente.postal_code),
            'logradouro': _texto(paciente.street),
            'numero': _texto(paciente.number),
            'complemento': _texto(paciente.complement),
            'bairro': _texto(paciente.district),
            'cidade': _texto(paciente.city),
            'uf': _texto(paciente.state),
            'estado_civil': paciente.get_marital_status_display(),
            'ocupacao': _texto(paciente.occupation),
            'origem_do_encaminhamento': paciente.get_referral_source_display(),
            'detalhe_do_encaminhamento': _texto(paciente.referral_details),
            'forma_de_pagamento': paciente.get_payment_category_display(),
            'situacao': paciente.get_status_display(),
            'arquivado_em': paciente.archived_at,
            'motivo_do_arquivamento': _texto(paciente.archived_reason),
            'cadastrado_em': paciente.created_at,
            'contatos': contatos,
            'convenios': convenios,
            'id': str(paciente.id),
        })
    return linhas


#: Colunas do cadastro, na ordem em que uma pessoa lê uma ficha.
#:
#: Contatos e convênios ficam de fora: são listas, e lista não cabe em
#: célula. Eles seguem inteiros no JSON e viram linhas próprias no
#: Markdown — o CSV é o formato que não os comporta, e é por isso que o
#: cadastro também se exporta em JSON.
PACIENTES_COLUNAS = [
    'numero_do_prontuario', 'nome', 'nascimento', 'sexo_no_cadastro', 'cpf',
    'documento_de_identidade', 'nome_da_mae', 'cep', 'logradouro', 'numero',
    'complemento', 'bairro', 'cidade', 'uf', 'estado_civil', 'ocupacao',
    'origem_do_encaminhamento', 'detalhe_do_encaminhamento',
    'forma_de_pagamento', 'situacao', 'arquivado_em',
    'motivo_do_arquivamento', 'cadastrado_em',
]


def pacientes_markdown(rows, **_parametros):
    """O cadastro como documento, uma ficha por paciente.

    Tabela não serve aqui: são vinte e uma colunas mais duas listas, e uma
    tabela de vinte e três colunas não se lê em editor nenhum. Uma ficha
    por paciente é como o dado é consultado de verdade — procura-se **um**
    paciente, não se varre a coluna "bairro".
    """
    linhas = ['# Cadastro de pacientes', '',
              f'{len(rows)} paciente(s).', '']
    for row in rows:
        titulo = row['nome']
        if row['numero_do_prontuario']:
            titulo = f'{row["numero_do_prontuario"]} — {titulo}'
        linhas += [f'## {titulo}', '']
        for coluna in PACIENTES_COLUNAS:
            if coluna == 'nome':
                continue
            valor = row.get(coluna)
            if valor in (None, '', False):
                continue
            rotulo = coluna.replace('_', ' ').capitalize()
            linhas.append(f'- **{rotulo}:** {valor}')
        for contato in row['contatos']:
            partes = [p for p in [
                contato['nome'], contato['parentesco'],
                contato['telefone'], contato['email'],
            ] if p]
            if partes:
                linhas.append('- **Contato:** ' + ' · '.join(partes))
        for cobertura in row['convenios']:
            partes = [str(p) for p in [
                cobertura['convenio'], cobertura['numero_da_carteirinha'],
                cobertura['inicio'], cobertura['fim'],
            ] if p]
            if partes:
                linhas.append('- **Convênio:** ' + ' · '.join(partes))
        linhas.append('')
    return '\n'.join(linhas)


#: Os campos do atendimento estruturado, na ordem da consulta, com o
#: rótulo que o médico reconhece. Vem daqui e não de `verbose_name`
#: porque o documento exportado tem leitor humano, e "Hpi" não é um
#: cabeçalho de seção.
SECOES_CLINICAS = [
    ('chief_complaint', 'Queixa principal'),
    ('hpi', 'História da doença atual'),
    # O campo do seguimento (1.41). "Evolução" era o rótulo do texto livre
    # até aqui, que passou a se chamar pelo nome da tela que o escreve —
    # duas seções com o mesmo título no Markdown seriam indistinguíveis.
    ('evolucao', 'Evolução'),
    ('personal_history', 'Antecedentes pessoais'),
    ('family_history', 'Antecedentes familiares'),
    ('habits_history', 'Hábitos'),
    ('consanguinity_details', 'Consanguinidade'),
    ('neurological_exam_text', 'Exame neurológico em texto livre'),
    ('free_text', 'Texto livre'),
    ('impressions', 'Impressões'),
    ('plan_text', 'Conduta'),
]


def atendimentos_rows(tenant_id, **_parametros):
    """Os atendimentos da clínica, com o texto das anotações.

    Ordenado por paciente e depois por data: é assim que um prontuário se
    lê, e é assim que o Markdown agrupa. Ordenar só por data produziria um
    diário da clínica — útil para outra coisa, inútil para acompanhar um
    caso.
    """
    from django.db.models import Prefetch

    from clinical.models import (
        ClinicalAmendment, Encounter, EncounterDiagnosis, ExamResult, ExaminationFinding,
    )

    # O `patient_id` entre o nome e a data: dois pacientes homônimos
    # ordenados só por nome se intercalavam por data, e o Markdown abria
    # um capítulo novo a cada troca — o prontuário de cada um em pedaços.
    consulta = (
        Encounter.objects.filter(tenant_id=tenant_id)
        .select_related('patient', 'physician_membership__user')
        .prefetch_related(
            Prefetch('diagnoses', queryset=EncounterDiagnosis.objects.order_by('rank')),
            Prefetch('medications'),
            Prefetch(
                'examination_findings',
                queryset=ExaminationFinding.objects.select_related('template_node')
                .order_by('domain', 'item_code', 'side'),
            ),
            Prefetch(
                'exam_results',
                queryset=ExamResult.objects.prefetch_related('lab_values').order_by('-performed_on', 'name'),
            ),
            Prefetch(
                'amendments',
                queryset=ClinicalAmendment.objects.select_related('author__user').order_by('authored_at'),
            ),
        )
        .order_by('patient__full_name', 'patient_id', 'occurred_at')
    )
    linhas = []
    for encontro in consulta.iterator(chunk_size=100):
        medico = encontro.physician_membership.user
        linha = {
            'paciente': encontro.patient.full_name,
            'numero_do_prontuario': _texto(encontro.patient.record_number),
            'paciente_id': str(encontro.patient_id),
            'data': encontro.occurred_at,
            'medico': medico.get_full_name() or medico.email,
            'tipo': encontro.rotulo_do_tipo,
            'situacao': encontro.get_status_display(),
            'finalizado_em': encontro.finalized_at,
            'id': str(encontro.id),
        }
        for campo, rotulo in SECOES_CLINICAS:
            linha[rotulo] = _texto(getattr(encontro, campo))
        linha.update(_registros_do_atendimento(encontro))
        linhas.append(linha)
    return linhas


def _nome(membership):
    if membership is None:
        return ''
    return membership.user.get_full_name() or membership.user.email


def _registros_do_atendimento(encontro):
    """O que o atendimento registra fora dos campos de texto.

    **Até a auditoria de 2026-11-11 isto não saía**, e o acervo era o
    texto e nada mais: sem a hipótese com o CID, sem a medicação, sem o
    exame neurológico do roteiro e as escalas, sem o resultado de exame e
    — o mais grave — sem o **adendo**, que é a única forma de corrigir um
    atendimento finalizado. A clínica que levasse o acervo levava um
    prontuário diferente do registrado, e a cláusula 14.3 do contrato 2.0
    promete "adendos, metadados".

    Cada lista vem do `prefetch_related` de `atendimentos_rows`, com a
    mesma ordem e o mesmo rótulo do resumo do caso
    (`clinical.views.PatientSummaryView`).
    """
    from clinical.examination import group_findings_by_domain

    exame = []
    for grupo in group_findings_by_domain(list(encontro.examination_findings.all())):
        for achado in grupo['findings']:
            valor = achado.qualifier
            if not valor and achado.numeric_value is not None:
                valor = str(achado.numeric_value)
            exame.append({
                'grupo': grupo['label'],
                'item': achado.label,
                'lado': '' if achado.side == 'not_applicable' else achado.get_side_display(),
                'valor': valor or achado.get_state_display(),
                'observacao': _texto(achado.note),
            })
    return {
        'hipoteses': [
            {
                'codigo': _texto(d.code_snapshot),
                'descricao': _texto(d.description_snapshot),
                'certeza': d.get_certainty_display(),
                'nota_do_medico': _texto(d.physician_note),
            }
            for d in encontro.diagnoses.all()
        ],
        'medicacoes': [
            {
                'nome': m.name, 'dose': _texto(m.dose), 'via': m.get_route_display(),
                'frequencia': _texto(m.frequency), 'inicio': m.started_on,
                'indicacao': _texto(m.indication), 'situacao': m.get_status_display(),
                'prescritor': _texto(m.prescriber), 'observacao': _texto(m.notes),
            }
            for m in sorted(encontro.medications.all(), key=lambda m: m.name)
        ],
        'exame_neurologico': exame,
        'resultados_de_exame': [
            {
                'exame': r.name, 'categoria': r.get_category_display(),
                'realizado_em': r.performed_on, 'servico': _texto(r.service_name),
                'laudo': _texto(r.report_text), 'conclusao': _texto(r.conclusion),
                'valores': [
                    {
                        'analito': v.analyte, 'valor': v.value_text, 'unidade': _texto(v.unit),
                        'referencia': _texto(v.reference_text), 'sinalizacao': v.get_flag_display(),
                    }
                    for v in r.lab_values.all()
                ],
            }
            for r in encontro.exam_results.all()
        ],
        'adendos': [
            {
                'em': a.authored_at, 'autor': _nome(a.author),
                'motivo': _texto(a.reason), 'texto': _texto(a.text),
            }
            for a in encontro.amendments.all()
        ],
    }


#: Colunas da tabela do atendimento. Só as de identificação: o texto
#: clínico tem milhares de caracteres e não é célula de planilha. Ele sai
#: inteiro no JSON e como seção no Markdown.
ATENDIMENTOS_COLUNAS = [
    'numero_do_prontuario', 'paciente', 'data', 'medico', 'tipo', 'situacao',
    'finalizado_em',
]


def atendimentos_markdown(rows, **_parametros):
    """O prontuário como documento: um capítulo por paciente, em ordem.

    É o formato que o contrato promete quando diz "de uso comum": abre em
    qualquer editor, imprime, e um médico que receba este arquivo consegue
    acompanhar o caso do começo ao fim. A alternativa — uma tabela com uma
    coluna de vinte mil caracteres — é tecnicamente uma exportação e
    praticamente um arquivo que ninguém consegue ler.

    Seção vazia não é impressa. Um atendimento de texto livre não tem
    queixa nem antecedentes preenchidos, e imprimir nove cabeçalhos vazios
    embaixo de cada consulta transformaria o documento em formulário em
    branco.
    """
    linhas = ['# Atendimentos', '', f'{len(rows)} atendimento(s).', '']
    paciente_atual = None
    for row in rows:
        if row['paciente_id'] != paciente_atual:
            paciente_atual = row['paciente_id']
            titulo = row['paciente']
            if row['numero_do_prontuario']:
                titulo = f'{row["numero_do_prontuario"]} — {titulo}'
            linhas += ['', f'## {titulo}', '']
        data = row['data']
        # Na hora de Brasília: o `occurred_at` vem do banco em UTC, e o
        # `strftime` direto imprimia três horas adiantado — a consulta das
        # 21h saía no dia seguinte (CLAUDE.md §1; revisão de 2026-11-02, W9).
        if hasattr(data, 'strftime'):
            from django.utils import timezone

            if timezone.is_aware(data):
                data = timezone.localtime(data)
            cabecalho = data.strftime('%d/%m/%Y %H:%M')
        else:
            cabecalho = str(data)
        linhas += [f'### {cabecalho} — {row["medico"]}', '',
                   f'*{row["tipo"]} · {row["situacao"]}*', '']
        for _campo, rotulo in SECOES_CLINICAS:
            texto = row.get(rotulo)
            if texto:
                linhas += [f'**{rotulo}**', '', texto, '']
        linhas += _registros_em_markdown(row)
    return '\n'.join(linhas)


def _juntar(*partes):
    return ' · '.join(str(p) for p in partes if p)


def _registros_em_markdown(row):
    """As listas do atendimento, cada uma só se tiver linha — pela mesma
    razão de a seção de texto vazia não ser impressa."""
    from django.utils import timezone

    linhas = []
    if row.get('hipoteses'):
        linhas += ['**Hipóteses diagnósticas**', '']
        for h in row['hipoteses']:
            linhas.append('- ' + _juntar(h['codigo'], h['descricao'], h['certeza'], h['nota_do_medico']))
        linhas.append('')
    if row.get('medicacoes'):
        linhas += ['**Medicações**', '']
        for m in row['medicacoes']:
            linhas.append('- ' + _juntar(
                m['nome'], m['dose'], m['via'], m['frequencia'], m['situacao'],
                m['indicacao'], m['observacao'],
            ))
        linhas.append('')
    if row.get('exame_neurologico'):
        linhas += ['**Exame neurológico e escalas**', '']
        grupo_atual = None
        for e in row['exame_neurologico']:
            if e['grupo'] != grupo_atual:
                grupo_atual = e['grupo']
                linhas.append(f'- *{grupo_atual}*')
            item = f'{e["item"]} ({e["lado"].lower()})' if e['lado'] else e['item']
            linhas.append('  - ' + _juntar(f'{item}: {e["valor"]}', e['observacao']))
        linhas.append('')
    if row.get('resultados_de_exame'):
        linhas += ['**Resultados de exame**', '']
        for r in row['resultados_de_exame']:
            data = r['realizado_em'].strftime('%d/%m/%Y') if r['realizado_em'] else ''
            linhas.append('- ' + _juntar(r['exame'], r['categoria'], data, r['servico']))
            for v in r['valores']:
                linhas.append('  - ' + _juntar(
                    f'{v["analito"]}: {v["valor"]} {v["unidade"]}'.strip(),
                    v['referencia'], v['sinalizacao'],
                ))
            if r['conclusao']:
                linhas.append(f'  - Conclusão: {r["conclusao"]}')
            if r['laudo']:
                linhas += ['', '  ' + r['laudo'].replace('\n', '\n  ')]
        linhas.append('')
    for a in row.get('adendos') or []:
        quando = a['em']
        if hasattr(quando, 'strftime'):
            if timezone.is_aware(quando):
                quando = timezone.localtime(quando)
            quando = quando.strftime('%d/%m/%Y %H:%M')
        linhas += [f'**Adendo de {quando} — {a["autor"]}**', '']
        if a['motivo']:
            linhas += [f'*Motivo: {a["motivo"]}*', '']
        linhas += [a['texto'], '']
    return linhas
