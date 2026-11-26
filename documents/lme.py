"""LME — Laudo de Solicitação, Avaliação e Autorização de Medicamento(s).

É o formulário do Componente Especializado da Assistência Farmacêutica
(CEAF) com que o paciente pede o medicamento de alto custo na farmácia do
Estado. O NeuroDoc preenche **o próprio modelo do Ministério da Saúde**, e
não um redesenho dele, pela mesma razão da receita do SNCR
(`sncr/pdf_oficial.py`): a farmácia recebe o formulário que conhece, e um
"parecido" nunca se prova igual.

**Sempre impressa, assinada à mão e carimbada** (decisão do titular,
2026-11-25). A LME não é assinada digitalmente no NeuroDoc: a tela não
oferece a assinatura e `issuance._sign_and_issue` a recusa
(`assinatura_digital_bloqueada`). O caminho é "Emitir para assinar e
carimbar"; os campos 17 (assinatura e carimbo do médico) e 23 (assinatura
de quem preencheu) ficam em branco para a caneta. Por isso também não há
QR nem envio por link: o documento em papel é entregue impresso.

**O modelo.** `documents/modelos/lme_ministerio_2026-03.pdf` é o arquivo
publicado em gov.br/saude (CEAF → publicações → `lme.pdf`), revisão de
13/03/2026, baixado em 2026-11-25. O SHA-256 está em `SHA256_MODELO`:
trocar o arquivo sem trocar a constante derruba a geração, em vez de
imprimir outro modelo em silêncio. O arquivo é um formulário do Acrobat;
o gerador tira dele os campos interativos e os botões do topo ("Salvar
como", "Limpar"...) e escreve os valores numa camada por cima da página.

**As posições saem do próprio modelo.** Cada campo interativo do PDF tem
um nome legível ("CNES", "Nome do paciente", "Selecao med 1"...) e um
retângulo; `_retangulos()` lê esses retângulos do arquivo travado. Um
modelo novo do Ministério com os mesmos nomes entra trocando só o arquivo
e o SHA-256 — e `checks/check_lme.py` falha se algum nome sumir.

**Medicamentos.** O modelo traz uma lista de sugestão (344 itens na
revisão de 2026-03), que a tela oferece enquanto se digita. **A lista não
limita nada**: o médico escreve o medicamento como quiser, porque é ele
quem sabe o que o protocolo do Ministério cobre, e a lista do arquivo fica
velha antes de o Ministério publicar outra.

**Raça/cor e CNS do paciente moram só na LME**, no conteúdo do documento,
e não no cadastro: é dado que só este formulário pede, e raça/cor é dado
pessoal sensível (LGPD, art. 5º, II) — não vale criar no cadastro de todo
paciente um campo que só a LME usa. A próxima LME do mesmo paciente
reaproveita o que a anterior registrou.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth

MODELO = Path(__file__).resolve().parent / 'modelos' / 'lme_ministerio_2026-03.pdf'
SHA256_MODELO = 'aa471d011c97ef6c7b6a7c2b25381057954019d13e4a55fc3e02e14c8d9136bc'
#: Gravado no conteúdo de cada LME, para saber em que modelo ela saiu.
VERSAO_MODELO = 'MS 2026-03'

MAX_MEDICAMENTOS = 6
MESES = 6

FONTE = 'Helvetica'
#: Do maior para o menor: o texto encolhe até caber, e abaixo do menor a
#: tela recusa — letra menor que isso não se lê no balcão da farmácia.
TAMANHO_MAXIMO = 10.0
TAMANHO_MINIMO = 6.5

RECUSA_DIGITAL = (
    'A LME é sempre impressa, assinada à mão e carimbada pelo médico: ela não é assinada '
    'digitalmente. Use “Emitir para assinar e carimbar”.'
)
MOTIVO_AUDITORIA = 'lme_somente_impressa'

# --- os campos do modelo ---------------------------------------------------------
#
# Chave do conteúdo -> nome do campo no PDF do Ministério.
CAMPOS_DE_TEXTO = {
    'cnes': 'CNES',
    'estabelecimento': 'Nome do estabelecimento de saúde',
    'paciente': 'Nome do paciente',
    'mae': 'Nome da mãe do paciente',
    'peso': 'Peso',
    'altura': 'Altura',
    'cid': 'CID',
    'diagnostico': 'Diagnóstico',
    'anamnese': 'Anamnese',
    'tratamento_relato': 'Tratamento',
    'responsavel': 'Nome do Responsável',
    'medico': 'Médico Solicitante',
    'medico_cns': 'TextCNS',
    'data': 'Today',
    'preenchido_outro_nome': 'Nome',
    'preenchido_outro_cpf': 'CPF',
    'etnia': 'Etnia',
    'telefone1': 'Telefone I',
    'telefone2': 'Telefone II',
    'documento_numero': 'Documento',
    'email': 'email',
}

#: Medicamento n (1..6) -> campo do nome.
CAMPOS_DE_MEDICAMENTO = [f'Selecao med {n}' for n in range(1, MAX_MEDICAMENTOS + 1)]

#: Quantidade: linha (medicamento) x coluna (mês). Os nomes do modelo não
#: seguem padrão nenhum (a 4ª linha usa Text18/19/20 e Text6b/7b/8b); a
#: tabela foi conferida pela posição de cada campo no arquivo.
CAMPOS_DE_QUANTIDADE = [
    ['Text6', 'Text7', 'Text8', 'Text6a', 'Text7a', 'Text8a'],
    ['Text10', 'Text11', 'Text12', 'Text10a', 'Text11a', 'Text12a'],
    ['Text14', 'Text15', 'Text16', 'Text14a', 'Text15a', 'Text16a'],
    ['Text18', 'Text19', 'Text20', 'Text6b', 'Text7b', 'Text8b'],
    ['Text22', 'Text23', 'Text24', 'Text10b', 'Text11b', 'Text12b'],
    ['Text22a', 'Text23a', 'Text24a', 'Text14b', 'Text15b', 'Text16b'],
]

#: Campos que admitem duas linhas (o nome de medicamento comprido, o
#: diagnóstico, o relato do tratamento prévio). A anamnese é o único campo
#: de várias linhas de verdade.
DUAS_LINHAS = {'estabelecimento', 'diagnostico', 'tratamento_relato', 'responsavel', 'medicamento'}
VARIAS_LINHAS = {'anamnese'}

#: Caixas de marcar: chave do conteúdo -> (campo do PDF, {valor: estado}).
#: Os estados (/0, /1...) foram conferidos pela posição de cada caixa ao
#: lado do rótulo impresso no modelo.
CAIXAS = {
    'tratamento_previo': ('Tratamentos prévios?', {'nao': '/0', 'sim': '/1'}),
    'incapaz': ('Incapaz?', {'nao': '/0', 'sim': '/1'}),
    'preenchido_por': ('dados complementares', {
        'paciente': '/0', 'mae': '/1', 'responsavel': '/2', 'medico': '/3', 'outro': '/4',
    }),
    'raca': ('Radio Button1', {
        'branca': '/0', 'amarela': '/1', 'preta': '/2', 'indigena': '/3', 'parda': '/4',
    }),
    'documento_tipo': ('Documentos', {'cpf': '/0', 'cns': '/1'}),
}

SIM_NAO = [('nao', 'Não'), ('sim', 'Sim')]
PREENCHIDO_POR = [
    ('medico', 'Médico solicitante'), ('paciente', 'Paciente'), ('mae', 'Mãe do paciente'),
    ('responsavel', 'Responsável (o do item 13)'), ('outro', 'Outro'),
]
RACAS = [
    ('branca', 'Branca'), ('preta', 'Preta'), ('parda', 'Parda'), ('amarela', 'Amarela'),
    ('indigena', 'Indígena'),
]
DOCUMENTOS = [('', 'Nenhum'), ('cpf', 'CPF'), ('cns', 'CNS (Cartão Nacional de Saúde)')]

#: As chaves do conteúdo da LME (`document_kinds.OPTIONAL_FIELDS`).
CHAVES = (
    *CAMPOS_DE_TEXTO, *CAIXAS, 'medicamentos', 'modelo',
)


class LmeInvalida(ValueError):
    """Conteúdo que não pode sair na LME (não cabe, falta, formato errado)."""


# --- o modelo -------------------------------------------------------------------

def carregar_modelo():
    dados = MODELO.read_bytes()
    if hashlib.sha256(dados).hexdigest() != SHA256_MODELO:
        raise RuntimeError(
            'O modelo da LME não confere com o SHA-256 registrado em documents/lme.py. '
            'Um modelo novo do Ministério entra com a constante trocada no mesmo commit.'
        )
    return dados


@lru_cache(maxsize=1)
def _widgets():
    """`[(nome, estado_ligado_ou_None, (x0, y0, x1, y1))]` de todos os campos do modelo."""
    import io

    from pypdf import PdfReader

    pagina = PdfReader(io.BytesIO(carregar_modelo())).pages[0]
    saida = []
    for anotacao in pagina.get('/Annots') or []:
        a = anotacao.get_object()
        if a.get('/Subtype') != '/Widget':
            continue
        pai = a['/Parent'].get_object() if a.get('/Parent') is not None else None
        nome = a.get('/T')
        if nome is None and pai is not None:
            nome = pai.get('/T')
        if nome is None:
            continue
        tipo = a.get('/FT') or (pai.get('/FT') if pai is not None else None)
        estado = None
        if tipo == '/Btn' and a.get('/AP') is not None:
            # Caixa de marcar ou rádio: a aparência normal é um dicionário
            # de estados ("/0", "/1"... e "/Off"); o que não é "/Off" é o
            # valor desta caixa. Botão de ação (Salvar, Limpar) tem uma
            # aparência só, sem estados, e fica com `None`.
            normal = a['/AP'].get_object().get('/N')
            if normal is not None and not hasattr(normal, 'get_data'):
                ligados = [k for k in normal.keys() if k != '/Off']
                if len(ligados) == 1:
                    estado = str(ligados[0])
        retangulo = tuple(float(v) for v in a['/Rect'])
        x0, y0, x1, y1 = retangulo
        saida.append((str(nome), estado, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))))
    return saida


def retangulo(nome):
    for n, estado, ret in _widgets():
        if n == nome and estado is None:
            return ret
    raise KeyError(nome)


def retangulo_da_caixa(nome, estado):
    for n, e, ret in _widgets():
        if n == nome and e == estado:
            return ret
    raise KeyError(f'{nome} {estado}')


def campos_que_faltam():
    """Os campos que este módulo usa e o modelo não tem (vazio = tudo certo)."""
    faltam = []
    nomes = [*CAMPOS_DE_TEXTO.values(), *CAMPOS_DE_MEDICAMENTO, *(c for linha in CAMPOS_DE_QUANTIDADE for c in linha)]
    for nome in nomes:
        try:
            retangulo(nome)
        except KeyError:
            faltam.append(nome)
    for nome, estados in CAIXAS.values():
        for estado in estados.values():
            try:
                retangulo_da_caixa(nome, estado)
            except KeyError:
                faltam.append(f'{nome} {estado}')
    return faltam


@lru_cache(maxsize=1)
def medicamentos_do_modelo():
    """A lista de sugestão que vem no próprio modelo, sem duplicatas e sem vazio."""
    import io

    from pypdf import PdfReader

    campos = PdfReader(io.BytesIO(carregar_modelo())).get_fields() or {}
    opcoes = []
    for campo in campos.values():
        if campo.get('/FT') == '/Ch' and campo.get('/Opt'):
            for opcao in campo['/Opt']:
                texto = str(opcao[1] if isinstance(opcao, list) else opcao)
                texto = ' '.join(texto.replace('–', '-').split())
                if texto and texto not in opcoes:
                    opcoes.append(texto)
            break
    return tuple(sorted(opcoes, key=lambda s: s.casefold()))


# --- texto que cabe ---------------------------------------------------------------

def imprimivel(texto):
    """O texto como a fonte padrão do PDF consegue desenhar.

    A Helvetica do PDF cobre o português (cp1252); um caractere fora dela
    (≥, emoji, aspas de outras línguas) sairia como lixo no papel. Troca o
    que tem equivalente e marca o resto com "?", que se vê na revisão.
    """
    trocas = {'≥': '>=', '≤': '<=', '→': '->', '×': 'x', ' ': ' ', '\t': ' '}
    saida = []
    for ch in str(texto or ''):
        ch = trocas.get(ch, ch)
        try:
            ch.encode('cp1252')
            saida.append(ch)
        except UnicodeEncodeError:
            saida.append('?')
    return ''.join(saida)


def _tamanhos():
    t = TAMANHO_MAXIMO
    while t >= TAMANHO_MINIMO - 1e-9:
        yield round(t, 2)
        t -= 0.5


def ajustar(texto, largura, altura, max_linhas):
    """`(tamanho, linhas)` do maior tamanho em que o texto cabe, ou `None`.

    Respeita as quebras de linha que o médico digitou (só na anamnese, onde
    `max_linhas` é maior que 2).
    """
    texto = imprimivel(texto).strip()
    if not texto:
        return (TAMANHO_MAXIMO, [])
    paragrafos = texto.splitlines() if max_linhas > 2 else [' '.join(texto.split())]
    for tamanho in _tamanhos():
        entrelinha = tamanho * 1.15
        cabe_linhas = min(max_linhas, int((altura - 1) // entrelinha) or 1)
        linhas = []
        for paragrafo in paragrafos:
            linhas += simpleSplit(' '.join(paragrafo.split()), FONTE, tamanho, largura) or ['']
        if len(linhas) <= cabe_linhas and all(stringWidth(l, FONTE, tamanho) <= largura + 0.01 for l in linhas):
            return (tamanho, linhas)
    return None


#: Folga entre a borda do campo e o texto.
MARGEM = 2.0


def _max_linhas(chave):
    if chave in VARIAS_LINHAS:
        return 99
    if chave in DUAS_LINHAS:
        return 2
    return 1


def caixa_de(chave, nome_pdf):
    x0, y0, x1, y1 = retangulo(nome_pdf)
    return x0 + MARGEM, y0, x1 - MARGEM, y1


ROTULOS = {
    'cnes': '1 — CNES', 'estabelecimento': '2 — Estabelecimento', 'paciente': '3 — Nome do paciente',
    'mae': '4 — Nome da mãe', 'peso': '5 — Peso', 'altura': '6 — Altura', 'cid': '9 — CID-10',
    'diagnostico': '10 — Diagnóstico', 'anamnese': '11 — Anamnese',
    'tratamento_relato': '12 — Tratamento prévio (relato)', 'responsavel': '13 — Nome do responsável',
    'medico': '14 — Nome do médico', 'medico_cns': '15 — CNS do médico', 'data': '16 — Data',
    'preenchido_outro_nome': '18 — Nome de quem preencheu', 'preenchido_outro_cpf': '18 — CPF de quem preencheu',
    'etnia': '19 — Etnia', 'telefone1': '20 — Telefone', 'telefone2': '20 — Telefone',
    'documento_numero': '21 — Documento', 'email': '22 — E-mail',
}


def o_que_nao_cabe(conteudo):
    """`{chave: mensagem}` dos valores que não cabem no campo do modelo."""
    erros = {}
    for chave, nome_pdf in CAMPOS_DE_TEXTO.items():
        valor = conteudo.get(chave) or ''
        if not str(valor).strip():
            continue
        x0, y0, x1, y1 = caixa_de(chave, nome_pdf)
        if ajustar(valor, x1 - x0, y1 - y0, _max_linhas(chave)) is None:
            erros[chave] = f'Não cabe no campo “{ROTULOS[chave]}” da LME, mesmo com a letra menor. Encurte o texto.'
    for indice, item in enumerate(conteudo.get('medicamentos') or []):
        x0, y0, x1, y1 = caixa_de('medicamento', CAMPOS_DE_MEDICAMENTO[indice])
        if ajustar(item.get('nome', ''), x1 - x0, y1 - y0, 2) is None:
            erros[f'medicamento_{indice + 1}'] = (
                f'O medicamento {indice + 1} não cabe na linha da LME, mesmo com a letra menor. Abrevie a apresentação.'
            )
    return erros


# --- validação do conteúdo -------------------------------------------------------

def so_digitos(valor):
    return re.sub(r'\D', '', str(valor or ''))


def formatar_cpf(valor):
    d = so_digitos(valor)
    return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}' if len(d) == 11 else str(valor or '')


def formatar_cns(valor):
    d = so_digitos(valor)
    return f'{d[:3]}.{d[3:7]}.{d[7:11]}.{d[11:]}' if len(d) == 15 else str(valor or '')


def formatar_telefone(valor):
    d = so_digitos(valor)
    if d.startswith('55') and len(d) in (12, 13):
        d = d[2:]
    if len(d) == 11:
        return f'({d[:2]}) {d[2:7]}-{d[7:]}'
    if len(d) == 10:
        return f'({d[:2]}) {d[2:6]}-{d[6:]}'
    return str(valor or '').strip()


CID10 = re.compile(r'^[A-Z][0-9]{2}(\.?[0-9])?$')


def normalizar_cid(valor):
    """"g35", "G35.0", "G350" -> "G35", "G35.0", "G35.0"; outra coisa passa como veio."""
    texto = re.sub(r'\s', '', str(valor or '')).upper()
    m = re.fullmatch(r'([A-Z][0-9]{2})\.?([0-9])?', texto)
    if not m:
        return texto
    return m.group(1) + (f'.{m.group(2)}' if m.group(2) else '')


def validar(conteudo):
    """Confere o conteúdo inteiro; levanta `LmeInvalida` com todas as mensagens.

    Os campos com asterisco no modelo são obrigatórios aqui também: a
    farmácia devolve a LME sem eles, e descobrir isso com o paciente no
    balcão é o que esta conferência evita. Os demais (telefone, e-mail,
    documento do paciente) são opcionais, como no modelo.
    """
    erros = {}

    def exige(chave, mensagem):
        if not str(conteudo.get(chave) or '').strip():
            erros[chave] = mensagem

    if not re.fullmatch(r'[0-9]{7}', str(conteudo.get('cnes') or '')):
        erros['cnes'] = 'O CNES tem sete dígitos (consulte em cnes.datasus.gov.br).'
    exige('paciente', 'Informe o nome completo do paciente.')
    exige('mae', 'Informe o nome da mãe (se for desconhecido, escreva “IGNORADA”).')
    exige('peso', 'Informe o peso do paciente.')
    exige('altura', 'Informe a altura do paciente.')
    exige('anamnese', 'A anamnese é obrigatória na LME.')
    exige('medico', 'Informe o nome do médico solicitante.')
    if conteudo.get('peso') and not re.fullmatch(r'[0-9]{1,3}([.,][0-9]{1,2})?', str(conteudo['peso'])):
        erros['peso'] = 'Peso em quilos, com até duas casas decimais (ex.: 72 ou 72,5).'
    if conteudo.get('altura') and not re.fullmatch(r'[0-9]{2,3}', str(conteudo['altura'])):
        erros['altura'] = 'Altura em centímetros, só números (ex.: 172).'
    if not CID10.fullmatch(str(conteudo.get('cid') or '')):
        erros['cid'] = 'Informe o CID-10 (letra e dois números, ex.: G35 ou G35.0). A LME só aceita CID-10.'
    if len(so_digitos(conteudo.get('medico_cns'))) != 15:
        erros['medico_cns'] = 'O CNS do médico tem 15 dígitos.'

    medicamentos = conteudo.get('medicamentos') or []
    if not medicamentos:
        erros['medicamentos'] = 'Inclua ao menos um medicamento, com a quantidade de ao menos um mês.'
    if len(medicamentos) > MAX_MEDICAMENTOS:
        erros['medicamentos'] = f'A LME tem {MAX_MEDICAMENTOS} linhas de medicamento.'
    for indice, item in enumerate(medicamentos[:MAX_MEDICAMENTOS], start=1):
        quantidades = item.get('quantidades') or []
        if len(quantidades) != MESES or not any(q for q in quantidades):
            erros[f'medicamento_{indice}'] = f'Informe a quantidade de ao menos um mês para o medicamento {indice}.'
        elif any(q and not re.fullmatch(r'[0-9]{1,4}', str(q)) for q in quantidades):
            erros[f'medicamento_{indice}'] = f'A quantidade do medicamento {indice} é um número inteiro de até 4 dígitos.'

    if conteudo.get('tratamento_previo') not in ('sim', 'nao'):
        erros['tratamento_previo'] = 'Diga se o paciente já fez ou faz tratamento da doença.'
    elif conteudo['tratamento_previo'] == 'sim':
        exige('tratamento_relato', 'Relate o tratamento prévio (o modelo pede “SIM. Relatar”).')
    if conteudo.get('incapaz') not in ('sim', 'nao'):
        erros['incapaz'] = 'Diga se o paciente é considerado incapaz (item 13).'
    elif conteudo['incapaz'] == 'sim':
        exige('responsavel', 'Paciente incapaz: indique o nome do responsável, que poderá pedir o medicamento.')
    if conteudo.get('preenchido_por') not in dict(PREENCHIDO_POR):
        erros['preenchido_por'] = 'Diga quem preencheu os campos 19 a 23.'
    elif conteudo['preenchido_por'] == 'outro':
        exige('preenchido_outro_nome', 'Informe o nome de quem preencheu.')
        if len(so_digitos(conteudo.get('preenchido_outro_cpf'))) != 11:
            erros['preenchido_outro_cpf'] = 'Informe o CPF (11 dígitos) de quem preencheu.'
    if conteudo.get('raca') not in dict(RACAS):
        erros['raca'] = 'Informe a raça/cor declarada pelo paciente ou responsável (item 19).'
    elif conteudo['raca'] == 'indigena':
        exige('etnia', 'Paciente indígena: informe a etnia.')
    tipo = conteudo.get('documento_tipo') or ''
    numero = so_digitos(conteudo.get('documento_numero'))
    if tipo == 'cpf' and len(numero) != 11:
        erros['documento_numero'] = 'O CPF tem 11 dígitos.'
    elif tipo == 'cns' and len(numero) != 15:
        erros['documento_numero'] = 'O CNS tem 15 dígitos.'
    elif not tipo and numero:
        erros['documento_tipo'] = 'Diga se o documento é CPF ou CNS.'

    if not erros:
        erros.update(o_que_nao_cabe(conteudo))
    if erros:
        excecao = LmeInvalida(' '.join(dict.fromkeys(erros.values())))
        excecao.erros = erros
        raise excecao


def assinatura_digital_bloqueada(document):
    from .models import MedicalDocumentKind

    return document.kind == MedicalDocumentKind.LME


# --- valores iniciais da tela ------------------------------------------------------

#: O que a LME anterior do mesmo paciente traz para a nova, mesmo sem
#: "a partir desta": dado de identificação que o cadastro não guarda
#: (raça/cor, CNS) ou que o médico já conferiu na anterior.
DA_LME_ANTERIOR = (
    'raca', 'etnia', 'documento_tipo', 'documento_numero', 'telefone1', 'telefone2', 'email',
    'incapaz', 'responsavel', 'preenchido_por', 'preenchido_outro_nome', 'preenchido_outro_cpf',
)


def _ultima_lme(**filtros):
    from .models import MedicalDocument, MedicalDocumentKind

    return (MedicalDocument.objects.filter(kind=MedicalDocumentKind.LME, **filtros)
            .order_by('-created_at').only('content_snapshot').first())


def _cnes_do_tiss(tenant_id):
    try:
        from tiss.models import Prestador
    except ImportError:  # pragma: no cover - os dois produtos têm o TISS
        return ''
    prestador = (Prestador.objects.filter(tenant_id=tenant_id, ativo=True).exclude(cnes='')
                 .order_by('nome').first())
    return prestador.cnes if prestador and prestador.cnes != '9999999' else ''


def _peso_e_altura(patient):
    from patients.models import ObservationKind
    from patients.observations import latest_observation

    peso = altura = ''
    obs = latest_observation(patient, ObservationKind.WEIGHT)
    if obs is not None:
        valor = obs.numeric_value
        peso = (f'{valor:.2f}'.rstrip('0').rstrip('.')).replace('.', ',')
    obs = latest_observation(patient, ObservationKind.HEIGHT)
    if obs is not None:
        valor = obs.numeric_value
        # A ficha grava a altura em metros; a LME pede centímetros.
        cm = valor * 100 if (obs.unit or 'm').lower() == 'm' else valor
        altura = str(int(round(cm)))
    return peso, altura


def _contatos(patient):
    from communications.services import _proprio_primeiro, _still_valid

    telefones, email = [], ''
    for contato in _proprio_primeiro(patient.contacts.all()):
        if not _still_valid(contato):
            continue
        if contato.phone and so_digitos(contato.phone) not in [so_digitos(t) for t in telefones]:
            telefones.append(contato.phone)
        if contato.email and not email:
            email = contato.email
    return (telefones + ['', ''])[:2], email


def valores_iniciais(tenant, patient, physician_membership, encounter=None, base=None):
    """O que a tela da LME abre preenchido.

    `base` é a LME de onde se parte ("Nova LME a partir desta"): o conteúdo
    dela inteiro, menos a data, que é sempre a da emissão. Sem `base`, o
    cadastro do paciente, a ficha (peso e altura), a LME anterior do mesmo
    paciente (identificação), a anterior do mesmo médico (CNS e
    estabelecimento) e as hipóteses do atendimento (CID).

    Tudo dentro da clínica da sessão: o CNS que o médico informou noutra
    clínica é conteúdo daquela clínica.
    """
    perfil = physician_membership.user.physician_profile
    if base is not None:
        inicial = {k: v for k, v in (base.content_snapshot or {}).items() if k in CHAVES}
        inicial['medico'] = perfil.professional_name
        return inicial

    peso, altura = _peso_e_altura(patient)
    telefones, email = _contatos(patient)
    inicial = {
        'paciente': patient.full_name,
        'mae': patient.mother_name,
        'peso': peso,
        'altura': altura,
        'medico': perfil.professional_name,
        'telefone1': telefones[0],
        'telefone2': telefones[1],
        'email': email,
        'documento_tipo': 'cpf' if patient.cpf else '',
        'documento_numero': formatar_cpf(patient.cpf) if patient.cpf else '',
        'preenchido_por': 'medico',
        'incapaz': '',
        'tratamento_previo': '',
    }
    do_paciente = _ultima_lme(tenant_id=tenant.id, patient=patient)
    if do_paciente is not None:
        anterior = do_paciente.content_snapshot or {}
        for chave in DA_LME_ANTERIOR:
            if anterior.get(chave):
                inicial[chave] = anterior[chave]
    do_medico = _ultima_lme(tenant_id=tenant.id, physician=physician_membership)
    anterior = (do_medico.content_snapshot or {}) if do_medico is not None else {}
    inicial['medico_cns'] = anterior.get('medico_cns', '')
    inicial['cnes'] = anterior.get('cnes') or _cnes_do_tiss(tenant.id)
    inicial['estabelecimento'] = anterior.get('estabelecimento') or tenant.trade_name or tenant.legal_name

    if encounter is not None:
        from modelos.emissao import diagnosticos_do_atendimento

        for hipotese in diagnosticos_do_atendimento(encounter):
            codigo = normalizar_cid(hipotese.split(' — ')[0])
            if CID10.fullmatch(codigo):
                inicial['cid'] = codigo
                inicial['diagnostico'] = hipotese.split(' — ', 1)[1] if ' — ' in hipotese else ''
                break
    return inicial
