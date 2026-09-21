"""O contrato de adesao existe, e o aceite dele vale alguma coisa?

Tenta quebrar. As perguntas sao:

- o texto tem as clausulas que o negocio prometeu, ou so um titulo?
- da para criar uma clinica sem aceitar o contrato?
- o aceite grava **o que** foi aceito, ou so um "sim" sem texto?
- os prazos gravados sao os do contrato (7 dias, 1 ano)?
- uma via chega ao contratante?
- o contrato aparece publicamente, antes de alguem ter conta?
- o console mostra o aceite, e percebe quando o texto muda sem trocar a versao?
- aceite de uma clinica vaza para outra?
"""
import re

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# Mesma razao de `check_landing`: este roteiro afirma sobre `mail.outbox`,
# que so existe no backend em memoria. Com o envio ligado no ambiente, a
# caixa ficaria vazia e o roteiro acusaria um defeito que nao existe.
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from unittest import mock

from django.core import mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from tenancy import contract
from tenancy.contracts import (
    PRAZO_ARREPENDIMENTO_DIAS, _somar_um_ano, enviar_copia, registrar_aceite,
    sha_do_texto,
)
from tenancy.invitations import issue_invitation
from tenancy.models import ContractAcceptance, InvitationPurpose, Tenant
from tenancy.plans import PlanCode
from tenancy.selectors import scope_to_tenant

falhas = []

SUFIXO = '@contrato.invalid'


def cnpj_valido(base):
    def dv(numeros, pesos):
        resto = sum(a * b for a, b in zip(numeros, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    n = [int(x) for x in base]
    d1 = dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


CNPJ_A = cnpj_valido('445566770001')
CNPJ_B = cnpj_valido('445566780001')


def limpar():
    """Aposenta o que a execucao anterior deixou. Nao apaga.

    A clinica criada aqui nao sai do banco, e nao pode sair: a trilha de
    auditoria referencia o inquilino com `PROTECT`, e ela e imutavel de
    proposito -- apagar o evento para conseguir apagar a linha que ele
    referencia troca uma sujeira de teste por um buraco na trilha. Foi a
    licao que o roteiro do console ja tinha ensinado.

    Aposentar e liberar os identificadores unicos (CNPJ, slug, e-mail) e
    tirar os poderes, deixando a organizacao fechada. A proxima execucao
    encontra o caminho livre; a trilha continua inteira.
    """
    import uuid

    from tenancy.models import Membership, MembershipStatus, TenantStatus

    clinicas = list(Tenant.objects.filter(cnpj__in=[CNPJ_A, CNPJ_B]))
    ContractAcceptance.objects.filter(tenant__in=clinicas).delete()
    for clinica in clinicas:
        Membership.objects.filter(tenant=clinica).update(
            status=MembershipStatus.REVOKED, roles=[],
        )
        sufixo = uuid.uuid4().hex[:8]
        # CNPJ e unico; um valor fora da faixa usada aqui devolve o numero
        # ao proximo roteiro sem colidir com clinica de verdade.
        clinica.cnpj = f'00{sufixo[:6]}000199'
        clinica.slug = f'aposentada-{sufixo}'
        clinica.legal_name = f'[aposentada pelo roteiro] {clinica.legal_name}'[:255]
        clinica.trade_name = f'[aposentada] {sufixo}'
        clinica.status = TenantStatus.CLOSED
        clinica.save(update_fields=[
            'cnpj', 'slug', 'legal_name', 'trade_name', 'status',
        ])
    for conta in User.objects.filter(email__endswith=SUFIXO):
        conta.email = f'aposentado-{uuid.uuid4().hex[:12]}@contrato.invalid'
        conta.is_active = False
        conta.is_staff = False
        conta.is_superuser = False
        conta.set_unusable_password()
        conta.save()


limpar()

print('=== 1. o texto tem o que o negocio prometeu ===')
inteiro = contract.texto_simples()
print(f'  versao={contract.VERSAO}  clausulas={len(contract.CLAUSULAS)}  '
      f'caracteres={len(inteiro)}')

# Cada linha e uma promessa que o negocio fez e que precisa estar escrita.
# O padrao casa com a ideia, nao com a frase inteira: reescrever a redacao
# de uma clausula nao pode quebrar o roteiro, apagar a clausula precisa.
obrigatorias = [
    ('arrependimento de 7 dias', r'7 \(sete\) dias corridos'),
    ('nao reembolso apos o prazo', r'n[aã]o gera direito a reembolso'),
    ('vencimento anual na data do aceite', r'anivers[aá]rio do aceite'),
    ('vigencia de 12 meses', r'12 \(doze\) meses'),
    ('clinica e a controladora', r'CONTROLADORA dos dados pessoais'),
    ('NeuroDoc e a operadora', r'a NeuroDoc é a OPERADORA'),
    ('responsabilidade do operador nao e afastada', r'art\.\s*42'),
    ('guarda de 20 anos do prontuario', r'20 \(vinte\) anos'),
    ('exportacao no termino', r'90 \(noventa\) dias'),
    ('prontuario nao e retido como garantia', r'n[aã]o é retido como garantia'),
    ('prazo de aviso de incidente', r'48 \(quarenta e oito\) horas'),
    ('suboperadores', r'suboperadores'),
    ('transferencia internacional', r'art\.\s*33'),
    ('encarregado', r'art\.\s*41'),
    ('foro', r'Fica eleito o foro'),
]
presentes = 0
for rotulo, padrao in obrigatorias:
    if re.search(padrao, inteiro, re.IGNORECASE):
        presentes += 1
    else:
        falhas.append(f'o contrato nao fala de: {rotulo}')
print(f'  clausulas obrigatorias presentes={presentes}/{len(obrigatorias)}')

# Numeracao coerente: a tela numera por posicao, e o texto simples tambem.
# Se as duas contagens divergissem, o e-mail citaria "clausula 9" e a tela
# mostraria outra coisa no lugar.
numeros = re.findall(r'^(\d+)\. [A-ZÀ-Ú]', inteiro, re.MULTILINE)
if [int(x) for x in numeros] != list(range(1, len(contract.CLAUSULAS) + 1)):
    falhas.append(f'a numeracao das clausulas saiu fora de ordem: {numeros}')
else:
    print(f'  numeracao={numeros[0]}..{numeros[-1]}')

# O resumo aponta para clausulas que existem.
for titulo, texto in contract.RESUMO:
    for citada in re.findall(r'cl[aá]usulas? (\d+)(?: e (\d+))?', texto):
        for n in [x for x in citada if x]:
            if not 1 <= int(n) <= len(contract.CLAUSULAS):
                falhas.append(f'o resumo "{titulo}" cita a clausula {n}, que nao existe')

print('=== 2. o hash identifica o texto ===')
sha = sha_do_texto()
print(f'  sha256={sha[:16]}...')
if sha != sha_do_texto():
    falhas.append('o hash do contrato muda entre duas leituras do mesmo texto')
# Mexer numa letra muda o hash -- e e isso que torna o aceite conferivel.
_titulo = contract.TITULO
contract.TITULO = _titulo + ' '
if sha_do_texto() == sha:
    falhas.append('o hash nao mudou depois de o texto mudar')
contract.TITULO = _titulo

print('=== 3. o contrato e publico, antes de alguem ter conta ===')
anonimo = Client()
pagina = anonimo.get('/contrato/')
corpo = pagina.content.decode(errors='replace')
tem_versao = contract.VERSAO in corpo
tem_arrependimento = '7 (sete) dias corridos' in corpo
print(f'  GET /contrato/ -> HTTP {pagina.status_code}  versao={tem_versao}  '
      f'arrependimento={tem_arrependimento}')
if pagina.status_code != 200 or not tem_versao or not tem_arrependimento:
    falhas.append('a pagina publica do contrato nao abre com o texto em vigor')
# Todas as clausulas na pagina, e nao um resumo que se faz passar por contrato.
faltando = [c['titulo'] for c in contract.CLAUSULAS if c['titulo'] not in corpo]
if faltando:
    falhas.append(f'a pagina publica nao mostra as clausulas: {faltando}')
if '/contrato/' not in anonimo.get('/').content.decode(errors='replace'):
    falhas.append('a pagina de vendas nao aponta para o contrato')

print('=== 4. sem aceitar, nao nasce clinica ===')
convite, token = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=PlanCode.BASIC)
dados = {
    'email': f'dono{SUFIXO}',
    'password': 'S3nhaF0rteDeVerdade!2026',
    'password_confirm': 'S3nhaF0rteDeVerdade!2026',
    'legal_name': 'Clinica do Roteiro de Contrato Ltda',
    'trade_name': 'Roteiro Contrato',
    'cnpj': CNPJ_A,
    'contract_version': contract.VERSAO,
}
antes = Tenant.objects.count()
cliente = Client()
sem_aceite = cliente.post(f'/signup/{token}/', dict(dados))     # sem accept_contract
criou = Tenant.objects.count() - antes
avisou = 'aceitar o contrato' in sem_aceite.content.decode(errors='replace')
print(f'  POST sem a caixa marcada -> HTTP {sem_aceite.status_code}  '
      f'clinicas criadas={criou}  avisa={avisou}')
if criou or not avisou:
    falhas.append('o cadastro criou a clinica sem aceite do contrato')
# E o convite nao foi queimado: a pessoa consegue tentar de novo.
convite.refresh_from_db()
if convite.consumed_at is not None:
    falhas.append('o cadastro recusado consumiu o convite')

print('=== 5. versao velha no formulario e recusada ===')
antes = Tenant.objects.count()
r = cliente.post(f'/signup/{token}/', dict(
    dados, accept_contract='on', contract_version='1900-01-01',
))
texto = r.content.decode(errors='replace')
print(f'  POST com versao antiga -> HTTP {r.status_code}  '
      f'clinicas criadas={Tenant.objects.count() - antes}  '
      f'avisa={"foi atualizado" in texto}')
if Tenant.objects.count() != antes or 'foi atualizado' not in texto:
    falhas.append('o cadastro aceitou uma versao de contrato que nao esta no ar')

print('=== 6. aceitando, o aceite fica gravado com o que foi aceito ===')
mail.outbox = []
cliente.post(f'/signup/{token}/', dict(dados, accept_contract='on'))
clinica = Tenant.objects.filter(cnpj=CNPJ_A).first()
aceite = None
if clinica is None:
    falhas.append('o cadastro com aceite nao criou a clinica')
else:
    aceite = ContractAcceptance.objects.filter(tenant=clinica).first()
    print(f'  clinica={clinica.slug}  aceite={"sim" if aceite else "nao"}')

if aceite is None:
    falhas.append('a clinica nasceu sem aceite registrado')
else:
    print(f'  versao={aceite.version}  sha={aceite.text_sha256[:16]}...  '
          f'plano={aceite.plan}  por={aceite.accepted_email}  ip={aceite.source_ip}')
    if aceite.version != contract.VERSAO:
        falhas.append('o aceite gravou uma versao diferente da que esta no ar')
    if aceite.text_sha256 != sha:
        falhas.append('o aceite gravou um hash que nao e o do texto em vigor')
    if aceite.plan != PlanCode.BASIC:
        falhas.append(f'o aceite gravou o plano {aceite.plan}, e o convite era basic')
    if aceite.accepted_email != f'dono{SUFIXO}':
        falhas.append('o aceite nao gravou quem aceitou')

    # Os prazos sao os do contrato, e nao qualquer data.
    # Arredondado, e nao `.days`: `created_at` e gravado pelo banco alguns
    # microssegundos depois de o prazo ser calculado, entao a diferenca e
    # de 6 dias, 23h59min59s -- e `.days` diria 6.
    dias = round((aceite.withdrawal_deadline - aceite.created_at).total_seconds() / 86400)
    anos_ok = aceite.expires_at.date() == _somar_um_ano(aceite.created_at).date()
    print(f'  arrependimento={dias} dia(s)  '
          f'vence em {aceite.expires_at.date()} (esperado={anos_ok})')
    if dias != PRAZO_ARREPENDIMENTO_DIAS:
        falhas.append(f'o prazo de arrependimento gravado foi de {dias} dias')
    if not anos_ok:
        falhas.append('o vencimento gravado nao e o aniversario do aceite')

    print('=== 7. a via chega ao contratante ===')
    aceite.refresh_from_db()
    para_o_dono = [m for m in mail.outbox if f'dono{SUFIXO}' in m.to]
    print(f'  e-mails na caixa={len(mail.outbox)}  '
          f'para o contratante={len(para_o_dono)}  '
          f'emailed_at={"sim" if aceite.emailed_at else "nao"}')
    if not para_o_dono:
        falhas.append('o contratante nao recebeu a via do contrato')
    else:
        via = para_o_dono[0].body
        # A via leva o contrato inteiro, e nao um link para ele: e a prova
        # que fica com quem contratou, e link expira.
        # `texto_simples` escreve os titulos em maiusculas, como e a
        # convencao de contrato; comparar com o titulo como esta no
        # catalogo acusaria as quinze clausulas como faltando.
        sem_clausula = [
            c['titulo'] for c in contract.CLAUSULAS if c['titulo'].upper() not in via
        ]
        tem_hash = aceite.text_sha256 in via
        tem_data = str(aceite.expires_at.year) in via
        print(f'  via: {len(via)} caracteres  hash={tem_hash}  vencimento={tem_data}  '
              f'clausulas faltando={len(sem_clausula)}')
        if sem_clausula or not tem_hash or not tem_data:
            falhas.append('a via enviada ao contratante nao tem o contrato inteiro')
    if aceite.emailed_at is None:
        falhas.append('o envio da via nao ficou registrado no aceite')

    print('=== 8. falha de e-mail nao desfaz o aceite ===')
    with mock.patch('communications.email.send_email',
                    side_effect=RuntimeError('smtp://servidor:senha fora do ar')):
        enviou = enviar_copia(aceite)
    aceite.refresh_from_db()
    print(f'  enviar_copia com SMTP fora -> {enviou}  '
          f'erro guardado={bool(aceite.email_error)}  '
          f'aceite ainda existe={ContractAcceptance.objects.filter(id=aceite.id).exists()}')
    if enviou or not aceite.email_error:
        falhas.append('a falha de envio da via nao ficou registrada')
    if not ContractAcceptance.objects.filter(id=aceite.id).exists():
        falhas.append('a falha de e-mail apagou o aceite')
    if len(aceite.email_error) > 255:
        falhas.append('o erro de e-mail foi guardado alem do limite da coluna')

    print('=== 9. a mesma versao nao e aceita duas vezes ===')
    duplicou = False
    try:
        with transaction.atomic():
            registrar_aceite(clinica, aceite.accepted_by, plan=aceite.plan)
        duplicou = True
    except IntegrityError:
        pass
    print(f'  segundo aceite da mesma versao -> {"passou" if duplicou else "recusado"}')
    if duplicou:
        falhas.append('a mesma clinica aceitou a mesma versao duas vezes')

print('=== 10. aceite de uma clinica nao vaza para outra ===')
_, outro_token = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=PlanCode.FREE)
Client().post(f'/signup/{outro_token}/', {
    'email': f'vizinha{SUFIXO}',
    'password': 'S3nhaF0rteDeVerdade!2026',
    'password_confirm': 'S3nhaF0rteDeVerdade!2026',
    'legal_name': 'Clinica Vizinha do Roteiro Ltda',
    'trade_name': 'Vizinha do Roteiro',
    'cnpj': CNPJ_B,
    'contract_version': contract.VERSAO,
    'accept_contract': 'on',
})
vizinha = Tenant.objects.filter(cnpj=CNPJ_B).first()
if clinica is None or vizinha is None:
    falhas.append('nao deu para montar as duas clinicas da secao de isolamento')
else:
    class Contexto:
        """O minimo que `scope_to_tenant` le: o inquilino corrente."""

        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

    minhas = scope_to_tenant(ContractAcceptance.objects.all(), Contexto(clinica.id))
    dela = scope_to_tenant(ContractAcceptance.objects.all(), Contexto(vizinha.id))
    sem_contexto = scope_to_tenant(ContractAcceptance.objects.all(), None)
    print(f'  aceites visiveis: clinica={minhas.count()}  vizinha={dela.count()}  '
          f'sem contexto={sem_contexto.count()}')
    if minhas.count() != 1 or dela.count() != 1 or sem_contexto.count():
        falhas.append('o escopo por inquilino nao isolou os aceites')
    if set(minhas.values_list('id', flat=True)) & set(dela.values_list('id', flat=True)):
        falhas.append('a mesma linha de aceite apareceu nas duas clinicas')
    # E o plano gravado e o do convite de cada uma, nao o da ultima.
    if dela.first().plan != PlanCode.FREE:
        falhas.append('o aceite da vizinha gravou o plano da outra clinica')

print('=== 11. o console mostra os aceites ===')
su = User.objects.filter(is_superuser=True, is_active=True).first()
if su is None:
    print('  (sem superadministrador nesta instalacao; secao pulada)')
else:
    if not TOTPDevice.objects.filter(user=su, confirmed=True).exists():
        TOTPDevice.objects.create(user=su, name='roteiro-contrato', confirmed=True)
    console = Client()
    console.force_login(su)
    # `force_login` sozinho nao marca `is_verified()`, e o console exige o
    # segundo fator: sem isto a tela responde 404 e o roteiro acusaria a
    # view de nao existir.
    requisicao = type('R', (), {'session': console.session, 'user': su})()
    otp_login(requisicao, TOTPDevice.objects.filter(user=su, confirmed=True).first())
    requisicao.session.save()
    console.cookies['sessionid'] = requisicao.session.session_key
    pagina = console.get('/instalacao/contratos/')
    corpo = pagina.content.decode(errors='replace')
    mostra = clinica is not None and clinica.trade_name in corpo
    print(f'  GET /instalacao/contratos/ -> HTTP {pagina.status_code}  '
          f'mostra a clinica={mostra}  mostra o texto={contract.VERSAO in corpo}')
    if pagina.status_code != 200 or not mostra:
        falhas.append('o console nao lista os aceites de contrato')
    if 'texto confere' not in corpo:
        falhas.append('o console nao confere o hash do texto aceito')

    # O console percebe quando o texto muda sem a versao mudar? E o unico
    # jeito de descobrir que um aceite deixou de ser conferivel.
    _sub = contract.SUBTITULO
    contract.SUBTITULO = _sub + ' (alterado pelo roteiro)'
    corpo = console.get('/instalacao/contratos/').content.decode(errors='replace')
    percebeu = 'texto difere do atual' in corpo
    contract.SUBTITULO = _sub
    print(f'  texto editado sem trocar a versao -> console avisa={percebeu}')
    if not percebeu:
        falhas.append('o console nao percebe texto editado sem troca de versao')

    # Sem MFA o console nao abre -- mesma porta do resto da instalacao.
    sem_mfa = User.objects.filter(
        is_superuser=True, is_active=True,
    ).exclude(totpdevice__confirmed=True).first()
    if sem_mfa is not None:
        outro = Client()
        outro.force_login(sem_mfa)
        r = outro.get('/instalacao/contratos/')
        print(f'  superadministrador sem MFA -> HTTP {r.status_code}')
        if r.status_code == 200:
            falhas.append('a tela de contratos abriu para superadministrador sem MFA')

limpar()

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o contrato existe, e o aceite guarda o que foi aceito, por quem e ate quando.')
