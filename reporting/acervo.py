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
    ('personal_history', 'Antecedentes pessoais'),
    ('family_history', 'Antecedentes familiares'),
    ('habits_history', 'Hábitos'),
    ('consanguinity_details', 'Consanguinidade'),
    ('free_text', 'Evolução'),
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
    from clinical.models import Encounter

    consulta = (
        Encounter.objects.filter(tenant_id=tenant_id)
        .select_related('patient', 'physician_membership__user')
        .order_by('patient__full_name', 'occurred_at')
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
            'tipo': encontro.get_kind_display(),
            'situacao': encontro.get_status_display(),
            'finalizado_em': encontro.finalized_at,
            'id': str(encontro.id),
        }
        for campo, rotulo in SECOES_CLINICAS:
            linha[rotulo] = _texto(getattr(encontro, campo))
        linhas.append(linha)
    return linhas


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
        cabecalho = data.strftime('%d/%m/%Y %H:%M') if hasattr(data, 'strftime') else str(data)
        linhas += [f'### {cabecalho} — {row["medico"]}', '',
                   f'*{row["tipo"]} · {row["situacao"]}*', '']
        for _campo, rotulo in SECOES_CLINICAS:
            texto = row.get(rotulo)
            if texto:
                linhas += [f'**{rotulo}**', '', texto, '']
    return '\n'.join(linhas)
