"""A receita eletrônica do SNCR: itens, classificação e limites.

Sprint 2 da integração (`docs/sncr/`). Este módulo decide **se** uma
receita pode sair como Receita de Controle Especial (RCE) ou Receita
Sujeita à Retenção (RET) eletrônica e devolve o conteúdo pronto para o
documento. Nada aqui gera PDF nem fala com a Anvisa.

**Por que a lista oficial e não a tarja da CMED** (decisão D7): a tarja é
dado de preço; quem diz que receituário a substância pede é o Anexo I da
Portaria SVS/MS 344/1998, importado em `catalogs.controlados`. A tarja
continua só como sugestão na busca da receita impressa.

**As regras, com a fonte de cada uma** (texto consolidado da Portaria 344
no Anvisalegis, lido em 2026-10-21):

- art. 55 — a RCE serve às listas **C1** e **C5** e aos **adendos** das
  listas A1, A2 e B1 (tramadol e codeína em dose baixa, por exemplo). Fora
  do adendo, A e B pedem Notificação de Receita, fora do escopo (D5);
- art. 57 — no máximo **3 substâncias da lista C1** por receita. Cada
  medicamento sai na **sua folha, com número SNCR próprio** (decisão I12):
  cada folha é uma receita, e o limite vale **por folha** — só um
  medicamento com quatro substâncias da C1 o ultrapassa;
- art. 52, § 1º — a quantidade em **algarismos e por extenso**;
- política do proprietário — no máximo **3 medicamentos** por emissão
  (`LIMITE_MEDICAMENTOS`), uma folha cada;
- FAQ de Integração P48 — controlado **nunca** em receita simples ou RET.

**O que o programa não decide** (docstring de `catalogs.controlados`): o
adendo depende de dose e de forma, e uma marca que a CMED não conhece não
prova que o medicamento é livre. Nos dois casos a receita exige a
confirmação do médico (`classificacao_confirmada`), gravada com o
documento — nunca uma escolha silenciosa.
"""

import re

from catalogs import controlados
from catalogs.portaria344 import normalizar

from .models import TipoReceita

SNCR_RCE = 'sncr_rce'
SNCR_RET = 'sncr_ret'

FORMATOS = {SNCR_RCE: TipoReceita.RCE, SNCR_RET: TipoReceita.RET}

FORMAT_CHOICES = (
    (SNCR_RCE, 'Controle especial — eletrônica com numeração do SNCR (Anvisa)'),
    (SNCR_RET, 'Sujeita à retenção — eletrônica com numeração do SNCR (antimicrobiano, GLP-1)'),
)

#: Política do proprietário (2026-10-21): uma emissão de medicamentos
#: controlados não leva mais de três medicamentos — cada um na sua folha,
#: com número SNCR próprio (decisão I12, 2026-10-21). Vale para as duas
#: receitas eletrônicas; a regra da norma por receita (art. 57) é conferida
#: por folha, à parte.
LIMITE_MEDICAMENTOS = 3

#: Portaria 344, art. 57: no máximo 3 substâncias da lista C1 por receita.
LIMITE_SUBSTANCIAS_C1 = 3

CAMPOS_DO_ITEM = ('nome', 'concentracao', 'forma', 'quantidade', 'posologia')

ROTULOS_DO_ITEM = {
    'nome': 'Medicamento ou substância',
    'concentracao': 'Concentração',
    'forma': 'Forma farmacêutica',
    'quantidade': 'Quantidade',
    'posologia': 'Posologia',
}

#: Tamanho máximo de cada campo: o modelo da Anvisa é de uma folha, e três
#: itens com posologia longa não cabem nela. O gerador ainda confere a
#: altura real; isto barra antes, com a mensagem do campo.
TAMANHO_MAXIMO = {'nome': 120, 'concentracao': 60, 'forma': 60, 'quantidade': 60, 'posologia': 300}

#: Os nomes dos campos no formulário: `item1_nome`, `item2_posologia`...,
#: e a marca de uso contínuo de cada item (`item1_uso_continuo`).
CAMPOS_DO_FORMULARIO = tuple(
    f'item{n}_{campo}' for n in range(1, LIMITE_MEDICAMENTOS + 1)
    for campo in CAMPOS_DO_ITEM + ('uso_continuo',)
)

#: O que o uso contínuo acrescenta à quantidade impressa. **Acrescenta, e não
#: substitui:** a Portaria 344 (art. 52, § 1º) exige a quantidade em
#: algarismos e por extenso também na receita de uso contínuo, com o limite
#: de 60 dias de tratamento (6 meses para anticonvulsivante e
#: antiparkinsoniano); na RET, a RDC 471/2021 pede a indicação de uso
#: contínuo com a quantidade para cada 30 dias. Uma receita só com "uso
#: contínuo", sem número, seria recusada no balcão — decisão de
#: 2026-10-29, explicada ao proprietário quando ele pediu a opção.
MARCA_USO_CONTINUO = 'uso contínuo'

#: Receituários da lista oficial que a RCE atende sem pergunta.
_RCE = 'rce'
#: Listas cujo adendo pode mandar uma preparação para a RCE (art. 55).
_LISTAS_COM_ADENDO_RCE = frozenset({'A1', 'A2', 'B1'})
_NOTIFICACOES = frozenset({
    'notificacao_a', 'notificacao_b', 'notificacao_b2', 'notificacao_retinoide', 'notificacao_talidomida',
})


class ReceitaInvalida(ValueError):
    """Recusa com a mensagem que o médico lê. Herda `ValueError` de propósito:
    as views de documento já mostram `ValueError` de `create_draft` na tela."""


# --- quantidade por extenso -------------------------------------------------

_UNIDADES = ('zero', 'um', 'dois', 'três', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove', 'dez',
             'onze', 'doze', 'treze', 'quatorze', 'quinze', 'dezesseis', 'dezessete', 'dezoito', 'dezenove')
_DEZENAS = ('', '', 'vinte', 'trinta', 'quarenta', 'cinquenta', 'sessenta', 'setenta', 'oitenta', 'noventa')
_CENTENAS = ('', 'cento', 'duzentos', 'trezentos', 'quatrocentos', 'quinhentos', 'seiscentos',
             'setecentos', 'oitocentos', 'novecentos')


def _ate_mil(n):
    if n < 20:
        return _UNIDADES[n]
    if n < 100:
        dezena, unidade = divmod(n, 10)
        return _DEZENAS[dezena] + (f' e {_UNIDADES[unidade]}' if unidade else '')
    if n == 100:
        return 'cem'
    centena, resto = divmod(n, 100)
    return _CENTENAS[centena] + (f' e {_ate_mil(resto)}' if resto else '')


def por_extenso(n):
    """O inteiro por extenso, em português, de 0 a 999.999."""
    if not 0 <= n < 1_000_000:
        raise ValueError(n)
    milhar, resto = divmod(n, 1000)
    if not milhar:
        return _ate_mil(resto)
    parte = 'mil' if milhar == 1 else f'{_ate_mil(milhar)} mil'
    if not resto:
        return parte
    # "mil e cem", "mil e vinte", mas "mil duzentos e trinta".
    ligacao = ' e ' if resto < 100 or resto % 100 == 0 else ' '
    return parte + ligacao + _ate_mil(resto)


_INTEIRO = re.compile(r'(?<![\d,.])(\d{1,6})(?![\d,.])')


def quantidade_com_extenso(texto):
    """"60 comprimidos" vira "60 (sessenta) comprimidos".

    Portaria 344, art. 52, § 1º: a quantidade da RCE em algarismos **e**
    por extenso. O médico escreve o número; o extenso é posto aqui, uma vez,
    e gravado no documento — o que ele revisa no rascunho é o que vai
    assinado. Se o texto já traz um parêntese logo após o número, ele é
    respeitado. Sem número inteiro, a quantidade é recusada.
    """
    texto = ' '.join((texto or '').split())
    achado = _INTEIRO.search(texto)
    if not achado:
        raise ReceitaInvalida(
            'A quantidade precisa de um número em algarismos (por exemplo, "60 comprimidos"); '
            'o NeuroDoc acrescenta o número por extenso, como a Portaria 344 exige.'
        )
    depois = texto[achado.end():].lstrip()
    if depois.startswith('('):
        return texto
    extenso = por_extenso(int(achado.group(1)))
    if _feminino(depois.split(' ')[0] if depois else ''):
        extenso = _no_feminino(extenso)
    return f'{texto[:achado.end()]} ({extenso}){texto[achado.end():]}'


#: Terminações de substantivo feminino que aparecem em quantidade de
#: receita: caixa(s), cápsula(s), ampola(s), gota(s), unidade(s),
#: drágea(s), bisnaga(s), embalagem(ns). "1 (um) caixa" sairia errado no
#: documento assinado; "comprimidos" e "frascos" seguem no masculino.
_FEMININO = re.compile(r'(as?|ades?|agem|agens)$')


def _feminino(palavra):
    return bool(_FEMININO.search(palavra.lower()))


def _no_feminino(extenso):
    palavras = extenso.split(' ')
    trocas = {'um': 'uma', 'dois': 'duas'}
    return ' '.join(
        trocas.get(p, p[:-5] + 'entas' if p.endswith('entos') else p) for p in palavras
    )


# --- classificação ------------------------------------------------------------

def _substancias_pela_cmed(nome):
    """As substâncias de um nome comercial, pela tabela da CMED.

    "Rivotril" não contém "clonazepam": sem esta consulta, toda marca
    passaria como "não encontrada na lista". Casa só o nome do **produto**
    pela primeira palavra, para "Rivotril" não achar o que tem "rivotril"
    no meio da apresentação.
    """
    from catalogs.models import CatalogSystem, MedicationProduct
    from catalogs.selectors import active_release

    alvo = re.sub(r'[^A-Z0-9 ]', ' ', normalizar(nome)).split()
    if not alvo or len(alvo[0]) < 4:
        return []
    release = active_release(CatalogSystem.CMED)
    if release is None:
        return []
    primeiro = alvo[0]
    substancias = set()
    for produto, substancia in (
        MedicationProduct.objects.filter(release=release, active=True, search_text__contains=primeiro)
        .values_list('product', 'substance')[:400]
    ):
        palavras = re.sub(r'[^A-Z0-9 ]', ' ', normalizar(produto)).split()
        if palavras and palavras[0] == primeiro:
            substancias.add(substancia)
    return sorted(substancias)


def _no_adendo_rce(substancia, lista):
    """O adendo da lista manda alguma preparação desta substância para a RCE?"""
    if lista.code not in _LISTAS_COM_ADENDO_RCE:
        return False
    adendo = normalizar(lista.adendo or '')
    nome = normalizar(re.split(r'\s*\(', substancia.name)[0]).strip()
    return bool(nome) and nome in adendo and 'CONTROLE ESPECIAL' in adendo


def classificar_item(nome):
    """O que a lista oficial diz do medicamento do item.

    Devolve um dicionário com `origem` (`nome`, `cmed` ou `nenhuma`) e
    `substancias`, cada uma com `nome`, `lista`, `receituario` e
    `adendo_rce` (verdadeiro quando o adendo da lista pode mandá-la para a
    RCE). Lista vazia não prova que o medicamento é livre.
    """
    achados = controlados.classificar(nome)
    origem = 'nome'
    if not achados:
        achados = []
        for substancia in _substancias_pela_cmed(nome):
            for par in controlados.classificar(substancia):
                if par not in achados:
                    achados.append(par)
        origem = 'cmed' if achados else 'nenhuma'
    return {
        'origem': origem,
        'substancias': [
            {
                'nome': substancia.name,
                'lista': lista.code,
                'receituario': lista.receituario,
                'adendo_rce': _no_adendo_rce(substancia, lista),
            }
            for substancia, lista in achados
        ],
    }


# --- montagem e validação -------------------------------------------------------

def itens_do_formulario(campos):
    """Os itens preenchidos, na ordem. Linha toda em branco é ignorada;
    linha pela metade é erro — o modelo da Anvisa pede os cinco campos."""
    alem = sorted({
        int(m.group(1)) for chave, valor in campos.items()
        if (m := re.match(r'^item(\d+)_', chave)) and int(m.group(1)) > LIMITE_MEDICAMENTOS
        and str(valor or '').strip()
    })
    if alem:
        # O formulário só tem três linhas; um quarto item só chega montado à
        # mão. Recusar, e não ignorar: ignorar emitiria a receita sem um
        # medicamento que o médico escreveu.
        raise ReceitaInvalida(
            f'No máximo {LIMITE_MEDICAMENTOS} medicamentos por receita eletrônica. '
            'Separe os demais em outra receita.'
        )
    itens = []
    for n in range(1, LIMITE_MEDICAMENTOS + 1):
        valores = {c: ' '.join(str(campos.get(f'item{n}_{c}') or '').split()) for c in CAMPOS_DO_ITEM}
        if not any(valores.values()):
            continue
        continuo = campos.get(f'item{n}_uso_continuo') in (True, 'on', 'true', '1')
        faltando = [ROTULOS_DO_ITEM[c].lower() for c, v in valores.items() if not v]
        if faltando:
            raise ReceitaInvalida(f'Medicamento {n}: falta {", ".join(faltando)}.')
        for campo, valor in valores.items():
            if len(valor) > TAMANHO_MAXIMO[campo]:
                raise ReceitaInvalida(
                    f'Medicamento {n}: {ROTULOS_DO_ITEM[campo].lower()} com mais de '
                    f'{TAMANHO_MAXIMO[campo]} caracteres não cabe no modelo da Anvisa.'
                )
        valores['uso_continuo'] = continuo
        itens.append(valores)
    return itens


def texto_da_prescricao(itens):
    """A prescrição em texto corrido.

    Gravada em `prescription_text` para que quem já lê esse campo — a
    lista de documentos do paciente, a exportação do acervo, o contexto da
    IA — continue lendo a receita eletrônica sem saber dos itens.
    """
    linhas = []
    for n, item in enumerate(itens, start=1):
        linhas.append(
            f'{n}. {item["nome"]} — {item["concentracao"]} — {item["forma"]} — '
            f'Quantidade: {item["quantidade"]} — Posologia: {item["posologia"]}'
        )
    return '\n'.join(linhas)


def _descricao(sub):
    return f'{sub["nome"]} (lista {sub["lista"]})'


def _validar_rce(itens, classificacao, confirmada):
    controlados_no_item = []
    pendencias = []
    for n, (item, cls) in enumerate(zip(itens, classificacao), start=1):
        subs = cls['substancias']
        notificacao = [s for s in subs if s['receituario'] in _NOTIFICACOES and not s['adendo_rce']]
        proibida = [s for s in subs if s['receituario'] == 'proscrita']
        if proibida:
            raise ReceitaInvalida(
                f'Medicamento {n} ({item["nome"]}): {_descricao(proibida[0])} é de uso proibido no Brasil '
                '(Portaria 344, listas E e F).'
            )
        if notificacao:
            raise ReceitaInvalida(
                f'Medicamento {n} ({item["nome"]}): {_descricao(notificacao[0])} exige Notificação de '
                'Receita, que o NeuroDoc ainda não emite eletronicamente. Use o talonário da Notificação.'
            )
        adendo = [s for s in subs if s['receituario'] in _NOTIFICACOES and s['adendo_rce']]
        if adendo:
            pendencias.append(
                f'medicamento {n} ({item["nome"]}): {_descricao(adendo[0])} só vai para a RCE pelo adendo '
                'da lista, conforme a dose e a forma'
            )
        if any(s['receituario'] == _RCE for s in subs) or adendo:
            controlados_no_item.append(n)
        c1 = {s['nome'] for s in subs if s['lista'] == 'C1'}
        if len(c1) > LIMITE_SUBSTANCIAS_C1:
            raise ReceitaInvalida(
                f'Medicamento {n} ({item["nome"]}) tem {len(c1)} substâncias da lista C1; a Portaria 344 '
                f'(art. 57) permite no máximo {LIMITE_SUBSTANCIAS_C1} por receita.'
            )
        if not subs:
            pendencias.append(f'medicamento {n} ({item["nome"]}) não foi encontrado na lista oficial')
    if pendencias and not confirmada:
        raise ReceitaInvalida(
            'Confira a classificação antes de gerar a receita: ' + '; '.join(pendencias) + '. '
            'Se o medicamento exige mesmo a Receita de Controle Especial, marque a confirmação; '
            'se não, use a receita simples.'
        )
    if not controlados_no_item and not confirmada:
        raise ReceitaInvalida(
            'Nenhum medicamento desta receita consta das listas C1 ou C5 da Portaria 344. '
            'Use a receita simples, ou marque a confirmação se o medicamento exige a RCE.'
        )


def _validar_ret(itens, classificacao):
    for n, (item, cls) in enumerate(zip(itens, classificacao), start=1):
        controlada = [s for s in cls['substancias'] if s['receituario'] != 'sem_retencao']
        if controlada:
            raise ReceitaInvalida(
                f'Medicamento {n} ({item["nome"]}): {_descricao(controlada[0])} é controlado pela '
                'Portaria 344 e não pode sair na receita sujeita à retenção (FAQ de Integração, '
                'pergunta 48). Use a Receita de Controle Especial.'
            )


def preparar(campos, patient, confirmada=False):
    """Valida e monta o conteúdo da receita eletrônica.

    Devolve o dicionário que vai para `MedicalDocument.content_snapshot`.
    Levanta `ReceitaInvalida` com a mensagem para o médico.
    """
    from .models import Configuracao

    formato = campos.get('prescription_format')
    if formato not in FORMATOS:
        raise ReceitaInvalida('Formato de receita eletrônica desconhecido.')
    if not Configuracao.carregar().ativo:
        raise ReceitaInvalida(
            'A receita eletrônica com numeração do SNCR ainda não está ligada nesta instalação. '
            'Use a receita impressa.'
        )
    if not (patient.cpf or '').strip():
        raise ReceitaInvalida(
            'A receita eletrônica do SNCR exige o CPF do paciente. Cadastre o CPF na ficha; '
            'para paciente estrangeiro com passaporte, use por enquanto a receita impressa.'
        )
    if formato == SNCR_RCE and not (patient.street and patient.city and patient.state):
        raise ReceitaInvalida(
            'A Receita de Controle Especial exige o endereço completo do paciente (logradouro, '
            'município e UF). Complete o cadastro antes de emitir.'
        )
    itens = itens_do_formulario(campos)
    if not itens:
        raise ReceitaInvalida('Informe ao menos um medicamento.')
    if len(itens) > LIMITE_MEDICAMENTOS:
        raise ReceitaInvalida(f'No máximo {LIMITE_MEDICAMENTOS} medicamentos por receita.')
    for item in itens:
        item['quantidade'] = quantidade_com_extenso(item['quantidade'])
        if item.get('uso_continuo') and MARCA_USO_CONTINUO not in item['quantidade'].lower():
            item['quantidade'] = f'{item["quantidade"]} — {MARCA_USO_CONTINUO}'
    classificacao = [classificar_item(item['nome']) for item in itens]
    if formato == SNCR_RCE:
        _validar_rce(itens, classificacao, confirmada)
    else:
        _validar_ret(itens, classificacao)
    release = controlados.release_ativa()
    return {
        'prescription_format': formato,
        'itens': itens,
        'classificacao': classificacao,
        'classificacao_confirmada': bool(confirmada),
        'lista_oficial': release.version if release else '',
        'prescription_text': texto_da_prescricao(itens),
    }


def tipo_do_documento(document):
    """`TipoReceita` da receita eletrônica, ou `None` para qualquer outro documento."""
    if getattr(document, 'kind', None) != 'prescription':
        return None
    return FORMATOS.get((document.content_snapshot or {}).get('prescription_format'))


def eh_eletronica(document):
    return tipo_do_documento(document) is not None

