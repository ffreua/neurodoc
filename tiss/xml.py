"""A mensagem `ENVIO_LOTE_GUIAS`, escrita a partir do snapshot das guias.

## Uma árvore, sete versões — com as diferenças medidas, não supostas

As árvores de `ctm_consultaGuia` e `ctm_sp-sadtGuia` foram extraídas dos
sete XSDs oficiais (`tiss/xsd/`, 30/10/2026) e comparadas versão a versão.
O envelope (`cabecalho`, `prestadorParaOperadora/loteGuias`, `epilogo`) é
igual em todas. Nas guias, o que muda é pouco e está todo aqui:

- **3.x**: `nomeBeneficiario` (obrigatório) e `numeroCNS` no beneficiário;
  `nomeContratado` dentro de `contratadoExecutante` e de
  `contratadoSolicitante`; não há regime de atendimento, saúde ocupacional
  nem cobertura especial;
- **4.x**: o nome do solicitante vira `nomeContratadoSolicitante`, irmão
  de `contratadoSolicitante`; o executante perde o nome; entram
  `regimeAtendimento` (obrigatório), `saudeOcupacional` e a cobertura
  especial (`coberturaEspecial` na Consulta, `indCobEspecial` na SP/SADT);
- **valores**: decimal 8,2 até a 4.01.00, 10,2 a partir da 4.02.00 —
  conferido aqui antes de escrever, para o erro dizer qual guia passou.

O domínio de cada código já foi conferido na guia contra o XSD da versão
(`guias.pendencias`); o arquivo pronto é validado de novo, **pelos bytes**,
contra o mesmo XSD (`versoes.validar`). Nenhum campo incompatível é
descartado em silêncio: o que não cabe na versão vira recusa com a guia e
o campo.

## O hash do epílogo

Componente Organizacional 202609, seção "HASH MD-5" (p.48-49): MD5, em
hexadecimal, da **concatenação do conteúdo das tags**, sem os nomes dos
elementos nem dos atributos, lidos da esquerda para a direita, de forma
literal, em ISO-8859-1. O texto oficial não diz três coisas, e a decisão
de cada uma está aqui:

- o próprio `<hash>` fica de fora (ele é o resultado) — e, com ele, o
  epílogo inteiro;
- o hexadecimal sai em **minúsculas**, como o `hexdigest` e como o exemplo
  da própria ANS;
- o arquivo é escrito **sem indentação**: não há espaço entre as tags, e
  por isso "só o conteúdo das folhas" e "todo nó de texto" dão o mesmo
  número — a ambiguidade não tem onde aparecer.

Só o validador de uma operadora real confirma; até lá, é a leitura mais
literal do texto, com vetores em `check_tiss_lotes`.

## Texto em ISO-8859-1

O arquivo é declarado ISO-8859-1, como os XSDs. Caractere fora dele (o
travessão, as aspas tipográficas que o celular insere) é trocado pelo
equivalente simples antes de escrever; o que não tem equivalente sai sem o
diacrítico. Espaços em sequência e quebras de linha viram um espaço: o
hash conta cada caractere, invisível ou não.
"""

import hashlib
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal

from lxml import etree

from . import versoes
from .models import UF_IBGE, IdentificacaoNaOperadora, TipoContratadoSolicitante, TipoGuia

NS = versoes.NAMESPACE
GERADOR = 'NeuroDoc TISS 1'

_TROCAS = {
    '–': '-', '—': '-', '‒': '-', '−': '-', '‘': "'", '’': "'",
    '‚': "'", '“': '"', '”': '"', '„': '"', '…': '...', ' ': ' ',
    '•': '-', '·': '.',
}


class XmlInvalido(Exception):
    """A guia não cabe na versão. Mensagem em português, com a guia e o campo."""


def latin1(texto):
    """O texto como a mensagem pode levar: ISO-8859-1, espaços simples."""
    texto = ' '.join(str(texto or '').split())
    saida = []
    for c in texto:
        c = _TROCAS.get(c, c)
        try:
            c.encode('latin-1')
            saida.append(c)
        except UnicodeEncodeError:
            base = unicodedata.normalize('NFKD', c).encode('latin-1', 'ignore').decode('latin-1')
            saida.append(base)
    return ''.join(saida)


def hash_tiss(raiz):
    """MD5 do conteúdo das tags, em ordem, sem o epílogo — ver o topo do módulo."""
    partes = []
    for el in raiz.iter():
        if not isinstance(el.tag, str):
            continue
        nome = etree.QName(el).localname
        if nome == 'epilogo' or any(etree.QName(a).localname == 'epilogo' for a in el.iterancestors()):
            continue
        if el.text:
            partes.append(el.text)
        if el.tail and el.getparent() is not None:
            partes.append(el.tail)
    return hashlib.md5(''.join(partes).encode('latin-1')).hexdigest()


# ------------------------------------------------------------------ escrita

class _Escritor:
    def __init__(self, versao, numero_guia=''):
        self.v = versoes.versao(versao)
        self.versao3 = self.v.codigo.startswith('3')
        self.decimal_8 = self.v.codigo in {'3.04.00', '3.05.00', '4.00.00', '4.00.01', '4.01.00'}
        self.guia = numero_guia

    def el(self, pai, nome, valor=None):
        filho = etree.SubElement(pai, f'{{{NS}}}{nome}')
        if valor is not None:
            filho.text = valor
        return filho

    def texto(self, pai, nome, valor, maximo, obrigatorio=False):
        valor = latin1(valor)
        if not valor:
            if obrigatorio:
                raise XmlInvalido(f'Guia {self.guia}: o campo {nome} é obrigatório e está vazio.')
            return None
        if len(valor) > maximo:
            raise XmlInvalido(f'Guia {self.guia}: {nome} passa de {maximo} caracteres.')
        return self.el(pai, nome, valor)

    def data(self, pai, nome, iso, obrigatorio=False):
        if not iso:
            if obrigatorio:
                raise XmlInvalido(f'Guia {self.guia}: a data {nome} é obrigatória e está vazia.')
            return None
        return self.el(pai, nome, date.fromisoformat(str(iso)[:10]).isoformat())

    def hora(self, pai, nome, iso):
        if not iso:
            return None
        return self.el(pai, nome, time.fromisoformat(str(iso)).strftime('%H:%M:%S'))

    def valor(self, pai, nome, quantia, digitos=None):
        q = Decimal(str(quantia)).quantize(Decimal('0.01'))
        teto = Decimal('999999.99') if (digitos or (8 if self.decimal_8 else 10)) == 8 else Decimal('99999999.99')
        if q > teto:
            raise XmlInvalido(
                f'Guia {self.guia}: {nome} de R$ {q} passa do limite da versão {self.v.codigo} (R$ {teto}).'
            )
        return self.el(pai, nome, f'{q:.2f}')


def _contratado(w, pai, identificacao, documento, nome_contratado=None):
    """`ct_contratadoDados`: código na operadora, CPF ou CNPJ (o `choice`)."""
    if identificacao == IdentificacaoNaOperadora.CNPJ:
        w.texto(pai, 'cnpjContratado', documento, 14, obrigatorio=True)
    elif identificacao == IdentificacaoNaOperadora.CPF:
        w.texto(pai, 'cpfContratado', documento, 11, obrigatorio=True)
    else:
        w.texto(pai, 'codigoPrestadorNaOperadora', documento, 14, obrigatorio=True)
    if nome_contratado is not None and w.versao3:
        w.texto(pai, 'nomeContratado', nome_contratado, 70, obrigatorio=True)


def _id_do_prestador(snap):
    cred = snap['credenciamento']
    if cred['identificacao'] == IdentificacaoNaOperadora.CODIGO:
        return cred['identificacao'], cred['codigo']
    return cred['identificacao'], snap['prestador']['documento']


def _profissional(w, pai, prof, nome_tag='nomeProfissional', conselho_tag='conselhoProfissional'):
    if prof is None:
        raise XmlInvalido(f'Guia {w.guia}: falta o profissional.')
    w.texto(pai, nome_tag, prof['nome'], 70, obrigatorio=(nome_tag == 'nomeProf'))
    w.el(pai, conselho_tag, prof['conselho'])
    w.texto(pai, 'numeroConselhoProfissional', prof['numero'], 15, obrigatorio=True)
    w.el(pai, 'UF', UF_IBGE[prof['uf']])
    w.el(pai, 'CBOS', prof['cbo'])


def _beneficiario(w, pai, snap):
    b = snap['beneficiario']
    dados = w.el(pai, 'dadosBeneficiario')
    w.texto(dados, 'numeroCarteira', b['carteira'], 20, obrigatorio=True)
    w.el(dados, 'atendimentoRN', 'S' if b.get('atendimento_rn') else 'N')
    if w.versao3:
        w.texto(dados, 'nomeBeneficiario', b['nome'], 70, obrigatorio=True)


def _guia_consulta(w, pai, snap):
    g = snap['guia']
    raiz = w.el(pai, 'guiaConsulta')
    cab = w.el(raiz, 'cabecalhoConsulta')
    w.el(cab, 'registroANS', snap['operadora']['registro_ans'])
    w.texto(cab, 'numeroGuiaPrestador', g['numero_prestador'], 20, obrigatorio=True)
    w.texto(raiz, 'numeroGuiaOperadora', g['numero_operadora'], 20)
    w.texto(raiz, 'ausenciaCodValidacao', g['ausencia_cod_validacao'], 2)
    w.texto(raiz, 'codValidacao', g['cod_validacao'], 10)
    _beneficiario(w, raiz, snap)
    exe = w.el(raiz, 'contratadoExecutante')
    identificacao, documento = _id_do_prestador(snap)
    _contratado(w, exe, identificacao, documento, snap['prestador']['nome'])
    w.texto(exe, 'CNES', snap['prestador']['cnes'], 7, obrigatorio=True)
    _profissional(w, w.el(raiz, 'profissionalExecutante'), snap['executante'])
    w.el(raiz, 'indicacaoAcidente', g['indicacao_acidente'])
    atend = w.el(raiz, 'dadosAtendimento')
    if not w.versao3:
        w.texto(atend, 'coberturaEspecial', g['cobertura_especial'], 2)
        w.el(atend, 'regimeAtendimento', g['regime_atendimento'] or '01')
        w.texto(atend, 'saudeOcupacional', g['saude_ocupacional'], 2)
    itens = snap['itens']
    if len(itens) != 1:
        raise XmlInvalido(f'Guia {w.guia}: a guia de Consulta tem um procedimento só.')
    item = itens[0]
    w.data(atend, 'dataAtendimento', item['data'], obrigatorio=True)
    w.texto(atend, 'tipoConsulta', g['tipo_consulta'], 1, obrigatorio=True)
    proc = w.el(atend, 'procedimento')
    w.el(proc, 'codigoTabela', item['tabela'])
    w.texto(proc, 'codigoProcedimento', item['codigo'], 10, obrigatorio=True)
    w.valor(proc, 'valorProcedimento', item['valor_total'])
    w.texto(raiz, 'observacao', g['observacao'], 500)


def _guia_sadt(w, pai, snap):
    g = snap['guia']
    raiz = w.el(pai, 'guiaSP-SADT')
    cab = w.el(raiz, 'cabecalhoGuia')
    w.el(cab, 'registroANS', snap['operadora']['registro_ans'])
    w.texto(cab, 'numeroGuiaPrestador', g['numero_prestador'], 20, obrigatorio=True)
    w.texto(cab, 'guiaPrincipal', g['guia_principal'], 20)
    if g['data_autorizacao']:
        aut = w.el(raiz, 'dadosAutorizacao')
        w.texto(aut, 'numeroGuiaOperadora', g['numero_operadora'], 20)
        w.data(aut, 'dataAutorizacao', g['data_autorizacao'], obrigatorio=True)
        w.texto(aut, 'senha', g['senha'], 20)
        w.data(aut, 'dataValidadeSenha', g['validade_senha'])
        w.texto(aut, 'ausenciaCodValidacao', g['ausencia_cod_validacao'], 2)
        w.texto(aut, 'codValidacao', g['cod_validacao'], 10)
    elif g['senha'] or g['numero_operadora'] or g['cod_validacao']:
        # O XSD só aceita senha e número da operadora dentro da autorização,
        # que exige a data: sem ela, o dado seria descartado em silêncio.
        raise XmlInvalido(f'Guia {w.guia}: senha ou nº da operadora sem a data da autorização.')
    _beneficiario(w, raiz, snap)

    sol = w.el(raiz, 'dadosSolicitante')
    contratado = w.el(sol, 'contratadoSolicitante')
    tipo = g['contratado_solicitante_tipo']
    if tipo == TipoContratadoSolicitante.PROPRIO:
        identificacao, documento = _id_do_prestador(snap)
        nome = snap['prestador']['nome']
    else:
        identificacao = {
            TipoContratadoSolicitante.CODIGO: IdentificacaoNaOperadora.CODIGO,
            TipoContratadoSolicitante.CNPJ: IdentificacaoNaOperadora.CNPJ,
            TipoContratadoSolicitante.CPF: IdentificacaoNaOperadora.CPF,
        }[tipo]
        documento, nome = g['contratado_solicitante_codigo'], g['contratado_solicitante_nome']
    _contratado(w, contratado, identificacao, documento, nome)
    if not w.versao3:
        w.texto(sol, 'nomeContratadoSolicitante', nome, 70, obrigatorio=True)
    _profissional(w, w.el(sol, 'profissionalSolicitante'), snap['solicitante'])

    pedido = w.el(raiz, 'dadosSolicitacao')
    w.data(pedido, 'dataSolicitacao', g['data_solicitacao'])
    w.el(pedido, 'caraterAtendimento', g['carater_atendimento'])
    w.texto(pedido, 'indicacaoClinica', g['indicacao_clinica'], 500)
    if not w.versao3:
        w.texto(pedido, 'indCobEspecial', g['cobertura_especial'], 2)

    exe = w.el(raiz, 'dadosExecutante')
    contratado = w.el(exe, 'contratadoExecutante')
    identificacao, documento = _id_do_prestador(snap)
    _contratado(w, contratado, identificacao, documento, snap['prestador']['nome'])
    w.texto(exe, 'CNES', snap['prestador']['cnes'], 7, obrigatorio=True)

    atend = w.el(raiz, 'dadosAtendimento')
    w.texto(atend, 'tipoAtendimento', g['tipo_atendimento'], 2, obrigatorio=True)
    w.el(atend, 'indicacaoAcidente', g['indicacao_acidente'])
    w.texto(atend, 'tipoConsulta', g['tipo_consulta'], 1)
    w.texto(atend, 'motivoEncerramento', g['motivo_encerramento'], 2)
    if not w.versao3:
        w.el(atend, 'regimeAtendimento', g['regime_atendimento'] or '01')
        w.texto(atend, 'saudeOcupacional', g['saude_ocupacional'], 2)

    executante = snap['executante']
    procs = w.el(raiz, 'procedimentosExecutados')
    total = Decimal('0.00')
    for item in snap['itens']:
        p = w.el(procs, 'procedimentoExecutado')
        w.el(p, 'sequencialItem', str(item['sequencial']))
        w.data(p, 'dataExecucao', item['data'], obrigatorio=True)
        w.hora(p, 'horaInicial', item['hora_inicial'])
        w.hora(p, 'horaFinal', item['hora_final'])
        dados = w.el(p, 'procedimento')
        w.el(dados, 'codigoTabela', item['tabela'])
        w.texto(dados, 'codigoProcedimento', item['codigo'], 10, obrigatorio=True)
        w.texto(dados, 'descricaoProcedimento', item['descricao'], 150, obrigatorio=True)
        w.el(p, 'quantidadeExecutada', str(item['quantidade']))
        w.texto(p, 'viaAcesso', item['via_acesso'], 1)
        w.texto(p, 'tecnicaUtilizada', item['tecnica'], 1)
        w.el(p, 'reducaoAcrescimo', f"{Decimal(item['fator']):.2f}")
        w.valor(p, 'valorUnitario', item['valor_unitario'])
        w.valor(p, 'valorTotal', item['valor_total'])
        # A equipe identifica o executante pelo CPF (`codProfissional`). Sem
        # CPF no cadastro do profissional, ela fica de fora — é opcional no
        # XSD —, e o executante segue identificado pelo contratado.
        if executante and executante.get('cpf'):
            eq = w.el(p, 'equipeSadt')
            cod = w.el(eq, 'codProfissional')
            w.el(cod, 'cpfContratado', executante['cpf'])
            _profissional(w, eq, executante, nome_tag='nomeProf', conselho_tag='conselho')
        total += Decimal(item['valor_total'])
    if not snap['itens']:
        raise XmlInvalido(f'Guia {w.guia}: SP/SADT sem procedimento realizado.')
    w.texto(raiz, 'observacao', g['observacao'], 500)
    valores = w.el(raiz, 'valorTotal')
    w.valor(valores, 'valorProcedimentos', total, digitos=10)
    w.valor(valores, 'valorTotalGeral', total, digitos=10)


def mensagem_lote(*, versao, tipo, numero_lote, transacao_em, prestador_id, registro_ans, snapshots):
    """Os bytes do arquivo, em ISO-8859-1, com o hash no epílogo.

    `prestador_id` é `(identificacao, documento)` do credenciamento;
    `transacao_em` é o instante reservado na criação do lote (hora local).
    Levanta `XmlInvalido` com a guia e o campo quando algo não cabe na
    versão. Não valida contra o XSD — quem chama valida os bytes.
    """
    w = _Escritor(versao)
    if not 1 <= len(snapshots) <= 100:
        raise XmlInvalido('Um lote tem de 1 a 100 guias.')
    raiz = etree.Element(f'{{{NS}}}mensagemTISS', nsmap={'ans': NS})
    cab = w.el(raiz, 'cabecalho')
    ident = w.el(cab, 'identificacaoTransacao')
    w.el(ident, 'tipoTransacao', 'ENVIO_LOTE_GUIAS')
    w.texto(ident, 'sequencialTransacao', numero_lote, 12, obrigatorio=True)
    instante = transacao_em if isinstance(transacao_em, datetime) else datetime.fromisoformat(transacao_em)
    w.el(ident, 'dataRegistroTransacao', instante.date().isoformat())
    w.el(ident, 'horaRegistroTransacao', instante.strftime('%H:%M:%S'))
    origem = w.el(w.el(cab, 'origem'), 'identificacaoPrestador')
    identificacao, documento = prestador_id
    tag = {IdentificacaoNaOperadora.CNPJ: 'CNPJ', IdentificacaoNaOperadora.CPF: 'CPF'}.get(
        identificacao, 'codigoPrestadorNaOperadora')
    w.texto(origem, tag, documento, 14, obrigatorio=True)
    w.el(w.el(cab, 'destino'), 'registroANS', registro_ans)
    w.el(cab, 'Padrao', w.v.codigo)

    lote = w.el(w.el(raiz, 'prestadorParaOperadora'), 'loteGuias')
    w.texto(lote, 'numeroLote', numero_lote, 12, obrigatorio=True)
    guias = w.el(lote, 'guiasTISS')
    for snap in snapshots:
        if snap.get('versao') != w.v.codigo:
            raise XmlInvalido(f"Guia {snap['guia']['numero_prestador']}: fechada na versão "
                              f"{snap.get('versao')}, e o lote é {w.v.codigo}.")
        if snap['operadora']['registro_ans'] != registro_ans:
            raise XmlInvalido(f"Guia {snap['guia']['numero_prestador']}: de outra operadora.")
        w.guia = snap['guia']['numero_prestador']
        if tipo == TipoGuia.CONSULTA:
            _guia_consulta(w, guias, snap)
        else:
            _guia_sadt(w, guias, snap)
    w.guia = ''

    valor_hash = hash_tiss(raiz)
    w.el(w.el(raiz, 'epilogo'), 'hash', valor_hash)
    # Declaração escrita à mão, com aspas duplas: a do lxml sai com aspas
    # simples, que é XML válido e que validador de portal às vezes recusa.
    corpo = etree.tostring(raiz, xml_declaration=False, encoding='ISO-8859-1', pretty_print=False)
    dados = b'<?xml version="1.0" encoding="ISO-8859-1"?>' + corpo
    return dados, valor_hash
