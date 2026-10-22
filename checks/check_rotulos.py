"""Todo campo de formulário escrito à mão tem nome para o leitor de tela (auditoria de 2026-10, X1).

O exemplo cinza (`placeholder`) não é rótulo: some quando se digita, e o
leitor de tela não o anuncia de forma confiável. Um rótulo visível sem
`for` também não serve — fica ao lado do campo na tela, e para quem não
enxerga o campo continua sem nome. A auditoria achou os dois casos no
console, no portal do paciente, na busca de códigos, no chat e no painel do
SNCR.

A varredura lê os templates e cobra, de cada `<input>`, `<select>` e
`<textarea>` visível, uma destas: `aria-label`, `aria-labelledby`, um
`<label for>` apontando para o `id` dele no mesmo arquivo, ou estar dentro
de um `<label>`. O campo desenhado pelo Django (`{{ form.campo }}`) não
aparece aqui — ele sai com `id`, e o template o rotula com `label_tag`.

E o grupo de opções: o título de um conjunto de botões de rádio é o nome do
grupo, e precisa estar ligado a ele (`role="radiogroup"` com
`aria-labelledby`), senão o leitor anuncia "O próprio paciente" sem dizer
de qual pergunta.

    docker compose exec -T app python manage.py shell < checks/check_rotulos.py
"""
import re
from pathlib import Path

from django.conf import settings

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


raiz = Path(settings.BASE_DIR) / 'templates'
COMENTARIO = re.compile(r'{%\s*comment\s*%}.*?{%\s*endcomment\s*%}|{#.*?#}|<!--.*?-->', re.S)
CAMPO = re.compile(r'<(input|select|textarea)\b([^>]*)>', re.S)
SEM_ROTULO = ('hidden', 'submit', 'button', 'reset', 'image')


def sem_comentarios(texto):
    # Troca o comentário por quebras de linha, para o número da linha continuar certo.
    return COMENTARIO.sub(lambda m: '\n' * m.group(0).count('\n'), texto)


print('=== 1. Campo escrito à mão tem nome ===')
achados = []
total = 0
for caminho in sorted(raiz.rglob('*.html')):
    texto = sem_comentarios(caminho.read_text(encoding='utf-8'))
    alvos_de_for = set(re.findall(r'\bfor="([^"]+)"', texto))
    for m in CAMPO.finditer(texto):
        atributos = m.group(2)
        tipo = re.search(r'\btype="([^"]+)"', atributos)
        if tipo and tipo.group(1) in SEM_ROTULO:
            continue
        total += 1
        if re.search(r'\baria-label(ledby)?=', atributos):
            continue
        ident = re.search(r'\bid="([^"]+)"', atributos)
        if ident and ident.group(1) in alvos_de_for:
            continue
        antes = texto[:m.start()]
        if antes.rfind('<label') > antes.rfind('</label>'):
            continue
        linha = texto.count('\n', 0, m.start()) + 1
        achados.append(f'{caminho.relative_to(raiz)}:{linha}')
conferir(f'{total} campos, nenhum sem nome', not achados, ', '.join(achados))

print('=== 2. Os pontos da auditoria ===')


def ler(rel):
    return (raiz / rel).read_text(encoding='utf-8')


for rel, titulo in (
    ('documents/portal_request.html', 'requester-titulo'),
    ('documents/portal_exames.html', 'requester-titulo'),
    ('ai/relatorio_form.html', 'finalidade-titulo'),
):
    texto = ler(rel)
    conferir(f'{rel}: o grupo de opções tem o título como nome',
             f'role="radiogroup" aria-labelledby="{titulo}"' in texto and f'id="{titulo}"' in texto)
conferir('agenda: os dias da semana formam um grupo com nome',
         'role="group" aria-labelledby="weekdays-titulo"' in ler('scheduling/settings.html'))
cabecalho = ler('partials/header.html')
conferir('cabeçalho: link sem destino que age como botão se declara botão',
         all('role="button"' in m for m in re.findall(r'<a [^>]*href="#"[^>]*>', cabecalho)),
         re.findall(r'<a [^>]*href="#"[^>]*>', cabecalho))

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: todo campo escrito à mão tem nome para o leitor de tela.')
