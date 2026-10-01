"""Aderencia ao celular: o que da para conferir sem navegador.

Layout nao se mede em Python — transbordo horizontal, altura de botao e
tamanho de fonte efetivo dependem de renderizar a pagina. A auditoria que
produziu estas regras foi feita num navegador de verdade, em 27 telas e em
quatro tamanhos (390x844, 360x740, 844x390 e 768x1024), e esta registrada em
`docs/homologation/mobile.md`.

O que este roteiro faz e outra coisa, e e por isso que ele existe: **impedir
que o remendo desapareca**. As regras de toque nao produzem efeito nenhum no
computador — nenhuma tela muda, nenhum roteiro reclama —, e CSS que nao faz
nada visivel e o primeiro candidato a ser apagado numa limpeza. Aqui se
afirma o contrato: as regras existem, valem para o dedo e nao so para a tela
estreita, e nenhuma tabela nova escapa do embrulho que a faz rolar.

As perguntas sao:

- o bloco de toque existe, e a condicao dele inclui `pointer: coarse`?
  (largura sozinha deixa de valer no celular deitado, que tem 844px)
- os campos vao a 16px? (abaixo disso o Safari do iPhone da zoom no foco e
  nao volta)
- o alvo de toque chega a 40px?
- a barra de acoes da pagina quebra a linha em vez de sair da tela?
- o campo de escrever do chat tambem vai a 16px?
- toda tabela do produto esta dentro de `.table-responsive`?
- alguma `row` usa calha grande sem variante responsiva? (a margem negativa
  de `g-5` passa da folga do `container` e a pagina rola na horizontal)
"""
import io
import os
import pathlib
import re

falhas = []

CSS_TEMA = 'static/duralux/neurodoc.css'
CSS_CHAT = 'static/teamchat/teamchat.css'
RAIZ_TEMPLATES = 'templates'


def ler(caminho):
    with io.open(caminho, encoding='utf-8') as fh:
        return fh.read()


print('=' * 66)
print('1. O BLOCO DE TOQUE EXISTE E PERGUNTA PELO DEDO')
print('=' * 66)

css = ler(CSS_TEMA)
blocos = re.findall(r'@media ([^{]+)\{', css)
toque = [q.strip() for q in blocos if 'pointer' in q and 'coarse' in q]
print('  consultas com pointer:coarse ->', toque or 'NENHUMA')
if not toque:
    falhas.append('o bloco de toque nao existe mais em neurodoc.css, ou perdeu o pointer:coarse')

# A largura sozinha nao basta: um celular deitado tem 844px.
if toque and not any('max-width' in q for q in toque):
    falhas.append('a consulta de toque perdeu o teto de largura e passou a valer no computador')

print()
print('=' * 66)
print('2. AS TRES REGRAS QUE O CELULAR PRECISA')
print('=' * 66)

# Recorta o bloco de toque para conferir dentro dele, e nao no arquivo todo:
# a regra no lugar errado vale para o computador e muda a densidade do tema.
inicio = css.find('@media (max-width: 767.98px), (pointer: coarse)')
bloco = css[inicio:] if inicio >= 0 else ''

esperado = [
    ('16px nos campos', r'\.form-control[\s\S]{0,200}?font-size:\s*1rem'),
    ('40px de alvo de toque', r'\.btn[\s\S]{0,200}?min-height:\s*40px'),
    ('caixa de selecao maior', r'\.form-check-input[\s\S]{0,200}?width:\s*1\.25rem'),
    # A paginacao nao herda a regra do botao: `.page-link` nao e `.btn`.
    # Ficava com 30px, tres quartos do alvo que o resto da tela respeita --
    # e na lista de pacientes, com noventa paginas depois da migracao,
    # "Anterior" e "Proxima" sao o unico jeito de andar pelo celular.
    ('40px na paginacao', r'\.page-link[\s\S]{0,200}?min-height:\s*40px'),
    ('paginacao quebrando linha', r'\.pagination[\s\S]{0,120}?flex-wrap:\s*wrap'),
]
for rotulo, padrao in esperado:
    presente = bool(re.search(padrao, bloco))
    print(f'  {rotulo:<26} {presente}')
    if not presente:
        falhas.append(f'a regra de {rotulo} saiu do bloco de toque')

# A barra de acoes tem de quebrar linha. Esta FORA de media query de
# proposito: a condicao e a largura disponivel, nao o tipo de aparelho.
quebra = re.search(r'\.page-header-right-items-wrapper\s*\{[^}]*flex-wrap:\s*wrap', css)
print('  barra de acoes quebra linha  ', bool(quebra))
if not quebra:
    falhas.append('a barra de acoes da pagina voltou a nao quebrar linha (transbordava em 768px)')

chat = ler(CSS_CHAT)
alvo_chat = re.search(
    r'@media[^{]*coarse[^{]*\{[\s\S]{0,400}?\.nd-tc-composer textarea\s*\{[^}]*font-size:\s*16px',
    chat,
)
print('  campo do chat a 16px         ', bool(alvo_chat))
if not alvo_chat:
    falhas.append('o campo de escrever do chat perdeu os 16px do celular')

print()
print('=' * 66)
print('3. TODA TABELA ROLA EM VEZ DE ESTOURAR A TELA')
print('=' * 66)

# Tabela larga sem `.table-responsive` empurra a pagina inteira para o lado.
# As excecoes sao as folhas para impressao e a pagina publica de verificacao,
# que nao tem o tema e cujas tabelas sao de duas colunas curtas.
ISENTAS = {
    os.path.join('clinical', 'summary.html'),
    os.path.join('documents', 'request_detail.html'),
    os.path.join('documents', 'verify.html'),
}
soltas = []
total = 0
for pasta, _, arquivos in os.walk(RAIZ_TEMPLATES):
    for nome in sorted(arquivos):
        if not nome.endswith('.html'):
            continue
        caminho = os.path.join(pasta, nome)
        rel = os.path.relpath(caminho, RAIZ_TEMPLATES)
        fonte = ler(caminho)
        for m in re.finditer(r'<table\b', fonte):
            total += 1
            antes = fonte[max(0, m.start() - 500):m.start()]
            if 'table-responsive' in antes:
                continue
            if rel in ISENTAS:
                continue
            soltas.append(f'{rel}:{fonte[:m.start()].count(chr(10)) + 1}')
print(f'  tabelas no produto: {total} | isentas: {len(ISENTAS)} arquivo(s)')
print(f'  sem .table-responsive: {soltas or "nenhuma"}')
if soltas:
    falhas.append(f'tabela sem .table-responsive: {soltas}')

print()
print('=' * 66)
print('4. CALHA GRANDE SEM VARIANTE RESPONSIVA')
print('=' * 66)

# `g-5` numa `row` vira margem negativa de 24px de cada lado; a folga do
# `container` e de 12px. Num celular de 390px a linha passa da tela e a
# pagina rola na horizontal — foi o que acontecia na pagina de vendas.
largas = []
for pasta, _, arquivos in os.walk(RAIZ_TEMPLATES):
    for nome in sorted(arquivos):
        if not nome.endswith('.html'):
            continue
        caminho = os.path.join(pasta, nome)
        rel = os.path.relpath(caminho, RAIZ_TEMPLATES)
        for n, linha in enumerate(io.open(caminho, encoding='utf-8'), 1):
            if 'row' not in linha:
                continue
            # `g-5` cru, sem um `g-<bp>-` ao lado que o torne condicional
            if re.search(r'\bg-5\b', linha) and not re.search(r'\bg-(sm|md|lg|xl|xxl)-\d\b', linha):
                largas.append(f'{rel}:{n}')
print(f'  linhas com g-5 sem variante: {largas or "nenhuma"}')
if largas:
    falhas.append(f'`g-5` sem variante responsiva (transborda no celular): {largas}')

print()
print('=' * 66)
print('7. `hidden` ESCONDE MESMO, E NAO SO NO ATRIBUTO')
print('=' * 66)
#
# O tema traz `[hidden]{display:none!important}` e, dez mil linhas depois,
# `.d-flex{display:flex!important}`. Mesma especificidade, os dois
# `!important`: vence o ultimo, e um elemento com `hidden` **e** `d-flex`
# fica visivel.
#
# Isto ja aconteceu: a faixa "ha um rascunho nao salvo" do atendimento
# nascia visivel para todo mundo, com dois botoes que nao faziam nada --
# o JavaScript so liga os cliques quando encontra rascunho de verdade, e
# ali nao havia nenhum. Quem via a tela nao tinha como ligar um sintoma ao
# outro, nem suspeitar de CSS.
CSS_DURALUX = 'static/duralux/duralux.css'

tema = ler(CSS_DURALUX)
proprio = ler(CSS_TEMA)

# 1. O tema realmente derruba o `hidden` depois de o declarar?
pos_hidden = tema.find('[hidden]{display:none!important}')
conflitos = [
    m.group(0) for m in re.finditer(r'\.d-[a-z-]*\{display:[^};]+!important\}', tema)
    if m.start() > pos_hidden >= 0
]
print(f'  regras de display que vencem o [hidden] do tema: {len(conflitos)}')
if not conflitos:
    print('  (o tema mudou; a regra de resgate abaixo pode ter deixado de ser necessaria)')

# 2. O resgate esta no CSS que carrega por ultimo?
resgate = re.search(r'\[hidden\]\s*\{[^}]*display:\s*none\s*!important', proprio)
print(f'  neurodoc.css devolve o significado do atributo: {bool(resgate)}')
if conflitos and not resgate:
    falhas.append(
        'o tema derruba [hidden] e neurodoc.css nao o restaura: '
        'elemento com hidden + classe de display aparece na tela'
    )

# 3. Alguma folha carregada DEPOIS torna a derrubar o atributo?
#
#    Exigir que `neurodoc.css` seja a ultima seria rigido demais -- o
#    `head` carrega o CSS do chat e o do catalogo depois dele, por boas
#    razoes. O que nao pode e uma dessas folhas trazer `display` com
#    `!important` num seletor que empate com `[hidden]`, porque ai o
#    resgate volta a perder pela ordem.
head = ler('templates/partials/head.html')
folhas = re.findall(r"static '([^']+\.css)'", head)
print(f'  ordem das folhas: {folhas}')
depois = folhas[folhas.index('duralux/neurodoc.css') + 1:] if 'duralux/neurodoc.css' in folhas else []
for folha in depois:
    caminho = os.path.join('static', folha)
    if not os.path.exists(caminho):
        continue
    # Comentarios fora antes de ler seletor: o `/* ... */` que precede uma
    # regra entraria no grupo e viraria um nome de seletor de tres linhas.
    limpo = re.sub(r'/\*.*?\*/', '', ler(caminho), flags=re.S)
    perigosas = []
    for seletor, valor in re.findall(r'([^{}]+)\{[^}]*display:\s*([a-z-]+)[^};]*!important', limpo):
        seletor = ' '.join(seletor.split())
        # `display:none!important` num seletor com `[hidden]` esta do MESMO
        # lado: e outro resgate pontual, como o que o chat da equipe ja
        # fazia para a propria janela antes de a regra geral existir.
        if valor == 'none' or '[hidden]' in seletor:
            continue
        perigosas.append(f'{seletor} -> display:{valor}')
    print(f'  {folha}: regras que venceriam o [hidden] = {perigosas or "nenhuma"}')
    if perigosas:
        falhas.append(
            f'{folha} vem depois de neurodoc.css e mostra o que deveria estar '
            f'escondido ({perigosas})'
        )

# 4. E nenhum template combina os dois contando com a sorte.
combinam = []
for caminho in sorted(pathlib.Path(RAIZ_TEMPLATES).rglob('*.html')):
    texto = ler(str(caminho))
    for tag in re.findall(r'<[a-zA-Z][^>]*\bhidden\b[^>]*>', texto, re.S):
        if re.search(r'\bd-(flex|block|grid|inline-flex|inline-block)\b', tag):
            combinam.append(str(caminho).replace(chr(92), '/'))
print(f'  templates com hidden + classe de display: {sorted(set(combinam)) or "nenhum"}')
# Nao e falha: com o resgate no lugar, a combinacao funciona. Fica listado
# porque e onde o defeito reaparece se alguem mexer na ordem das folhas.

print()
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o bloco de toque esta no lugar e pergunta pelo dedo, os campos vao a 16px,')
print('    o alvo de toque chega a 40px, a barra de acoes quebra linha, e nenhuma')
print('    tabela ou calha larga empurra a pagina para o lado.')
