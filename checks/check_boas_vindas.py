"""A clinica recem-cadastrada sabe que precisa de um medico?

A clinica nasce so com o responsavel, e o responsavel nao abre prontuario.
Sem aviso, quem cadastrava procurava "Novo atendimento" e nao achava. Este
roteiro tenta quebrar os tres lugares que agora dizem isso:

1. o **e-mail de boas-vindas** sai no cadastro, depois da via do contrato,
   com o aviso do perfil medico, o link absoluto para os primeiros passos
   (de `PUBLIC_BASE_URL`, nao do `Host:`) e o texto de IA e SMS **do plano
   contratado** -- o Gratuito nao pode ler que tem SMS;
2. o e-mail que falha **nao desfaz** o cadastro;
3. o **aviso na tela** aparece para todo vinculo enquanto nao ha medico,
   com o link de Equipe so para quem pode cadastrar, e some quando alguem
   recebe o papel -- inclusive o proprio responsavel;
4. o artigo **Primeiros passos** abre, e o primeiro do manual, entra no
   sitemap, cita os planos lidos de `plans.py`, e a pagina inicial leva a
   ele sem trocar os quatro cartoes que ja mostrava.
"""
import uuid
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver', 'forjado.invalid']
dj_settings.SECURE_SSL_REDIRECT = False
# `mail.outbox` so existe no backend em memoria (mesma razao de `check_contrato`).
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from base.help_content import ARTICLES, article_by_slug
from tenancy import contract
from tenancy.invitations import issue_invitation
from tenancy.models import (
    ContractAcceptance, InvitationPurpose, Membership, MembershipStatus, Role, Tenant,
    TenantStatus,
)
from tenancy.plans import PUBLIC_ORDER, PlanCode, has_clinical_ai, has_sms, plan_label

falhas = []
SUFIXO = '@boasvindas.invalid'
AVISO = 'data-nd-aviso="sem-medico"'


def cnpj_valido(base):
    def dv(numeros, pesos):
        resto = sum(a * b for a, b in zip(numeros, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    n = [int(x) for x in base]
    d1 = dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


CNPJS = {
    PlanCode.FREE: cnpj_valido('556677880001'),
    PlanCode.COMPLETE: cnpj_valido('556677890001'),
    'falha': cnpj_valido('556677900001'),
    'forjado': cnpj_valido('556677910001'),
}


def limpar():
    """Aposenta o que a execucao anterior deixou, sem apagar (ver `check_contrato`)."""
    for clinica in Tenant.objects.filter(cnpj__in=CNPJS.values()):
        ContractAcceptance.objects.filter(tenant=clinica).delete()
        Membership.objects.filter(tenant=clinica).update(status=MembershipStatus.REVOKED, roles=[])
        sufixo = uuid.uuid4().hex[:8]
        clinica.cnpj = f'00{sufixo[:6]}000199'
        clinica.slug = f'aposentada-{sufixo}'
        clinica.legal_name = f'[aposentada pelo roteiro] {clinica.legal_name}'[:255]
        clinica.trade_name = f'[aposentada] {sufixo}'
        clinica.status = TenantStatus.CLOSED
        clinica.save(update_fields=['cnpj', 'slug', 'legal_name', 'trade_name', 'status'])
    for conta in User.objects.filter(email__endswith=SUFIXO):
        conta.email = f'aposentado-{uuid.uuid4().hex[:12]}{SUFIXO}.velho'
        conta.is_active = False
        conta.set_unusable_password()
        conta.save()


def cadastrar(chave, plano, email):
    _, token = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=plano)
    Client().post(f'/signup/{token}/', {
        'email': email,
        'password': 'S3nhaF0rteDeVerdade!2026',
        'password_confirm': 'S3nhaF0rteDeVerdade!2026',
        'legal_name': f'Clinica Boas-Vindas {chave} Ltda',
        'trade_name': f'Boas-Vindas & {chave}',
        'cnpj': CNPJS[chave],
        'contract_version': contract.VERSAO,
        'accept_contract': 'on',
        'declare_powers': 'on',
    })
    return Tenant.objects.filter(cnpj=CNPJS[chave]).first()


def entrar(user, tenant):
    # A conta recem-criada ainda nao confirmou o e-mail, e o middleware
    # devolve 403 antes de desenhar o menu. O roteiro mede o aviso, nao a
    # confirmacao: carimba como se o link tivesse sido aberto.
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=['email_verified_at'])
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


limpar()
url_passos = dj_settings.PUBLIC_BASE_URL.rstrip('/') + reverse(
    'onboarding:help-article', args=['primeiros-passos'],
)

print('=== 1. o e-mail de boas-vindas sai no cadastro, com o texto do plano ===')
clinicas = {}
for plano in (PlanCode.FREE, PlanCode.COMPLETE):
    email = f'dono-{plano}{SUFIXO}'
    mail.outbox = []
    clinica = cadastrar(plano, plano, email)
    clinicas[plano] = clinica
    if clinica is None:
        falhas.append(f'o cadastro no plano {plano} nao criou a clinica')
        continue
    para_o_dono = [m for m in mail.outbox if email in m.to]
    assuntos = [m.subject for m in para_o_dono]
    boas = [m for m in para_o_dono if m.subject.startswith('Boas-vindas ao NeuroDoc')]
    print(f'  {plano}: e-mails ao dono={assuntos}')
    if len(boas) != 1:
        falhas.append(f'{plano}: esperava 1 e-mail de boas-vindas, vieram {len(boas)}')
        continue
    corpo = boas[0].body
    # A via do contrato continua sendo a primeira: `check_contrato` le
    # `para_o_dono[0]` como a via.
    if not para_o_dono[0].subject.startswith('Contrato de ades'):
        falhas.append(f'{plano}: a via do contrato deixou de ser o primeiro e-mail')
    for trecho, motivo in (
        ('perfil médico', 'o aviso do perfil medico'),
        ('Equipe e papéis', 'onde cadastrar o medico'),
        (url_passos, 'o link absoluto para os primeiros passos'),
        ('SMTP) próprio', 'que a campanha exige SMTP proprio'),
        ('Boas-Vindas & ', 'o nome da clinica sem escapar o "&"'),
    ):
        if trecho not in corpo:
            falhas.append(f'{plano}: o e-mail nao traz {motivo}')
    if '&amp;' in corpo:
        falhas.append(f'{plano}: o e-mail de texto saiu com HTML escapado')
    diz_sms = 'SMS nativo' in corpo
    diz_ia = 'IA nativa' in corpo
    print(f'  {plano}: IA nativa={diz_ia} (plano tem={has_clinical_ai(plano)})  '
          f'SMS nativo={diz_sms} (plano tem={has_sms(plano)})')
    if diz_ia != has_clinical_ai(plano) or diz_sms != has_sms(plano):
        falhas.append(f'{plano}: o e-mail promete IA/SMS diferente do que o plano tem')

print('=== 2. Host forjado nao muda o link ===')
_, token = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=PlanCode.FREE)
mail.outbox = []
Client(HTTP_HOST='forjado.invalid').post(f'/signup/{token}/', {
    'email': f'forjado{SUFIXO}', 'password': 'S3nhaF0rteDeVerdade!2026',
    'password_confirm': 'S3nhaF0rteDeVerdade!2026', 'legal_name': 'Forjada Ltda',
    'trade_name': 'Forjada', 'cnpj': CNPJS['forjado'], 'contract_version': contract.VERSAO,
    'accept_contract': 'on', 'declare_powers': 'on',
})
boas = [m for m in mail.outbox if m.subject.startswith('Boas-vindas')]
forjado = any('forjado.invalid' in m.body for m in boas)
print(f'  boas-vindas={len(boas)}  link com o host forjado={forjado}')
if not boas or forjado:
    falhas.append('o link do e-mail seguiu o Host: da requisicao')

print('=== 3. o e-mail que falha nao desfaz o cadastro ===')
# O log da falha e esperado; silenciado para nao parecer erro na saida.
import logging
logging.getLogger('tenancy.boas_vindas').disabled = True
with mock.patch('tenancy.boas_vindas.render_to_string', side_effect=RuntimeError('quebrado')):
    quebrada = cadastrar('falha', PlanCode.FREE, f'falha{SUFIXO}')
logging.getLogger('tenancy.boas_vindas').disabled = False
print(f'  clinica criada com o e-mail quebrado={quebrada is not None}')
if quebrada is None:
    falhas.append('a falha do e-mail de boas-vindas derrubou o cadastro')

print('=== 4. o aviso na tela enquanto nao ha medico ===')
clinica = clinicas.get(PlanCode.COMPLETE)
if clinica is not None:
    dono = User.objects.get(email=f'dono-{PlanCode.COMPLETE}{SUFIXO}')
    vinculo = Membership.objects.get(tenant=clinica, user=dono)
    sec = User.objects.create_user(email=f'sec-{uuid.uuid4().hex[:6]}{SUFIXO}', password=None)
    Membership.objects.create(
        tenant=clinica, user=sec, roles=[Role.SECRETARY],
        status=MembershipStatus.ACTIVE, activated_at=timezone.now(),
    )
    tela = reverse('patients:list')

    def pagina(user):
        r = entrar(user, clinica).get(tela, follow=True)
        return r.status_code, r.content.decode(errors='replace')

    st, html = pagina(dono)
    link_equipe = reverse('tenancy:team') in html.split(AVISO, 1)[-1][:2500] if AVISO in html else False
    print(f'  responsavel: HTTP {st}  aviso={AVISO in html}  link de Equipe={link_equipe}')
    if AVISO not in html:
        falhas.append('o responsavel nao ve o aviso de clinica sem medico')
    elif not link_equipe:
        falhas.append('o aviso nao leva o responsavel a Equipe e papeis')

    st, html = pagina(sec)
    trecho = html.split(AVISO, 1)[-1][:2500] if AVISO in html else ''
    print(f'  secretaria: HTTP {st}  aviso={AVISO in html}  '
          f'link de Equipe={reverse("tenancy:team") in trecho}')
    if AVISO not in html:
        falhas.append('a secretaria nao ve o aviso de clinica sem medico')
    if reverse('tenancy:team') in trecho:
        falhas.append('o aviso oferece Equipe a quem nao pode abri-la')

    # Medico suspenso nao conta: o aviso pergunta por vinculo ativo.
    vinculo.roles = [Role.OWNER, Role.DOCTOR]
    vinculo.status = MembershipStatus.SUSPENDED
    vinculo.save(update_fields=['roles', 'status'])
    from tenancy.limits import has_doctor
    print(f'  com o unico medico suspenso: tem medico={has_doctor(clinica)}')
    if has_doctor(clinica):
        falhas.append('vinculo suspenso contou como medico')

    vinculo.status = MembershipStatus.ACTIVE
    vinculo.save(update_fields=['status'])
    _, html = pagina(dono)
    _, html_sec = pagina(sec)
    print(f'  responsavel virou medico: aviso para ele={AVISO in html}  '
          f'para a secretaria={AVISO in html_sec}')
    if AVISO in html or AVISO in html_sec:
        falhas.append('o aviso continuou depois de a clinica ganhar medico')

    # Outra clinica sem medico nao contamina a que tem.
    outra = clinicas.get(PlanCode.FREE)
    if outra is not None:
        dono_free = User.objects.get(email=f'dono-{PlanCode.FREE}{SUFIXO}')
        r = entrar(dono_free, outra).get(tela, follow=True)
        aviso_outra = AVISO in r.content.decode(errors='replace')
        print(f'  a outra clinica, ainda sem medico: aviso={aviso_outra}')
        if not aviso_outra:
            falhas.append('o medico de uma clinica apagou o aviso da outra')

print('=== 5. o artigo Primeiros passos ===')
artigo = article_by_slug('primeiros-passos')
anonimo = Client()
if artigo is None:
    falhas.append('o artigo primeiros-passos nao existe')
else:
    r = anonimo.get(reverse('onboarding:help-article', args=['primeiros-passos']))
    html = r.content.decode(errors='replace')
    print(f'  HTTP {r.status_code}  primeiro do manual={ARTICLES[0]["slug"] == "primeiros-passos"}')
    if r.status_code != 200:
        falhas.append('o artigo primeiros-passos nao abre')
    if ARTICLES[0]['slug'] != 'primeiros-passos':
        falhas.append('primeiros-passos deixou de ser o primeiro artigo')
    texto = ' '.join(t for t, _, _ in artigo['steps'])
    for trecho in ('Responsável', 'Médico', 'Secretaria', 'Gestor', 'perfil médico',
                   'IA nativa', 'SMS nativo', 'SMTP', 'Comunicação em massa', 'CRM',
                   'certificado'):
        if trecho not in texto:
            falhas.append(f'o artigo nao fala de "{trecho}"')
    for recurso, nome in ((has_clinical_ai, 'IA'), (has_sms, 'SMS')):
        com = [plan_label(c) for c in PUBLIC_ORDER if recurso(c)]
        print(f'  {nome}: planos com={com}')
        if not all(n in texto for n in com):
            falhas.append(f'o artigo nao cita todos os planos com {nome}')
    # Os links internos do artigo levam a artigos que existem.
    import re
    for slug in re.findall(r'\(/ajuda/([a-z-]+)/\)', texto):
        if article_by_slug(slug) is None:
            falhas.append(f'o artigo aponta para /ajuda/{slug}/, que nao existe')
    if '<ul>' not in html:
        falhas.append('a lista de perfis nao virou lista no HTML')

    sitemap = anonimo.get('/sitemap.xml').content.decode()
    if '/ajuda/primeiros-passos/' not in sitemap:
        falhas.append('o artigo nao entrou no sitemap')

print('=== 6. a pagina inicial e a central levam aos primeiros passos ===')
landing = anonimo.get('/').content.decode(errors='replace')
ajuda = anonimo.get(reverse('onboarding:help')).content.decode(errors='replace')
alvo = reverse('onboarding:help-article', args=['primeiros-passos'])
print(f'  na pagina inicial={alvo in landing}  na central={alvo in ajuda}')
if alvo not in landing:
    falhas.append('a pagina inicial nao leva aos primeiros passos')
if alvo not in ajuda:
    falhas.append('a central de ajuda nao leva aos primeiros passos')
for slug in ('paciente', 'agenda', 'atendimento', 'exame'):
    if reverse('onboarding:help-article', args=[slug]) not in landing:
        falhas.append(f'a pagina inicial perdeu o cartao do artigo {slug}')

limpar()
print()
if falhas:
    print('FALHAS:')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('OK: boas-vindas, aviso de clinica sem medico e primeiros passos.')
