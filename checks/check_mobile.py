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
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o bloco de toque esta no lugar e pergunta pelo dedo, os campos vao a 16px,')
print('    o alvo de toque chega a 40px, a barra de acoes quebra linha, e nenhuma')
print('    tabela ou calha larga empurra a pagina para o lado.')
