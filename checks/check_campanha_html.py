"""Comunicacao em massa em HTML com CSS (2026-11-22).

A campanha pode levar um corpo em HTML, para o e-mail chegar bonito. Esse
HTML vai a pacientes com o nome da clinica no remetente, entao o roteiro
tenta quebrar:

1. a limpeza: script, evento, `javascript:` (inclusive escrito com
   entidade), iframe, formulario, CSS que executa ou busca algo, a fuga de
   dentro do `<style>`, imagem fora de `https:`;
2. o rodape obrigatorio, que fica fora do HTML de quem escreve e sobrevive
   a um corpo que tenta escondê-lo;
3. a versao em texto, que sai mesmo sem texto escrito, com os links;
4. o formulario: texto ou HTML, HTML que nao sobra, o teto do Gmail, e o
   que fica gravado ja limpo;
5. o envio: duas partes, o link de descadastro **de cada contato** nas
   duas, nada perigoso no que sai, e a campanha so em texto como antes;
6. as telas: a previa com politica propria e sem script, o quadro so do
   proprio site, outra clinica em 404, a alteracao so em rascunho e com
   trilha, e o teste mandando o HTML.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

import uuid

from django.core import mail
from django.core.mail import get_connection
from django.test import Client
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from communications import email as email_mod
from communications import marketing
from communications.email_html import MAX_HTML, css_seguro, limpar_html, montar_documento, texto_do_html
from communications.forms import MarketingCampaignForm
from communications.models import (
    CampaignStatus, MarketingCampaign, MarketingRecipient, MessagingSettings, RecipientStatus,
)
from patients.models import Patient, PatientContact
from tenancy.models import Tenant

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


def baixo(texto):
    return (texto or '').lower()


print('=== 1. a limpeza do HTML ===')
ataques = {
    'script': '<p>Oi</p><script>alert(1)</script>',
    'evento': '<p onclick="alert(1)">Oi</p><img src="https://x.example/a.png" onerror="alert(1)">',
    'href javascript': '<a href="javascript:alert(1)">clique</a>',
    'href com entidade': '<a href="jav&#x61;script:alert(1)">clique</a>',
    'href com tab': '<a href="java\tscript:alert(1)">clique</a>',
    'iframe': '<p>Oi</p><iframe src="https://x.example"></iframe>',
    'formulario': '<form action="https://x.example"><input name="cpf"><button>ok</button></form><p>Oi</p>',
    'object/embed': '<object data="x.swf"></object><embed src="x.swf"><p>Oi</p>',
    'svg com script': '<svg><script>alert(1)</script></svg><p>Oi</p>',
    'meta refresh': '<meta http-equiv="refresh" content="0;url=https://x.example"><p>Oi</p>',
    'base': '<base href="https://x.example/"><p>Oi</p>',
}
proibido = ('<script', 'onclick', 'onerror', 'javascript', '<iframe', '<form', '<input',
            '<object', '<embed', '<svg', '<meta', '<base', 'alert(1)')
for rotulo, bruto in ataques.items():
    css, corpo = limpar_html(bruto)
    sujo = [p for p in proibido if p in baixo(corpo)]
    confere(not sujo, f'{rotulo}: nada perigoso sobra', ', '.join(sujo))

css, corpo = limpar_html('<p style="color:red; position:fixed; top:0; behavior:url(x.htc); '
                         'background:url(javascript:alert(1)); width:expression(alert(1))">Oi</p>')
confere('color:red' in corpo.replace(' ', ''), 'style: a cor permitida fica', corpo)
for marca in ('position', 'behavior', 'javascript', 'expression'):
    confere(marca not in baixo(corpo), f'style: "{marca}" sai', corpo)

estilo = css_seguro('@import url(https://x.example/a.css); '
                    '.a{color:#123456; background:url(javascript:alert(1))} '
                    '.b{width:expr/**/ession(alert(1))} .c{-moz-binding:url(x)} '
                    '.d{background:url("https://cdn.example/fundo.png")} '
                    '@font-face{font-family:x; src:url(https://x.example/f.woff)} '
                    '@media (max-width:600px){.e{width:100%}}')
confere('@import' not in estilo, '<style>: @import sai', estilo)
confere('javascript' not in baixo(estilo), '<style>: url(javascript:) sai', estilo)
confere('expr' not in baixo(estilo), '<style>: expression() escrito com comentário sai', estilo)
confere('binding' not in estilo, '<style>: -moz-binding sai', estilo)
confere('cdn.example/fundo.png' in estilo, '<style>: url(https:) fica', estilo)
confere('font-face' not in estilo, '<style>: @font-face (fonte remota) sai', estilo)
confere('#123456' in estilo, '<style>: declaração segura da mesma regra fica', estilo)
confere('@media' in estilo, '<style>: @media fica (é o ajuste ao celular)', estilo)

css, corpo = limpar_html('<style>p{color:red}</style><script>x</script></style><script>alert(1)</script><p>Oi</p>')
confere('<' not in css, 'a fuga de dentro do <style> não leva HTML junto', css)
confere('alert' not in corpo and '<script' not in baixo(corpo), 'nem o script depois da fuga')

css, corpo = limpar_html('<img src="http://x.example/a.png" alt="a"><img src="data:image/png;base64,AAAA" alt="b">'
                         '<img src="https://cdn.example/logo.png" alt="Logo"><p>Oi</p>')
confere('http://x.example' not in corpo, 'imagem http: perde o endereço', corpo)
confere('data:image' not in corpo, 'imagem data: perde o endereço', corpo)
confere('https://cdn.example/logo.png' in corpo, 'imagem https: fica', corpo)

css, corpo = limpar_html('<a href="https://clinica.example/campanha" target="_self">Saiba</a><!-- nota -->')
confere('target="_blank"' in corpo and 'noopener' in corpo, 'link abre fora, sem acesso à janela', corpo)
confere('nota' not in corpo, 'comentário sai', corpo)

doc = ('<!DOCTYPE html><html><head><title>t</title><style>.x{color:#abcdef}</style></head>'
       '<body><table width="100%"><tr><td class="x" bgcolor="#eeeeee">Olá</td></tr></table></body></html>')
css, corpo = limpar_html(doc)
confere('#abcdef' in css and '<table' in corpo and 'bgcolor' in corpo,
        'documento inteiro: o <style> do <head> e o corpo de tabela ficam', f'{css} | {corpo}')
confere('<title' not in corpo and '<html' not in corpo, 'documento inteiro: o invólucro sai', corpo)
confere(limpar_html('<script>alert(1)</script><style>p{}</style>') == ('', ''),
        'HTML só com script e estilo não sobra nada')

print('=== 2. o rodapé obrigatório ===')
link = 'https://neurodoc.example/descadastrar/TOKEN-UNICO/'
css, corpo = limpar_html('<style>*{color:#ffffff !important; display:none}</style>'
                         '<div style="display:none">Oi</div>')
documento = montar_documento(css, corpo, 'Clínica <b>A</b> & Cia', link, assunto='Teste')
confere(documento.index(link) > documento.index('Oi'), 'o rodapé vem depois do corpo')
confere('Clínica &lt;b&gt;A&lt;/b&gt; &amp; Cia' in documento, 'o nome da clínica sai escapado')
confere('se descadastrar' in documento, 'o rodapé diz como parar')
rodape = documento[documento.index('<table role="presentation"'):]
confere('color:#555555' in rodape and 'color:#1a56db' in rodape,
        'o rodapé tem cor própria inline (o CSS da campanha não o apaga)')
confere(documento.startswith('<!DOCTYPE html>') and 'charset="utf-8"' in documento,
        'o documento é completo e em UTF-8')

print('=== 3. a versão em texto ===')
texto = texto_do_html('<h1>Vacinação</h1><p>Venha&nbsp;nos ver.</p>'
                      '<p><a href="https://clinica.example/agenda">Marque aqui</a></p><ul><li>Um</li><li>Dois</li></ul>')
confere('Vacinação' in texto and 'Venha nos ver.' in texto, 'o texto do HTML aparece', texto)
confere('Marque aqui (https://clinica.example/agenda)' in texto, 'o link leva o endereço', texto)
confere('<' not in texto, 'sem marca HTML no texto', texto)
confere('\n' in texto, 'blocos viram linhas', texto)

tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=tenant.id).filter(slug__startswith='demo-').first()
ms, _ = MessagingSettings.objects.get_or_create(tenant_id=tenant.id)
CAMPOS = ('email_enabled', 'email_from_name', 'email_from_address', 'smtp_host')
guardado = {f: getattr(ms, f) for f in CAMPOS}
_conexao_original = email_mod._connection_for
email_mod._connection_for = lambda sender: (
    get_connection('django.core.mail.backends.locmem.EmailBackend')
    if sender is not None and sender.uses_own_server else None
)
ms.email_enabled = True
ms.email_from_name = 'Clinica Demo A'
ms.email_from_address = 'contato@clinica-demo.example.com'
ms.smtp_host = 'smtp.x.example.com'
ms.save()

usuario = User.objects.get(email='doctor-a@demo.neurodoc.local')


def cliente():
    c = Client()
    c.force_login(usuario)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


criadas = []
contatos = []
try:
    print('=== 4. o formulário ===')
    HTML = ('<style>.titulo{color:#0a58ca;font-size:22px}</style>'
            '<table width="100%"><tr><td><h1 class="titulo">Campanha de vacinação</h1>'
            '<p>Venha se vacinar.</p><img src="https://cdn.example/logo.png" alt="Logo">'
            '<script>alert(1)</script></td></tr></table>')
    f = MarketingCampaignForm({'subject': 'Só HTML', 'body_html': HTML, 'body_text': '', 'per_minute': 10})
    confere(f.is_valid(), 'só HTML, sem texto, é aceito', f.errors.as_text())
    if f.is_valid():
        confere('<script' not in f.cleaned_data['body_html'] and 'alert' not in f.cleaned_data['body_html'],
                'o que fica gravado já vem limpo')
        confere('.titulo' in f.cleaned_data['body_html'], 'o CSS fica gravado')
    f = MarketingCampaignForm({'subject': 'Vazia', 'body_html': '', 'body_text': '', 'per_minute': 10})
    confere(not f.is_valid() and 'body_text' in f.errors, 'nem texto nem HTML é recusado')
    f = MarketingCampaignForm({'subject': 'Só script', 'body_html': '<script>alert(1)</script>',
                               'body_text': '', 'per_minute': 10})
    confere(not f.is_valid() and 'body_html' in f.errors, 'HTML que não sobra nada é recusado com o motivo')
    f = MarketingCampaignForm({'subject': 'Grande', 'body_html': '<p>' + 'a' * (MAX_HTML + 10) + '</p>',
                               'body_text': '', 'per_minute': 10})
    confere(not f.is_valid() and 'body_html' in f.errors, 'HTML acima do teto do Gmail é recusado')
    f = MarketingCampaignForm({'subject': 'Só texto', 'body_html': '', 'body_text': 'Olá', 'per_minute': 10})
    confere(f.is_valid(), 'só texto continua aceito, como antes', f.errors.as_text())

    print('=== 5. o envio ===')
    paciente = Patient.objects.filter(tenant=tenant, status='active').first()
    for i in (1, 2):
        contatos.append(PatientContact.objects.create(
            tenant=tenant, patient=paciente, name=f'Contato HTML {i}', relationship='self',
            email=f'campanha-html-{i}-{uuid.uuid4().hex[:6]}@example.com', phone='',
            marketing_opt_in_at=timezone.now(), marketing_opt_in_evidence='roteiro check_campanha_html',
        ))
    f = MarketingCampaignForm({'subject': 'Vacinação 2026', 'body_html': HTML, 'body_text': '', 'per_minute': 50})
    assert f.is_valid(), f.errors
    camp = f.save(commit=False)
    camp.tenant = tenant
    camp.save()
    criadas.append(camp)
    marketing.build_recipients(camp)
    meus = {c.email for c in contatos}
    camp.recipients.exclude(contact__email__in=meus).delete()
    confere(camp.recipients.count() == 2, 'a fila tem os dois contatos do roteiro', str(camp.recipients.count()))
    marketing.guard(camp)  # não pode recusar: há HTML, mesmo sem texto
    camp.status = CampaignStatus.SENDING
    camp.save(update_fields=['status'])
    mail.outbox = []
    marketing.send_batch(camp)
    saidas = [m for m in mail.outbox if m.to and m.to[0] in meus]
    confere(len(saidas) == 2, 'saíram duas mensagens', str(len(saidas)))
    # Os links lidos do banco, sem `unsubscribe_url` em objeto velho: ela
    # cria o token quando falta, e criaria um link diferente do que saiu.
    for c_ in contatos:
        c_.refresh_from_db()
    links = {c_.id: marketing.unsubscribe_url(c_) for c_ in contatos}
    for m in saidas:
        contato = next(c for c in contatos if c.email == m.to[0])
        link_dele = links[contato.id]
        alternativas = getattr(m, 'alternatives', [])
        html_saida = alternativas[0][0] if alternativas else ''
        confere(bool(alternativas) and alternativas[0][1] == 'text/html',
                f'{contato.name}: a mensagem tem a parte HTML')
        confere(link_dele in m.body and link_dele in html_saida,
                f'{contato.name}: o link de descadastro DELE está no texto e no HTML')
        outros = [links[c.id] for c in contatos if c.id != contato.id]
        confere(not any(o in html_saida or o in m.body for o in outros),
                f'{contato.name}: sem o link de outro contato')
        confere('Campanha de vacinação' in m.body, f'{contato.name}: o texto foi gerado do HTML')
        confere('<script' not in baixo(html_saida) and 'alert(1)' not in html_saida,
                f'{contato.name}: nada perigoso no HTML que saiu')
        confere('.titulo' in html_saida and 'https://cdn.example/logo.png' in html_saida,
                f'{contato.name}: o CSS e o logotipo chegaram')
        confere(m.extra_headers.get('List-Unsubscribe') == f'<{link_dele}>',
                f'{contato.name}: List-Unsubscribe continua')

    # O que está no banco é relido e limpo de novo no envio: um corpo que
    # entrou por fora do formulário (admin, migração) não sai sujo.
    camp.body_html = '<p>Oi</p><script>alert(2)</script><a href="javascript:alert(3)">x</a>'
    texto, documento = marketing.mensagem_da_campanha(camp, 'https://exemplo.invalid/d/')
    confere('alert' not in documento and 'javascript' not in baixo(documento),
            'HTML gravado por fora do formulário é limpo de novo no envio')

    so_texto = MarketingCampaign.objects.create(tenant=tenant, subject='Só texto', body_text='Olá', per_minute=10)
    criadas.append(so_texto)
    texto, documento = marketing.mensagem_da_campanha(so_texto, 'https://exemplo.invalid/d/')
    confere(documento is None and 'Olá' in texto and 'https://exemplo.invalid/d/' in texto,
            'campanha só em texto: sem HTML, com o rodapé no texto, como antes')

    print('=== 6. as telas ===')
    c = cliente()
    rascunho = MarketingCampaign.objects.create(
        tenant=tenant, subject='Prévia', body_html='<p class="x">Olá</p><style>.x{color:#123}</style>',
        per_minute=10,
    )
    criadas.append(rascunho)
    r = c.get(f'/app/org/campanhas/{rascunho.id}/previa/')
    corpo = r.content.decode()
    politica = r.get('Content-Security-Policy', '')
    confere(r.status_code == 200, 'a prévia abre', str(r.status_code))
    confere("script-src" not in politica and "default-src 'none'" in politica,
            'a prévia tem política própria, sem script', politica)
    confere("frame-ancestors 'self'" in politica and r.get('X-Frame-Options') == 'SAMEORIGIN',
            'a prévia só se deixa emoldurar pelo próprio site')
    confere('img-src https:' in politica, 'a prévia mostra imagem https (o logotipo)')
    confere('se descadastrar' in corpo and 'Olá' in corpo, 'a prévia mostra corpo e rodapé')
    confere('no-store' in r.get('Cache-Control', ''), 'a prévia não fica em cache')

    r = c.get(f'/app/org/campanhas/{rascunho.id}/')
    confere('/previa/' in r.content.decode() and 'sandbox' in r.content.decode(),
            'a tela da campanha mostra a prévia num quadro sandbox')
    confere(f'/campanhas/{rascunho.id}/editar/' in r.content.decode(), 'o rascunho tem "Alterar a mensagem"')

    if outra:
        alheia = MarketingCampaign.objects.create(tenant=outra, subject='Alheia', body_text='x', per_minute=10)
        criadas.append(alheia)
        confere(c.get(f'/app/org/campanhas/{alheia.id}/previa/').status_code == 404,
                'prévia de campanha de outra clínica: 404')
        confere(c.get(f'/app/org/campanhas/{alheia.id}/editar/').status_code == 404,
                'alterar campanha de outra clínica: 404')

    r = c.post(f'/app/org/campanhas/{rascunho.id}/editar/', {
        'subject': 'Prévia alterada', 'body_html': '<p>Novo <b>texto</b></p><script>x</script>',
        'body_text': '', 'per_minute': 12,
    })
    rascunho.refresh_from_db()
    confere(r.status_code == 302 and rascunho.subject == 'Prévia alterada' and '<script' not in rascunho.body_html,
            'alterar o rascunho grava, já limpo', f'{r.status_code} {rascunho.body_html!r}')
    trilha = AuditEvent.objects.filter(action='communications.campaign_edited',
                                       object_id=str(rascunho.id)).first()
    confere(trilha is not None, 'a alteração vai à trilha')
    if trilha:
        meta = str(trilha.integrity_metadata)
        confere('Novo' not in meta and 'texto' not in meta.replace('body_text', ''),
                'a trilha guarda os campos alterados, não o conteúdo', meta)

    camp.refresh_from_db()
    r = c.post(f'/app/org/campanhas/{camp.id}/editar/', {
        'subject': 'Trocada no meio', 'body_html': '<p>x</p>', 'body_text': '', 'per_minute': 10,
    })
    camp.refresh_from_db()
    confere(camp.subject == 'Vacinação 2026', 'campanha que já saiu não é alterada', camp.subject)

    mail.outbox = []
    r = c.post(f'/app/org/campanhas/{rascunho.id}/testar/', {'to_email': 'teste-html@example.com'})
    teste = [m for m in mail.outbox if m.to == ['teste-html@example.com']]
    confere(len(teste) == 1 and getattr(teste[0], 'alternatives', None),
            'o teste manda o HTML', str(len(teste)))
    if teste:
        html_teste = teste[0].alternatives[0][0]
        confere('exemplo.invalid' in html_teste and 'exemplo.invalid' in teste[0].body,
                'o teste leva o link de exemplo, não o de um contato')
finally:
    for camp in criadas:
        MarketingRecipient.objects.filter(campaign=camp).delete()
        MarketingCampaign.objects.filter(id=camp.id).delete()
    for contato in contatos:
        MarketingRecipient.objects.filter(contact=contato).delete()
        PatientContact.objects.filter(id=contato.id).delete()
    for campo, valor in guardado.items():
        setattr(ms, campo, valor)
    ms.save()
    email_mod._connection_for = _conexao_original

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(f'  - {f}')
    raise SystemExit(1)
print('check_campanha_html: tudo ok')
