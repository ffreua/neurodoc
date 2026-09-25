"""Dado do servidor colado dentro de atributo HTML pelo JavaScript.

Nasceu de um defeito real, encontrado na auditoria pre-deploy de
2026-09-24: dois arquivos montavam marcacao por concatenacao e passavam o
valor por um `escapar()` escrito assim --

    var div = document.createElement('div');
    div.textContent = texto;
    return div.innerHTML;

-- que escapa `&`, `<` e `>` e **nao** escapa aspas. A serializacao de um
no de texto nao sabe em que contexto o resultado sera colado, e aspa so
precisa de escape dentro de atributo. O retorno era colado justamente
dentro de um atributo:

    'data-nome="' + escapar(p.full_name) + '"'

Um paciente chamado `Maria" onmouseover="..."` fechava o atributo e o que
vinha depois virava atributo novo do elemento. Provado em navegador real:
antes da correcao o `<button>` saia com um `onmouseover` de verdade; depois
dela, so com `data-nome` contendo o texto literal. Quem grava o nome e a
secretaria; quem executa e o medico que abre a lista. Nao ha CSP que
impeca o manipulador embutido.

Tenta quebrar. As perguntas sao:

- algum arquivo monta atributo HTML por concatenacao?
- se monta, o escapador dele escapa aspa dupla E aspa simples?
- algum arquivo voltou a forma curta, que nao escapa aspas?
- o nome do paciente continua aceitando aspas? (tem de continuar -- a
  correcao e na saida; recusar aspa na entrada quebraria `O'Brien` e
  deixaria passar todo outro consumidor do mesmo dado)
"""
import re

from django.conf import settings

BASE_DIR = settings.BASE_DIR
falhas = []

arquivos = sorted((BASE_DIR / 'static').rglob('*.js'))
print(f'=== 1. {len(arquivos)} arquivo(s) de JavaScript em static/ ===')


def sem_comentario(fonte):
    """Comentarios fora antes de procurar.

    Mesma razao do roteiro do chat da equipe: este arquivo explica em prosa
    a regra que verifica, e uma busca crua acusaria a propria explicacao.
    """
    fonte = re.sub(r'/\*.*?\*/', '', fonte, flags=re.S)
    return re.sub(r'(?m)^\s*//.*$', '', fonte)


#: `algumacoisa="' +` -- abre atributo, fecha a string e concatena valor.
#: E a unica forma que precisa de escape de aspa: `textContent` e
#: `setAttribute` nao tem contexto de parsing e nao precisam de nada.
ATRIBUTO_CONCATENADO = re.compile('[a-zA-Z-]+=["\'][\'"]\\s*\\+')

#: Distingue marcacao de SELETOR CSS. `querySelector('[name="' + n + '"]')`
#: casa com o padrao acima e nao e defeito: o valor vai para um seletor, que
#: nao e analisado como HTML. A diferenca esta no que vem antes -- marcacao
#: de verdade abre uma tag (`'<button ...`). Sem esta segunda pergunta o
#: roteiro acusava `duralux/app.js` e `patients/patient_form.js`, que so
#: montam seletor, e um roteiro que acusa o inocente e desligado na primeira
#: vez que atrapalha.
ABRE_TAG = re.compile('[\'"]\\s*<\\s*[a-zA-Z]')

#: A forma curta, que nao escapa aspas. Procurada pelo CORPO e nao pelo
#: nome: chamar o helper de `escapar` nao o torna seguro.
FORMA_CURTA = re.compile(r'textContent\s*=[^;]+;\s*return\s+\w+\.innerHTML\s*;', re.S)

print('=== 2. quem monta atributo de marcacao por concatenacao ===')
concatenam = []
for caminho in arquivos:
    codigo = sem_comentario(caminho.read_text(encoding='utf-8'))
    ocorrencias = list(ATRIBUTO_CONCATENADO.finditer(codigo))
    if not ocorrencias:
        continue
    monta_html = any(
        ABRE_TAG.search(codigo[max(0, m.start() - 300):m.start()])
        for m in ocorrencias
    )
    if monta_html:
        concatenam.append(caminho)
        print(f'  {caminho.relative_to(BASE_DIR)}')
    else:
        print(f'  {caminho.relative_to(BASE_DIR)} -> so seletor CSS, nao marcacao (ok)')
if not concatenam:
    print('  nenhum monta marcacao (o ideal: setAttribute/textContent em toda parte)')

print('=== 3. quem monta marcacao precisa escapar as duas aspas ===')
for caminho in concatenam:
    codigo = sem_comentario(caminho.read_text(encoding='utf-8'))
    dupla = '&quot;' in codigo or '&#34;' in codigo
    simples = '&#39;' in codigo or '&apos;' in codigo or '&#x27;' in codigo
    print(f'  {str(caminho.relative_to(BASE_DIR)):40} aspa dupla={dupla} aspa simples={simples}')
    if not dupla:
        falhas.append(
            f'{caminho.relative_to(BASE_DIR)} monta atributo por concatenacao e nao '
            f'escapa aspa dupla: um valor com aspa fecha o atributo e injeta outro'
        )
    if not simples:
        falhas.append(
            f'{caminho.relative_to(BASE_DIR)} monta atributo por concatenacao e nao '
            f'escapa aspa simples: quebra se o atributo for delimitado por apostrofo'
        )

print('=== 4. ninguem voltou a forma curta onde ela nao serve ===')
for caminho in arquivos:
    codigo = sem_comentario(caminho.read_text(encoding='utf-8'))
    if not FORMA_CURTA.search(codigo):
        continue
    # A forma curta e CORRETA para contexto de texto. So e defeito no
    # arquivo que tambem monta atributo.
    if caminho in concatenam:
        print(f'  {caminho.relative_to(BASE_DIR)} -> forma curta E monta atributo')
        falhas.append(
            f'{caminho.relative_to(BASE_DIR)} voltou ao escapador que nao escapa aspas'
        )
    else:
        print(f'  {caminho.relative_to(BASE_DIR)} -> forma curta, so em contexto de texto (ok)')

print('=== 5. o nome do paciente continua aceitando aspas ===')
from patients.forms import PatientForm

formulario = PatientForm(data={'full_name': 'Maria " O\'Brien'})
formulario.is_valid()
aceito = 'full_name' not in formulario.errors
print(f'  nome com aspa dupla e simples aceito: {aceito}')
if not aceito:
    falhas.append(
        'o cadastro passou a recusar aspas no nome — a correcao do XSS e na '
        'saida, e recusar na entrada quebra sobrenome legitimo'
    )

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: nenhum dado do servidor escapa de atributo HTML montado no cliente.')
