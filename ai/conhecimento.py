"""O que o chat de apoio sabe sobre o próprio NeuroDoc.

Na conversa **sem paciente**, o chat de apoio responde também a dúvida de
uso do sistema ("como bloqueio um horário?", "onde fica o laudo que o
paciente mandou?"). Ele responde a partir de trechos do **manual** (a
central de ajuda, `base/help_content.py`) e da **documentação técnica**
(`docs/homologation/` e `docs/governance/`), escolhidos para cada pergunta
e entregues junto com ela. É RAG: recuperar o trecho, e só então gerar.

## Por que busca por palavras, e não por embeddings

A alternativa natural seria vetorizar os trechos e buscar por
similaridade. Três razões para não fazê-lo, na ordem do `chat_prompt.py`:

1. **Não depende do provedor.** Embedding é outra chamada, a outro
   modelo, que metade dos dez provedores do catálogo não oferece. A
   clínica que configurou o próprio provedor ficaria sem a busca.
2. **O corpus é pequeno e fala a língua da pergunta.** São ~90 artigos e
   documentos escritos para quem usa o sistema, com o vocabulário da tela
   ("bloquear horário", "portal", "adendo"). Para isso, BM25 sobre o texto
   sem acento acha o trecho certo.
3. **Auditável e sem estado.** O índice é montado do texto que está na
   imagem, na memória do processo, a cada publicação. Não há base vetorial
   para manter, migrar ou ficar desatualizada em relação ao código.

## O que nunca entra

- **Conversa ligada a paciente.** Ali o assunto é o prontuário, e a
  documentação disputaria espaço com os dados dele (`build_chat_prompt`).
- **Nada de dado de paciente.** O corpus é texto versionado do repositório,
  público desde 2026-10-19. Não há o que desidentificar.
- **Plano de trabalho e histórico de publicação** (`docs/releases/`,
  `docs/superpowers/`): descrevem como o sistema *foi* sendo feito, e o
  modelo os leria como descrição do que ele *é*.
"""
import functools
import logging
import math
import re
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Pastas da documentação técnica que entram. O manual (help_content) entra
#: sempre, e na frente: é escrito para quem usa a tela.
PASTAS_DE_DOCUMENTACAO = ('docs/homologation', 'docs/governance')

#: Quantos trechos acompanham a pergunta, e o teto de caracteres deles.
#: Quatro trechos cobrem uma resposta que cruza dois assuntos sem empurrar
#: o histórico da conversa para fora da janela do modelo.
MAX_TRECHOS = 4
MAX_CARACTERES = 6000

#: Tamanho alvo de um trecho. Seção maior é partida por parágrafo: trecho
#: grande demais ocupa a cota inteira com um assunto só.
TAMANHO_DO_TRECHO = 1400

#: Pontuação mínima para um trecho valer. Medida em 2026-10-19 sobre
#: perguntas reais: as de uso do sistema ficam entre 7 e 15; as clínicas
#: puras ("dose de topiramato", "AVC isquêmico ou hemorrágico") entre 4 e 6.
#: As duas faixas se tocam -- a documentação técnica cita doenças como
#: exemplo, e "critérios de McDonald" acha o roteiro da busca por CID --,
#: então o corte tira o ruído grosso e o prompt faz o resto: os trechos
#: valem só para pergunta sobre o sistema (`chat_prompt.COM_MANUAL`).
PONTUACAO_MINIMA = 5.0

#: Palavras que aparecem em toda pergunta e não distinguem trecho nenhum.
PALAVRAS_VAZIAS = frozenset('''
A AO AOS AS COM COMO DA DAS DE DO DOS E EH EM ENTRE ESSA ESSE ESTA ESTE EU
FAZ FAZER ISSO JA LA MAIS MAS ME MEU MINHA NA NAS NAO NO NOS NUM NUMA O OS
OU PARA PELA PELO POR POSSO PRA PRECISO QUAL QUANDO QUE SE SEM SER SEU SUA
TEM TER UM UMA VOCE VOCES SISTEMA NEURODOC ONDE FICA
'''.split())

#: Endereço público da central de ajuda, para o modelo poder apontar.
URL_DA_AJUDA = '/ajuda/'


def _normalizar(texto):
    from catalogs.importers import normalize_for_search

    return normalize_for_search(texto)


#: Letras do radical. A pergunta e o manual raramente usam a mesma forma da
#: palavra: "como exporto" contra "Exportar o acervo", "bloqueio" contra
#: "bloquear", "horários" contra "horário". Seis letras juntam as formas de
#: um verbo e do substantivo dele sem juntar palavras diferentes demais
#: ("MEDICO" e "MEDICA" continuam separadas).
RADICAL = 6


def _termos(texto):
    """Os radicais das palavras que contam, sem acento e em maiúsculas."""
    termos = []
    for palavra in re.findall(r'[A-Z0-9]+', _normalizar(texto)):
        if len(palavra) < 3 or palavra in PALAVRAS_VAZIAS:
            continue
        termos.append(palavra[:RADICAL])
    return termos


def _partir(titulo, fonte, texto):
    """Um texto longo em trechos de ~TAMANHO_DO_TRECHO, cortados em parágrafo."""
    paragrafos = [p.strip() for p in re.split(r'\n\s*\n', texto) if p.strip()]
    trechos, atual = [], ''
    for paragrafo in paragrafos:
        if atual and len(atual) + len(paragrafo) > TAMANHO_DO_TRECHO:
            trechos.append(atual)
            atual = ''
        atual = f'{atual}\n\n{paragrafo}' if atual else paragrafo
    if atual:
        trechos.append(atual)
    return [{'titulo': titulo, 'fonte': fonte, 'texto': t} for t in trechos]


def _do_manual():
    from base.help_content import ARTICLES, FAQ_USO

    trechos = []
    for artigo in ARTICLES:
        passos = [passo[0] if isinstance(passo, (tuple, list)) else str(passo)
                  for passo in artigo.get('steps', [])]
        corpo = '\n\n'.join([artigo.get('summary', ''), *passos])
        trechos += _partir(
            f'Manual: {artigo["title"]}', f'{URL_DA_AJUDA}{artigo["slug"]}/', corpo,
        )
    for item in FAQ_USO:
        trechos.append({
            'titulo': f'Pergunta frequente: {item["pergunta"]}',
            'fonte': f'{URL_DA_AJUDA}perguntas/',
            'texto': item['resposta'],
        })
    return trechos


def _da_documentacao():
    raiz = Path(settings.BASE_DIR)
    trechos = []
    for pasta in PASTAS_DE_DOCUMENTACAO:
        for arquivo in sorted((raiz / pasta).glob('*.md')):
            try:
                conteudo = arquivo.read_text(encoding='utf-8')
            except OSError:
                continue
            documento = arquivo.stem
            secao, linhas = documento, []

            def fechar():
                texto = '\n'.join(linhas).strip()
                if texto:
                    trechos.extend(_partir(
                        f'Documentação: {secao}', f'{pasta}/{arquivo.name}', texto,
                    ))

            for linha in conteudo.splitlines():
                cabecalho = re.match(r'^#{1,4}\s+(.+)', linha)
                if cabecalho:
                    fechar()
                    secao, linhas = f'{documento} — {cabecalho.group(1).strip()}', []
                else:
                    linhas.append(linha)
            fechar()
    return trechos


@functools.lru_cache(maxsize=1)
def indice():
    """Os trechos e as estatísticas do BM25, montados uma vez por processo.

    O corpus é o que está na imagem, e a imagem muda a cada publicação; por
    isso o cache vive o tempo do processo e nada é gravado.
    """
    try:
        trechos = _do_manual() + _da_documentacao()
    except Exception:                                   # noqa: BLE001
        logger.exception('ai: índice da documentação não montou')
        trechos = []
    documentos = []
    frequencia = {}
    for trecho in trechos:
        termos = _termos(f'{trecho["titulo"]} {trecho["texto"]}')
        contagem = {}
        for termo in termos:
            contagem[termo] = contagem.get(termo, 0) + 1
        documentos.append((trecho, contagem, len(termos)))
        for termo in contagem:
            frequencia[termo] = frequencia.get(termo, 0) + 1
    media = (sum(n for _, _, n in documentos) / len(documentos)) if documentos else 1
    return documentos, frequencia, media


def buscar(pergunta, limite=MAX_TRECHOS):
    """Os trechos que respondem à pergunta, do mais ao menos relevante.

    BM25 (k1=1.5, b=0.75). O manual ganha um empurrão de 30% sobre a
    documentação técnica: quando os dois falam do mesmo assunto, a resposta
    para quem está na tela é a do manual.
    """
    documentos, frequencia, media = indice()
    consulta = set(_termos(pergunta))
    if not consulta or not documentos:
        return []
    total = len(documentos)
    k1, b = 1.5, 0.75
    pontuados = []
    for trecho, contagem, tamanho in documentos:
        pontos = 0.0
        for termo in consulta:
            tf = contagem.get(termo)
            if not tf:
                continue
            idf = math.log(1 + (total - frequencia[termo] + 0.5) / (frequencia[termo] + 0.5))
            pontos += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * tamanho / media))
        if trecho['titulo'].startswith(('Manual', 'Pergunta')):
            pontos *= 1.3
        if pontos >= PONTUACAO_MINIMA:
            pontuados.append((pontos, trecho))
    pontuados.sort(key=lambda item: -item[0])

    escolhidos, usados = [], 0
    for _, trecho in pontuados:
        if len(escolhidos) >= limite or usados + len(trecho['texto']) > MAX_CARACTERES:
            break
        escolhidos.append(trecho)
        usados += len(trecho['texto'])
    return escolhidos


def bloco_para_o_prompt(trechos):
    """Os trechos como seção do prompt, cada um com a sua fonte."""
    if not trechos:
        return ''
    partes = [
        f'### {t["titulo"]}\n(fonte: {t["fonte"]})\n{t["texto"]}' for t in trechos
    ]
    return '\n\n'.join(partes)
