"""As versões do padrão TISS que este NeuroDoc sabe gerar, e os XSDs de cada uma.

## Por que sete versões, e por que elas não são iguais

As operadoras não migram juntas. Numa clínica real, em outubro de 2026, a
Unimed Belém recebia 4.00.00 e a Hapvida estava configurada em 3.04.00 no
sistema de faturamento que ela usava. A ANS publica a 4.03.00 como vigente
(Componente Organizacional 202609, §141) e diz que, havendo mais de uma
vigente, vale a acordada entre as partes (§206).

**Trocar a string da versão não é suporte multiversão.** Os XSDs divergem
em estrutura e em domínio: `dm_tipoAtendimento` tem o código `05` (exame
ambulatorial) até a 4.00.01 e não o tem a partir da 4.01.00; nome do
beneficiário e CNS saíram da mensagem na 4.00.00; o CNPJ virou
alfanumérico na 4.03.00. Cada versão tem o seu pacote aqui, e cada XML é
validado contra **o pacote da versão que declara**.

## Vigente na ANS, histórica, e aceita pela operadora

São três informações diferentes, e a tela mostra as três:

- **`vigente_ans`**: a versão consta do `dm_versao` da 4.03.00 (4.00.00 a
  4.03.00) e da tabela de competências da ANS de set/2026.
- **histórica** (3.04.00, 3.05.00): não consta de nenhuma competência desde
  mai/2023. O XML de cobrança só sai quando o credenciamento registra que
  **aquela operadora aceita** a versão — quem declarou, quando e por quê
  (`Credenciamento.aceite_*`). Sem isso, é inspeção.
- **aceita pela operadora**: só a homologação com ela prova; o sistema não
  afirma.

## Segurança do parser

Os XSDs são carregados **depois** de conferir o SHA-256 de cada arquivo
contra `xsd/MANIFESTO.json` — arquivo trocado no disco não vira regra de
validação. E todo parse é sem rede, sem DTD externo e sem expandir
entidade: um XML de entrada com `<!DOCTYPE` é recusado antes de qualquer
coisa (XXE). Fontes e hashes: `docs/tiss/REVISAO_SPRINT1.md` §2.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PASTA_XSD = Path(__file__).resolve().parent / 'xsd'

#: Namespace de todas as versões, de 3.04.00 a 4.03.00 (conferido em cada
#: `targetNamespace`). O anexo que deu origem ao módulo usava
#: `.../padraotiss/schemas`, que não é este — e foi reprovado por isso.
NAMESPACE = 'http://www.ans.gov.br/padroes/tiss/schemas'


@dataclass(frozen=True)
class Versao:
    codigo: str
    pasta: str
    vigente_ans: bool

    @property
    def principal(self):
        return f'tissV{self.codigo.replace(".", "_")}.xsd'

    @property
    def tipos_simples(self):
        return f'tissSimpleTypesV{self.codigo.replace(".", "_")}.xsd'

    @property
    def historica(self):
        return not self.vigente_ans

    @property
    def rotulo(self):
        return self.codigo if self.vigente_ans else f'{self.codigo} (histórica)'


#: Da mais nova para a mais antiga, que é a ordem do menu.
VERSOES = {
    v.codigo: v for v in (
        Versao('4.03.00', '040300', True),
        Versao('4.02.00', '040200', True),
        Versao('4.01.00', '040100', True),
        Versao('4.00.01', '040001', True),
        Versao('4.00.00', '040000', True),
        Versao('3.05.00', '030500', False),
        Versao('3.04.00', '030400', False),
    )
}

#: A versão sugerida para credenciamento novo: a vigente na ANS.
VERSAO_ATUAL = '4.03.00'


class VersaoDesconhecida(Exception):
    pass


class PacoteAdulterado(Exception):
    """Um XSD no disco não bate com o manifesto. Mensagem para quem opera."""


class XmlRecusado(Exception):
    """XML com DTD/entidade, ou que nem chega a ser XML. Mensagem para a tela."""


def versao(codigo):
    """Aceita `4.03.00` e `04.03.00` — o rótulo da ANS varia entre documentos."""
    codigo = (codigo or '').strip()
    if re.fullmatch(r'0\d\.\d{2}\.\d{2}', codigo):
        codigo = codigo[1:]
    try:
        return VERSOES[codigo]
    except KeyError:
        raise VersaoDesconhecida(f'Versão TISS desconhecida: {codigo!r}.') from None


def escolhas():
    return [(v.codigo, v.rotulo) for v in VERSOES.values()]


def _parser():
    from lxml import etree

    return etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False,
        dtd_validation=False, huge_tree=False, remove_comments=False,
    )


@lru_cache(maxsize=1)
def _manifesto():
    return json.loads((PASTA_XSD / 'MANIFESTO.json').read_text(encoding='utf-8'))


def conferir_pacote(codigo):
    """Confere o SHA-256 de cada arquivo do pacote. Levanta `PacoteAdulterado`."""
    v = versao(codigo)
    esperado = _manifesto().get(v.pasta) or {}
    pasta = PASTA_XSD / v.pasta
    presentes = {p.name for p in pasta.glob('*.xsd')}
    if presentes != set(esperado):
        raise PacoteAdulterado(f'Pacote {v.codigo}: arquivos diferentes do manifesto.')
    for nome, sha in esperado.items():
        if hashlib.sha256((pasta / nome).read_bytes()).hexdigest() != sha:
            raise PacoteAdulterado(f'Pacote {v.codigo}: {nome} não bate com o manifesto.')
    return v


@lru_cache(maxsize=None)
def schema(codigo):
    """O `XMLSchema` da versão, carregado uma vez por processo."""
    from lxml import etree

    v = conferir_pacote(codigo)
    arvore = etree.parse(str(PASTA_XSD / v.pasta / v.principal), _parser())
    return etree.XMLSchema(arvore)


@lru_cache(maxsize=None)
def _tipos_simples(codigo):
    v = versao(codigo)
    return (PASTA_XSD / v.pasta / v.tipos_simples).read_text(encoding='latin-1')


def dominio(codigo, tipo):
    """Os valores de um `simpleType` enumerado do XSD da versão (`dm_UF`, `dm_CBOS`...).

    Lido do próprio XSD, e não de lista escrita à mão: o domínio muda de
    versão para versão (a 4.03.00 tem 172 CBOs; a 3.04.00, 147), e uma lista
    nossa envelheceria em silêncio. Devolve lista vazia se o tipo não existe
    naquela versão.
    """
    texto = _tipos_simples(codigo)
    m = re.search(r'<simpleType name="' + re.escape(tipo) + r'">(.*?)</simpleType>', texto, re.S)
    if not m:
        return []
    return re.findall(r'<enumeration value="([^"]*)"', m.group(1))


def carregar_xml(dados):
    """Bytes → árvore, recusando DTD, entidade e o que não for XML."""
    from lxml import etree

    if not isinstance(dados, (bytes, bytearray)):
        raise XmlRecusado('O arquivo precisa ser lido como bytes.')
    maiusculo = bytes(dados).upper()
    if b'<!DOCTYPE' in maiusculo or b'<!ENTITY' in maiusculo:
        raise XmlRecusado('XML com DOCTYPE ou ENTITY não é aceito.')
    try:
        return etree.fromstring(bytes(dados), _parser())
    except etree.XMLSyntaxError as exc:
        raise XmlRecusado(f'O arquivo não é um XML válido: {exc.msg}.') from None


def validar(codigo, dados):
    """Valida os **bytes finais** contra o XSD da versão. Devolve a lista de erros.

    Lista vazia = válido no XSD. Isso não é aceito pela operadora, nem
    validado pelas regras de negócio — são as outras etapas.
    """
    doc = carregar_xml(dados)
    sch = schema(codigo)
    if sch.validate(doc):
        return []
    return [f'linha {e.line}: {e.message}' for e in sch.error_log]
