"""Uma pergunta por acao: o modal do sistema, e nunca a caixa do navegador.

Relatado em 2026-10-19: limpar as notificacoes mostrava a caixa do Chrome,
depois o modal do sistema, e de novo a caixa do Chrome. Dois scripts
respondiam ao mesmo `data-nd-confirm` -- `nd-inline.js` com
`window.confirm` e `app.js` com o modal --, e o modal, ao reenviar o
formulario, disparava a caixa de novo.

Roteiro estrutural, porque o defeito e de JavaScript e o cliente de teste
do Django nao executa JavaScript. As perguntas sao:

- o `nd-inline.js` so recorre ao `window.confirm` quando a pagina nao tem
  o modal?
- o modal esta no `base.html` sem condicao, e toda tela com
  `data-nd-confirm` herda do `base.html`?
- nenhum outro `window.confirm`, `window.alert` ou `window.prompt` nasceu
  em template ou script?
"""
import re
from pathlib import Path

from django.conf import settings as dj_settings

falhas = []
BASE = Path(dj_settings.BASE_DIR)


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


print('=== 1. o nd-inline.js cede a pergunta ao modal ===')
inline = (BASE / 'static' / 'duralux' / 'nd-inline.js').read_text(encoding='utf-8')
bloco = inline[inline.index("hasAttribute('data-nd-confirm')"):]
bloco = bloco[:bloco.index('}, true);')]
confere("getElementById('nd-confirm-modal')" in bloco, 'confere se a pagina tem o modal')
confere(bloco.index("getElementById('nd-confirm-modal')") < bloco.index('window.confirm'),
        'e confere antes de chamar o window.confirm')
app = (BASE / 'static' / 'duralux' / 'app.js').read_text(encoding='utf-8')
confere("getElementById('nd-confirm-modal')" in app and "[data-nd-confirm]" in app,
        'o app.js continua fazendo a pergunta no modal')

print('=== 2. o modal existe onde a pergunta e feita ===')
base = (BASE / 'templates' / 'base.html').read_text(encoding='utf-8')
pos = base.index('id="nd-confirm-modal"')
antes = base[:pos]
# Sem condicao: o ultimo `{% if` antes do modal tem de estar fechado.
abertos = len(re.findall(r'{%\s*if\b', antes)) - len(re.findall(r'{%\s*endif\s*%}', antes))
confere(abertos == 0, f'o modal esta no base.html fora de qualquer if ({abertos} aberto)')


def herda_base(caminho, visto=None):
    visto = visto or set()
    if caminho in visto:
        return False
    visto.add(caminho)
    texto = caminho.read_text(encoding='utf-8')
    m = re.search(r'{%\s*extends\s+["\']([^"\']+)["\']', texto)
    if not m:
        return False
    pai = m.group(1)
    if pai == 'base.html':
        return True
    alvo = BASE / 'templates' / pai
    return alvo.exists() and herda_base(alvo, visto)


# Parciais incluidos: quem os inclui e uma tela que herda do base.html.
PARCIAIS = {'partials/header.html', 'scheduling/_booking_modals.html', 'scheduling/_desbloquear.html'}
for t in sorted((BASE / 'templates').rglob('*.html')):
    rel = t.relative_to(BASE / 'templates').as_posix()
    if 'data-nd-confirm' not in t.read_text(encoding='utf-8') or rel == 'base.html':
        continue
    if rel in PARCIAIS or Path(rel).name.startswith('_'):
        print(f'  --    {rel} (parcial; vale o shell de quem o inclui)')
        continue
    confere(herda_base(t), f'{rel} herda do base.html (tem o modal)')

print('=== 3. nenhuma caixa do navegador nova ===')
nativas = []
for raiz, padrao in ((BASE / 'static', '*.js'), (BASE / 'templates', '*.html')):
    for arq in raiz.rglob(padrao):
        if 'design_system' in arq.parts or arq.name.endswith('.min.js'):
            continue
        for n, linha in enumerate(arq.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
            if re.search(r'window\.(confirm|alert|prompt)\s*\(', linha):
                nativas.append(f'{arq.relative_to(BASE).as_posix()}:{n}')
permitidas = [x for x in nativas if x.startswith('static/duralux/nd-inline.js')]
confere(len(permitidas) == 1, f'so a reserva do nd-inline.js ({permitidas})')
confere(nativas == permitidas, f'nenhuma outra caixa nativa ({[x for x in nativas if x not in permitidas]})')

if falhas:
    print(f'\nFALHA: {len(falhas)} problema(s):')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('\nOK: uma pergunta por acao, no modal do sistema.')
