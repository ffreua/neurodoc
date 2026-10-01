"""Tradução de uma ficha do sistema anterior para o cadastro do NeuroDoc.

Migrar duas mil fichas à mão não acontece: a secretária desiste na
centésima, e o que não foi digitado vira paciente que o sistema novo não
conhece. Este módulo faz a tradução, e o comando
`import_pacientes_xml` a executa.

**O que esta leitura decide, e o que ela recusa a decidir.**

Traduzir cadastro antigo é, quase todo, adivinhar. A regra que seguimos:
quando o dado antigo cabe num campo do NeuroDoc **sem interpretação**, ele
entra no campo; quando exigiria interpretar, ele entra como texto nas
observações administrativas, onde um humano o lê e decide. Jogar fora é a
única coisa que não se faz — o dado existia, e quem apagar não saberá o
que apagou.

Os casos em que isso pesa:

- **Convênio.** O arquivo traz `PARTICULAR`, `FAMILIAR`, `GRATUIDADE` e
  `DESCONTO MEDICO 50%`. Nenhum é operadora de saúde: são **categorias de
  cobrança** daquela clínica. Criar `Insurer` e `HealthPlan` a partir
  disso encheria o cadastro de convênios que não existem. Então
  `payment_category` fica **particular** para todos, e o que não for
  "PARTICULAR" vai para as observações.
- **Indicação.** Mil duzentos e vinte e sete valores distintos, quase
  todos o nome de quem encaminhou ("DR. ALEXANDRE SEGRE", "IND. DE
  PACIENTE"). O texto inteiro é preservado em `referral_details`; a
  classificação em `referral_source` é uma heurística declarada, e erra
  para "Outro", que é o valor que não afirma nada.
- **Endereço.** Vem num campo só, e em 81% das fichas no formato
  `RUA X, 295 AP 804`. A separação é feita, e quando a forma não é essa o
  endereço inteiro fica em `street` — torto, mas legível, e nunca perdido.

**Nada é marcado como pré-cadastro.** A ficha migrada é um cadastro de
verdade, com nome, nascimento, CPF e endereço; tratá-la como "pré" a
esconderia da lista de pacientes, que é exatamente onde ela precisa
aparecer.
"""
import re
import unicodedata
from datetime import datetime

from django.utils import timezone

from .models import MaritalStatus, PaymentCategory, ReferralSource, SexAtRegistration
from .naming import normalizar_nome

#: Os campos do XML que esta leitura consome. Declarados para que o
#: comando possa avisar se o arquivo vier com outra forma, em vez de
#: importar duas mil fichas vazias em silêncio.
CAMPOS_ESPERADOS = {
    'NUM_ICLIN', 'NOME', 'DT_NASC', 'CPF', 'SEXO', 'ESTADO_CIVIL', 'PROFISSAO',
    'IDENTIDADE', 'ENDERECO', 'CEP', 'BAIRRO', 'MUNICIPIO', 'UF',
    'TEL_RES', 'TEL_OUTRO', 'EMAIL', 'RESPONSAVEL', 'RESPONSAVEL_PAR',
    'CONV_NOME', 'INDICACAO', 'CANCELADO', 'NUM_PRONTUARIO',
}

SEXO = {'F': SexAtRegistration.FEMALE, 'M': SexAtRegistration.MALE}

#: `SE` (separado) não tem correspondente no NeuroDoc, e cai em "Outro" em
#: vez de virar "divorciado": separação e divórcio são estados civis
#: diferentes, e o cadastro não pode afirmar um pelo outro.
ESTADO_CIVIL = {
    'CA': MaritalStatus.MARRIED,
    'SO': MaritalStatus.SINGLE,
    'VI': MaritalStatus.WIDOWED,
    'DI': MaritalStatus.DIVORCED,
    'SE': MaritalStatus.OTHER,
    'UN': MaritalStatus.STABLE_UNION,
}


def _texto(registro, tag):
    elemento = registro.find(tag)
    return (elemento.text or '').strip() if elemento is not None else ''


def _digitos(valor):
    return ''.join(c for c in (valor or '') if c.isdigit())


def _sem_acento(texto):
    decomposto = unicodedata.normalize('NFKD', texto or '')
    return ''.join(c for c in decomposto if not unicodedata.combining(c)).upper()


def data_br(valor):
    """`dd/mm/aaaa` para `date`. `None` quando não for uma data de gente.

    Data impossível não vira exceção: vira ausência, e o motivo fica
    escrito na ficha. Uma importação que para na linha 1.400 por causa de
    um "30/02/1980" deixa as outras oitocentas de fora.
    """
    try:
        dia = datetime.strptime((valor or '').strip(), '%d/%m/%Y').date()
    except ValueError:
        return None
    # Nascimento no futuro ou antes de 1900 é erro de digitação do sistema
    # antigo, não longevidade.
    if dia.year < 1900 or dia > timezone.localdate():
        return None
    return dia


def origem_da_indicacao(texto):
    """Classifica quem encaminhou, e erra para "Outro".

    Heurística declarada, e de propósito conservadora: "DR." e "DRA." no
    texto indicam médico; "PACIENTE" indica paciente. Qualquer outra coisa
    é "Outro" — que não afirma nada e deixa o texto original falar.
    """
    alvo = _sem_acento(texto)
    if not alvo:
        return ReferralSource.NOT_INFORMED
    if re.search(r'\bDRA?\.?\b|\bDOUTOR', alvo):
        return ReferralSource.PHYSICIAN
    if 'PACIENTE' in alvo:
        return ReferralSource.PATIENT
    if 'INTERNET' in alvo or 'GOOGLE' in alvo or 'SITE' in alvo:
        return ReferralSource.INTERNET
    return ReferralSource.OTHER


def separar_endereco(valor):
    """`RUA X, 295 AP 804` → logradouro, número e complemento.

    Devolve o endereço inteiro como logradouro quando não reconhece a
    forma. Endereço torto e legível serve à secretária; endereço perdido
    não serve a ninguém.
    """
    bruto = ' '.join((valor or '').split())
    if not bruto:
        return '', '', ''
    if ',' not in bruto:
        return bruto[:255], '', ''
    logradouro, _, resto = bruto.rpartition(',')
    resto = resto.strip()
    casamento = re.match(r'^(\d+[A-Za-z]?)\s*(.*)$', resto)
    if not casamento:
        # Vírgula sem número depois ("RUA X, FUNDOS") — o que vem depois é
        # complemento, não número.
        return logradouro.strip()[:255], '', resto[:100]
    return logradouro.strip()[:255], casamento.group(1)[:30], casamento.group(2).strip()[:100]


def telefones(registro):
    """Os telefones da ficha, em dígitos, sem repetir.

    `TEL_OUTRO` vem primeiro porque é o preenchido em 97,8% das fichas (o
    celular), contra 45,3% do `TEL_RES`. O primeiro da lista é o que vai
    para o contato principal, e celular é por onde se alcança alguém.
    """
    vistos = []
    for tag in ('TEL_OUTRO', 'TEL_RES'):
        numero = _digitos(_texto(registro, tag))
        if 8 <= len(numero) <= 16 and numero not in vistos:
            vistos.append(numero)
    return vistos


def ler_registro(registro):
    """Traduz um `<CLIENTE>` para o dicionário que o comando grava.

    Devolve `None` quando a ficha não tem nome: sem nome não há paciente,
    e inventar "Sem nome" criaria fichas que ninguém acha e ninguém apaga.
    """
    nome = normalizar_nome(_texto(registro, 'NOME'))
    if not nome:
        return None

    nascimento = data_br(_texto(registro, 'DT_NASC'))
    cpf = _digitos(_texto(registro, 'CPF'))
    logradouro, numero, complemento = separar_endereco(_texto(registro, 'ENDERECO'))
    indicacao = _texto(registro, 'INDICACAO')
    convenio = _texto(registro, 'CONV_NOME')

    # As observações administrativas são o destino do que não cabe em
    # campo — e o lugar onde a secretária lê o que veio do sistema antigo.
    anotacoes = []
    prontuario_antigo = _texto(registro, 'NUM_PRONTUARIO')
    if prontuario_antigo:
        # A pasta de papel está etiquetada com este número. Perdê-lo é
        # perder a ligação entre o arquivo físico e a ficha na tela.
        anotacoes.append(f'Prontuário no sistema anterior: {prontuario_antigo}')
    if convenio and _sem_acento(convenio) != 'PARTICULAR':
        anotacoes.append(f'Categoria de cobrança no sistema anterior: {convenio}')
    if not nascimento and _texto(registro, 'DT_NASC'):
        anotacoes.append(
            f'Data de nascimento no sistema anterior não pôde ser lida: '
            f'{_texto(registro, "DT_NASC")!r}'
        )

    ficha = {
        'legacy_id': _texto(registro, 'NUM_ICLIN'),
        'full_name': nome,
        'birth_date': nascimento,
        'cpf': cpf if len(cpf) == 11 else '',
        'sex_at_registration': SEXO.get(
            _texto(registro, 'SEXO').upper(), SexAtRegistration.NOT_INFORMED,
        ),
        'marital_status': ESTADO_CIVIL.get(
            _texto(registro, 'ESTADO_CIVIL').upper(), MaritalStatus.NOT_INFORMED,
        ),
        'occupation': _texto(registro, 'PROFISSAO')[:150],
        'identity_number': _texto(registro, 'IDENTIDADE')[:30],
        'street': logradouro,
        'number': numero,
        'complement': complemento,
        'district': _texto(registro, 'BAIRRO')[:100],
        'city': _texto(registro, 'MUNICIPIO')[:100],
        'state': _texto(registro, 'UF').upper()[:2],
        'postal_code': _digitos(_texto(registro, 'CEP'))[:8],
        'country': 'BR',
        'payment_category': PaymentCategory.PRIVATE,
        'referral_source': origem_da_indicacao(indicacao),
        'referral_details': indicacao[:255],
        'cancelado': _texto(registro, 'CANCELADO').upper() == 'S',
        'anotacoes': anotacoes,
        'telefones': telefones(registro),
        'email': _texto(registro, 'EMAIL').strip().lower()[:254],
        'responsavel': normalizar_nome(_texto(registro, 'RESPONSAVEL'))[:255],
        'responsavel_parentesco': _texto(registro, 'RESPONSAVEL_PAR')[:100],
    }
    if not ficha['birth_date']:
        # `Patient.clean()` exige data de nascimento **ou** o motivo de ela
        # faltar. O motivo escrito é melhor que o campo vazio: diz à
        # secretária o que perguntar quando o paciente aparecer.
        ficha['birth_date_unknown_reason'] = (
            'Não constava no sistema anterior; a confirmar no próximo atendimento.'
        )
    return ficha
