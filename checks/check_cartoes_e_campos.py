"""Cartões empilhados com a altura do conteúdo, e campos do atendimento que rolam (1.24.1).

Dois pedidos do médico em 2026-10-22, os dois de proporção da tela:

1. **A receita emitida tinha cartões enormes.** `stretch-full`, do tema, é
   `height: calc(100% - 24px)` — feito para cards lado a lado. Empilhados na
   mesma coluna, cada um queria a altura da coluna inteira. A tela de texto
   livre já tinha caído nisso (`check_texto_livre`), corrigida só ali. Agora
   a regra mora no CSS da casa e vale para as 24 telas que usam a classe.
2. **No atendimento, campo que cresce empurra os outros.** A caixa passa a ter
   altura fixa (o `rows` do formulário) e barra de rolagem própria — só dentro
   do atendimento; no resto do sistema ela continua crescendo.

O roteiro confere a regra onde ela mora (CSS e JS servidos) e as duas telas
de verdade: a receita emitida e os dois tipos de atendimento.

    docker compose exec -T app python manage.py shell < checks/check_cartoes_e_campos.py
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.urls import reverse

from accounts.models import User
from clinical.models import Encounter
from documents.models import MedicalDocument
from tenancy.models import Membership

settings.ALLOWED_HOSTS += ['testserver']
settings.SECURE_SSL_REDIRECT = False

falhas = []
ROOT = Path(settings.BASE_DIR)


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


css = (ROOT / 'static/duralux/neurodoc.css').read_text(encoding='utf-8')
app_js = (ROOT / 'static/duralux/app.js').read_text(encoding='utf-8')

print('=== 1. Card esticado com outro card ao lado volta à altura do conteúdo ===')
regra = re.search(
    r'\.card\.stretch\.stretch-full:has\(~ \.card\),\s*\.card ~ \.card\.stretch\.stretch-full\s*\{\s*height:\s*auto;',
    css,
)
conferir('a regra está no CSS da casa, para as duas posições na pilha', regra is not None)
conferir('o CSS da casa carrega depois do tema (senão o tema venceria)',
         (ROOT / 'templates/partials/head.html').read_text(encoding='utf-8').find('duralux/duralux.css')
         < (ROOT / 'templates/partials/head.html').read_text(encoding='utf-8').find('duralux/neurodoc.css'))

print('=== 2. A receita emitida não estica cartão nenhum ===')
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = (Membership.objects.filter(user=user, status='active', roles__contains=['doctor'])
           .order_by('created_at').first())
cliente = Client()
cliente.force_login(user)
sessao = cliente.session
sessao['tenant_id'] = str(vinculo.tenant_id)
sessao.save()
detalhe = (ROOT / 'templates/documents/medical_detail.html').read_text(encoding='utf-8')
conferir('o template não usa stretch-full', 'stretch-full' not in detalhe)
doc = (MedicalDocument.objects.filter(tenant_id=vinculo.tenant_id, physician=vinculo)
       .order_by('-created_at').first())
if doc is not None:
    resposta = cliente.get(reverse('documents:medical-detail', args=[doc.id]))
    conferir('a tela do documento abre', resposta.status_code == 200, resposta.status_code)
    conferir('e sai sem stretch-full', 'stretch-full' not in resposta.content.decode())
else:
    print('  (sem documento na base de demonstração; conferido só o template)')

print('=== 3. No atendimento, o campo rola em vez de crescer ===')
conferir('o autogrow não mexe no campo dentro do atendimento',
         "ROLA_EM_VEZ_DE_CRESCER = '[data-nd-atendimento]'" in app_js
         and 'if (area.closest(ROLA_EM_VEZ_DE_CRESCER)) return;' in app_js)
conferir('e o CSS devolve a barra de rolagem ali (o padrão a esconde)',
         re.search(r'\[data-nd-atendimento\] textarea\.form-control,[^{]*\{\s*overflow-y:\s*auto;', css)
         is not None)
conferir('fora do atendimento, o campo continua crescendo',
         'function autoGrow(area)' in app_js
         and re.search(r'textarea\.form-control-sm\s*\{\s*resize:\s*none;\s*overflow-y:\s*hidden;', css)
         is not None)
for tipo in ('structured', 'free_text'):
    atendimento = (Encounter.objects.filter(tenant_id=vinculo.tenant_id, kind=tipo, status__in=['draft', 'in_progress'])
                   .order_by('-created_at').first())
    if atendimento is None:
        print(f'  ({tipo}: sem atendimento em rascunho na base de demonstração)')
        continue
    corpo = cliente.get(reverse('clinical:detail', args=[atendimento.id])).content.decode()
    inicio = corpo.find('data-nd-atendimento=')
    campos = re.findall(r'<textarea\b', corpo[inicio:])
    conferir(f'{tipo}: os campos de texto estão dentro da marca do atendimento',
             inicio > 0 and len(campos) > 0, f'marca em {inicio}, {len(campos)} campos')

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: cartões empilhados na altura do conteúdo, e campos do atendimento que rolam.')
