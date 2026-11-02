"""Tradução de uma anotação do sistema anterior (iClin) para um atendimento.

O cadastro já veio (`patients/importacao.py`). Faltava o histórico: sem ele,
o NeuroDoc não sabe quando o paciente foi visto pela última vez, e o portal
recusa o pedido de receita de quem consultou na semana anterior à troca de
sistema (`documents/portal_retorno.py`). O comando
`import_atendimentos_xml` executa esta tradução.

**Por que texto livre, e não o prontuário estruturado.** A anotação do iClin
tem seções com nomes estáveis — queixa, antecedentes, exame, diagnósticos,
prescrição — e parece que caberiam nos campos do estruturado. Não cabem
sem interpretar: "Medicamentos em uso" e "Prescrição" são texto escrito à
mão, e a medicação do NeuroDoc é uma lista com dose, via e frequência em
colunas. Passar seis mil prescrições para essa lista seria adivinhar
posologia, e a regra da migração do cadastro vale aqui também: o que exige
interpretação não é espalhado em campos.

**O que se separa, e por quê.** Duas seções saem do corpo, porque são as
duas que o NeuroDoc **leva para a consulta seguinte**
(`clinical/carry_forward.py`):

- **Diagnósticos** → `impressions`. O médico não usava CID no iClin; o
  texto vai como impressão, e não como `EncounterDiagnosis`, que pediria
  um código ou uma certeza que a anotação não declara.
- **Prescrição de medicamentos** e **Condutas e orientações** →
  `plan_text`.

Tudo o mais fica no corpo (`free_text`), com os títulos das seções e na
ordem em que estava. Nada é descartado; o arquivo original segue guardado
pelo médico como documento das evoluções anteriores.

**Título de seção só conta no começo de um bloco.** O título precisa ser
uma linha inteira, depois do início ou de uma linha em branco, e seguida da
linha `- ` com que o iClin abre o conteúdo de toda seção. A mesma palavra
no meio de um parágrafo continua sendo texto. E o `- ` de abertura sai:
ele é a moldura que o iClin põe em volta de cada seção, não algo que o
médico escreveu — as listas que o médico escreveu ficam como estavam.
"""
import unicodedata
import re
from datetime import date, datetime

#: As seções da anotação do iClin, como o arquivo as escreve. Lista
#: fechada de propósito: um título que não está aqui é texto do médico.
SECOES = (
    'Queixas principais ou evolução',
    'Evolução',
    'Anamnese e exame físico',
    'Antecedentes pessoais e hábitos',
    'Antecedentes familiares',
    'Medicamentos em uso',
    'Exame físico',
    'Resultados de exames',
    'Diagnósticos',
    'Prescrição de medicamentos',
    'Condutas e orientações',
)
PARA_IMPRESSOES = {'Diagnósticos'}
PARA_CONDUTA = {'Prescrição de medicamentos', 'Condutas e orientações'}

#: Os campos que o comando confere antes de ler: arquivo com outra forma
#: importaria sete mil consultas vazias em silêncio.
CAMPOS_ESPERADOS = {'num_anotacao', 'data', 'num_cliente', 'nome_cliente', 'dt_nasc', 'tx'}

#: Os limites dos campos de `Encounter`. Nenhuma anotação do arquivo de
#: 2026-11 passa de 13 mil caracteres; conferir aqui transforma a exceção
#: futura numa linha do relatório em vez de uma transação desfeita.
LIMITES = {'free_text': 100000, 'impressions': 20000, 'plan_text': 20000}


def _texto(registro, tag):
    elemento = registro.find(tag)
    return (elemento.text or '').strip() if elemento is not None else ''


def nome_comparavel(nome):
    """O nome sem acento, sem pontuação e em caixa alta, para casar fichas.

    Só para comparar: o nome gravado continua o da ficha.
    """
    sem_acento = unicodedata.normalize('NFKD', nome or '').encode('ascii', 'ignore').decode()
    return ' '.join(re.sub(r'[^A-Z ]', ' ', sem_acento.upper()).split())


def separar_secoes(texto):
    """Devolve `(free_text, impressions, plan_text)` de uma anotação."""
    linhas = (texto or '').replace('\r\n', '\n').split('\n')
    blocos = []          # [(título ou None, [linhas])]
    atual = (None, [])
    for i, linha in enumerate(linhas):
        titulo = linha.strip()
        comeco_de_bloco = i == 0 or not linhas[i - 1].strip()
        abre_conteudo = i + 1 < len(linhas) and linhas[i + 1].startswith('- ')
        if titulo in SECOES and comeco_de_bloco and abre_conteudo:
            blocos.append(atual)
            atual = (titulo, [])
            continue
        atual[1].append(linha)
    blocos.append(atual)

    corpo, impressoes, conduta = [], [], []
    for titulo, conteudo in blocos:
        if conteudo and conteudo[0].startswith('- ') and titulo:
            conteudo = [conteudo[0][2:]] + conteudo[1:]
        texto_bloco = '\n'.join(conteudo).strip()
        if not texto_bloco:
            continue
        if titulo in PARA_IMPRESSOES:
            impressoes.append((titulo, texto_bloco))
        elif titulo in PARA_CONDUTA:
            conduta.append((titulo, texto_bloco))
        else:
            corpo.append((titulo, texto_bloco))

    def juntar(partes, com_titulo):
        return '\n\n'.join(
            f'{t}\n{b}' if (t and com_titulo) else b for t, b in partes
        )

    # O corpo leva os títulos sempre: é ali que várias seções se encontram.
    # A impressão é uma seção só e o campo já se chama "Impressões"; a
    # conduta leva os títulos quando junta prescrição e orientações.
    return juntar(corpo, True), juntar(impressoes, False), juntar(conduta, len(conduta) > 1)


def _arquivos(registro, tag):
    elemento = registro.find(tag)
    if elemento is None:
        return []
    nomes = [(n.text or '').strip() for n in elemento.findall('nome')]
    links = [(n.text or '').strip() for n in elemento.findall('link')]
    return [(nome or 'arquivo', link) for nome, link in zip(nomes, links) if link]


def ler_anotacao(registro):
    """Uma `<anotacao>` traduzida, ou `None` quando não há o que migrar.

    Sem texto não há consulta a registrar: um atendimento vazio na data
    serviria só para enganar o portal sobre a última visita.
    """
    numero = _texto(registro, 'num_anotacao')
    free_text, impressions, plan_text = separar_secoes(_texto(registro, 'tx'))

    # Anexos e documentos ficaram no iClin; vão os nomes e os endereços,
    # escritos, para quem precisar saber que existiam.
    listas = []
    for titulo, tag in (('Anexos no iClin', 'anexos'), ('Documentos emitidos no iClin', 'doc_adicionais')):
        itens = _arquivos(registro, tag)
        if itens:
            listas.append(titulo + ':\n' + '\n'.join(f'- {nome}: {link}' for nome, link in itens))
    if listas and (free_text or impressions or plan_text):
        free_text = '\n\n'.join(p for p in [free_text, *listas] if p)

    if not (free_text or impressions or plan_text) or not numero:
        return None
    try:
        quando = datetime.fromisoformat(_texto(registro, 'data'))
    except ValueError:
        return None
    try:
        nascimento = date.fromisoformat(_texto(registro, 'dt_nasc'))
    except ValueError:
        nascimento = None
    return {
        'legacy_id': f'iclin:{numero}',
        'numero': numero,
        'cliente': _texto(registro, 'num_cliente'),
        'nome': _texto(registro, 'nome_cliente'),
        'nascimento': nascimento,
        'quando': quando,
        'alerta': _texto(registro, 'alerta'),
        'free_text': free_text,
        'impressions': impressions,
        'plan_text': plan_text,
    }


def excede_limite(anotacao):
    return [campo for campo, teto in LIMITES.items() if len(anotacao[campo]) > teto]
