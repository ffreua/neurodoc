"""Rótulos das terminologias TUSS usadas na guia TISS — gerado, não editar à mão.

Fonte: "TUSS - Demais terminologias - VERSÃO 202609.xlsx", do pacote
`Padrao_TISS_Representacao_de_Conceitos_em_Saude_202609.zip` da ANS
(SHA-256 do XLSX: ad62541b18a4a7652bb883c9aa89940f712d54630c3610c067626acc3fba13c7). Gerado por um script de leitura do
XLSX; para atualizar, rode-o de novo sobre o pacote novo.

**Quem decide se um código é aceito é o XSD da versão** (`versoes.dominio`):
esta tabela só dá o nome que a tela mostra. O código é comparado sem zero à
esquerda (`rotulo`), porque a planilha guarda alguns como número.
"""

TITULOS = {
    '23': 'caráter do atendimento',
    '35': 'grau de participação',
    '36': 'indicador de acidente',
    '39': 'motivo de encerramento',
    '48': 'técnica utilizada',
    '50': 'tipo de atendimento',
    '52': 'tipo de consulta',
    '61': 'via de acesso',
    '74': 'motivo de ausência do código de validação',
    '75': 'indicador de cobertura especial',
    '76': 'regime de atendimento',
    '77': 'saúde ocupacional',
    '87': 'tabelas (código da tabela do procedimento)',
}

TERMOS = {
    '23': {
        '1': 'Eletivo',
        '2': 'Urgência/Emergência',
    },
    '35': {
        '00': 'Cirurgião',
        '01': 'Primeiro Auxiliar',
        '02': 'Segundo Auxiliar',
        '03': 'Terceiro Auxiliar',
        '04': 'Quarto Auxiliar',
        '05': 'Instrumentador',
        '06': 'Anestesista',
        '07': 'Auxiliar de Anestesista',
        '08': 'Consultor',
        '09': 'Perfusionista',
        '10': 'Pediatra na sala de parto',
        '11': 'Auxiliar SADT',
        '12': 'Clínico',
        '13': 'Intensivista',
    },
    '36': {
        '0': 'Trabalho',
        '1': 'Trânsito',
        '2': 'Outros',
        '9': 'Não Acidente',
    },
    '39': {
        '11': 'Alta Curado',
        '12': 'Alta Melhorado',
        '14': 'Alta a pedido',
        '15': 'Alta com previsão de retorno para acompanhamento do paciente',
        '16': 'Alta por Evasão',
        '18': 'Alta por outros motivos',
        '19': 'Alta de Paciente Agudo em Psiquiatria',
        '21': 'Permanência, por características próprias da doença',
        '22': 'Permanência, por intercorrência',
        '23': 'Permanência, por impossibilidade sócio-familiar',
        '24': 'Permanência, por Processo de doação de órgãos, tecidos e células - doador vivo',
        '25': 'Permanência, por Processo de doação de órgãos, tecidos e células - doador morto',
        '26': 'Permanência, por mudança de Procedimento',
        '27': 'Permanência, por reoperação',
        '28': 'Permanência, outros motivos',
        '31': 'Transferido para outro estabelecimento',
        '32': 'Transferência para Internação Domiciliar',
        '41': 'Óbito com declaração de óbito fornecida pelo médico assistente',
        '42': 'Óbito com declaração de Óbito fornecida pelo Instituto Médico Legal - IML',
        '43': 'Óbito com declaração de Óbito fornecida pelo Serviço de Verificação de Óbito - SVO.',
        '51': 'Encerramento Administrativo',
        '61': 'Alta da mãe/puérpera e do recém-nascido',
        '62': 'Alta da mãe/puérpera e permanência do recém-nascido',
        '63': 'Alta da mãe/puérpera e óbito do recém-nascido',
        '64': 'Alta da mãe/puérpera com óbito fetal',
        '65': 'Óbito da gestante e do concepto',
        '66': 'Óbito da mãe/puérpera e alta do recém-nascido',
        '67': 'Óbito da mãe/puérpera e permanência do recém-nascido',
    },
    '48': {
        '1': 'Convencional',
        '2': 'Video',
        '3': 'Robótica',
    },
    '50': {
        '01': 'Remoção',
        '02': 'Pequena Cirurgia',
        '03': 'Outras Terapias',
        '04': 'Consulta',
        '08': 'Quimioterapia',
        '09': 'Radioterapia',
        '10': 'Terapia Renal Substitutiva (TRS)',
        '13': 'Pequeno atendimento (sutura, gesso e outros)',
        '23': 'Exame',
    },
    '52': {
        '1': 'Primeira Consulta',
        '2': 'Retorno',
        '3': 'Pré-natal',
        '4': 'Por encaminhamento',
    },
    '61': {
        '1': 'Única',
        '2': 'Mesma via',
        '3': 'Diferentes vias',
    },
    '74': {
        '01': 'Beneficiário internado',
        '02': 'Beneficiário em situação de urgência/emergência',
        '03': 'Intermitência/Instabilidade de sistemas e regularização do atendimento após saída do beneficiário do prestador de serviço',
        '04': 'Beneficiário se negou a transmitir o número do token',
        '05': 'Beneficiário em coleta domiciliar',
        '06': 'Material para exames enviado ao prestador por terceiros',
        '07': 'Beneficiário não possui celular',
    },
    '75': {
        '01': 'Gestante',
        '02': 'Pré-operatório',
        '03': 'Pós-operatório',
    },
    '76': {
        '01': 'Ambulatorial',
        '02': 'Domiciliar',
        '03': 'Internação',
        '04': 'Pronto-socorro',
        '05': 'TELESSAÚDE',
    },
    '77': {
        '01': 'Admissional',
        '02': 'Demissional',
        '03': 'Periódico',
        '04': 'Retorno ao trabalho',
        '05': 'Mudança de função',
        '06': 'Promoção à saúde',
    },
    '87': {
        '00': 'Tabela própria das operadoras',
        '18': 'Diárias, taxas e gases medicinais',
        '19': 'Materiais e Órteses, Próteses e Materiais Especiais (OPME)',
        '20': 'Medicamentos',
        '22': 'Procedimentos e eventos em saúde',
        '23': 'Caráter do atendimento',
        '24': 'Classificação Brasileira de Ocupações (CBO)',
        '25': 'Código da despesa',
        '26': 'Conselho profissional',
        '27': 'Débitos e créditos',
        '28': 'Dentes',
        '29': 'Diagnóstico por imagem',
        '30': 'Escala de capacidade funcional (ECOG - Escala de Zubrod)',
        '31': 'Estadiamento do tumor',
        '32': 'Faces do dente',
        '33': 'Finalidade do tratamento',
        '34': 'Forma de pagamento',
        '35': 'Grau de participação',
        '36': 'Indicador de acidente',
        '37': 'Indicador de débito ou crédito',
        '38': 'Mensagens (glosas, negativas e outras)',
        '39': 'Motivo de encerramento',
        '40': 'Origem da guia',
        '41': 'Regime de internação',
        '42': 'Regiões da boca',
        '43': 'Sexo',
        '44': 'Situação inicial do dente',
        '45': 'Status da solicitação',
        '46': 'Status do cancelamento',
        '47': 'Status da guia e do protocolo',
        '48': 'Técnica utilizada',
        '49': 'Tipo de acomodação',
        '50': 'Tipo de atendimento',
        '51': 'Tipo de atendimento em odontologia',
        '52': 'Tipo de consulta',
        '53': 'Tipo de demonstrativo',
        '54': 'Tipo de guia',
        '55': 'Tipo de faturamento',
        '56': 'Natureza da guia',
        '57': 'Tipo de internação',
        '58': 'Tipo de quimioterapia',
        '59': 'Unidade da federação',
        '60': 'Unidade de medida',
        '61': 'Via de acesso',
        '62': 'Via de administração',
        '63': 'Grupos de procedimentos e itens assistenciais para envio para ANS',
        '64': 'Forma de envio de procedimentos e itens assistenciais para ANS',
        '65': 'Metástase',
        '66': 'Nódulo',
        '67': 'Tumor',
        '68': 'Categoria de despesa',
        '69': 'Versão do componente de comunicação do padrão',
        '70': 'Forma de envio de padrão',
        '71': 'Tipo de atendimento por operadora intermediária',
        '72': 'Tipo de identificação do beneficiário',
        '73': 'Etapas de autorização',
        '74': 'Motivos de ausência do código de validação',
        '87': 'Tabelas de domínio',
        '90': 'Tabela Própria Pacote Odontológico',
        '98': 'Tabela Própria de Pacotes',
        '75': 'Cobertura especial',
        '76': 'Regime de atendimento',
        '77': 'Saúde ocupacional',
        '78': 'Tipo de Pagamento',
        '79': 'Modelos de Remuneração entre Operadoras e Prestadores',
        '80': 'Formato do documento',
        '81': 'Tipo do documento',
        '82': 'Centro de consumo',
    },
}


def rotulo(tabela, codigo):
    """O termo da TUSS para o código, ou o próprio código se não houver."""
    alvo = str(codigo or '').lstrip('0') or '0'
    for chave, termo in TERMOS.get(str(tabela), {}).items():
        if (chave.lstrip('0') or '0') == alvo:
            return termo
    return str(codigo or '')


def escolhas(tabela, dominio):
    """Pares (código, "código — termo") só com os códigos do domínio do XSD.

    O domínio vem da versão (`versoes.dominio`), e é ele que manda: um código
    da TUSS que a versão não aceita não aparece na tela.
    """
    return [(c, f'{c} — {rotulo(tabela, c)}') for c in dominio]
