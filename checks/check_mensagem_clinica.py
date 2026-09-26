"""A clinica consegue falar com quem mantem o sistema -- e so isso?

As duas portas do rodape do menu ("Fale com a NeuroDoc" e "Envie
sugestoes") criam um caminho novo de dentro de uma clinica para o console
de quem opera o servidor. Caminho novo entre esses dois mundos e
exatamente onde conteudo clinico vaza, entao a pergunta nao e so "a
mensagem chega": e o que ela carrega junto.

Tenta quebrar. As perguntas sao:

- quem tem vinculo escreve, qualquer que seja o papel? e quem nao tem?
- a mensagem de uma clinica aparece na outra?
- o texto vai parar na trilha de auditoria, que nao deveria guarda-lo?
- tentativa recusada pelo formulario gasta a cota de quem esta errando?
- o console le as duas clinicas, e continua exigindo MFA?
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from django.core.cache import cache
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from tenancy.models import ClinicMessage, ClinicMessageKind, Membership, Tenant

failures = []
criados = []


def confere(condicao, descricao, detalhe=''):
    marca = 'ok  ' if condicao else 'FALHA'
    sufixo = f' ({detalhe})' if detalhe else ''
    print(f'  {marca} {descricao}{sufixo}')
    if not condicao:
        failures.append(descricao)


def entrar(email, slug):
    usuario = User.objects.get(email=email)
    vinculo = Membership.objects.get(user=usuario, tenant__slug=slug)
    cliente = Client()
    cliente.force_login(usuario)
    sessao = cliente.session
    sessao['tenant_id'] = str(vinculo.tenant_id)
    sessao.save()
    return cliente, vinculo


def limpar_cota():
    """A cota vive no Redis por uma hora, e o cliente de teste e sempre a
    mesma pessoa: sem zerar, a segunda execucao comeca no teto."""
    for vinculo in Membership.objects.all()[:20]:
        cache.delete(f'clinic-message:{vinculo.id}')


limpar_cota()

print('=== 1. os dois botoes aparecem para qualquer papel ===')
# Cada papel numa tela que ele de fato abre: pedir o painel de indicadores
# a secretaria devolveria 404, e o teste acusaria os botoes por um motivo
# que nada tem a ver com eles.
for email, rota in [
    ('doctor-b@demo.neurodoc.local', '/app/patients/'),
    ('secretary-a@demo.neurodoc.local', '/app/patients/'),
    ('manager-a@demo.neurodoc.local', '/app/reporting/'),
]:
    cliente, _ = entrar(email, 'demo-clinica-a')
    corpo = cliente.get(rota).content.decode(errors='replace')
    tem_os_dois = 'Fale com a NeuroDoc' in corpo and 'Envie sugestões' in corpo
    confere(tem_os_dois, f'{email.split("@")[0]} ve as duas portas no menu')

print('=== 2. sem vinculo nao ha porta ===')
sem_vinculo = Client()
confere(sem_vinculo.get('/app/mensagem/support/').status_code in (302, 404),
        'quem nao esta autenticado nao alcanca a tela',
        str(sem_vinculo.get('/app/mensagem/support/').status_code))

print('=== 3. tipo desconhecido na URL e 404 ===')
cliente_a, vinculo_a = entrar('secretary-a@demo.neurodoc.local', 'demo-clinica-a')
confere(cliente_a.get('/app/mensagem/qualquer/').status_code == 404,
        'um `kind` inventado na URL nao abre formulario')

print('=== 4. a tela avisa para nao escrever dado de paciente ===')
for kind in ClinicMessageKind.values:
    corpo = cliente_a.get(f'/app/mensagem/{kind}/').content.decode(errors='replace')
    confere('Não escreva dado de paciente' in corpo,
            f'{kind}: a tela avisa sobre dado de paciente')
    confere('type="file"' not in corpo,
            f'{kind}: nao oferece anexo')

print('=== 5. enviar grava na clinica certa, e so nela ===')
antes = ClinicMessage.objects.count()
resposta = cliente_a.post('/app/mensagem/suggestion/', {
    'subject': 'Roteiro: filtrar agenda por convenio',
    'body': 'Texto do roteiro de verificacao, longo o suficiente para passar.',
}, follow=True)
nova = ClinicMessage.objects.order_by('-created_at').first()
criados.append(nova.id)
confere(ClinicMessage.objects.count() == antes + 1, 'a mensagem foi gravada')
confere(nova.tenant_id == vinculo_a.tenant_id, 'gravada na clinica de quem escreveu')
confere(nova.author_id == vinculo_a.id, 'com o vinculo do autor')
confere(nova.kind == ClinicMessageKind.SUGGESTION, 'com o tipo da URL', nova.kind)

# A clinica B nao pode ver a mensagem da A por nenhuma consulta de `/app/`.
cliente_b, vinculo_b = entrar('doctor-a@demo.neurodoc.local', 'demo-clinica-b')
from tenancy.selectors import scope_to_tenant

contexto_b = type('C', (), {'tenant_id': vinculo_b.tenant_id})()
visiveis_em_b = scope_to_tenant(ClinicMessage.objects.all(), contexto_b).count()
confere(visiveis_em_b == 0, 'a clinica B nao enxerga a mensagem da A', str(visiveis_em_b))

print('=== 6. a trilha registra o fato, nunca o texto ===')
evento = (
    AuditEvent.objects.filter(action='tenancy.clinic_message_sent')
    .order_by('-created_at').first()
)
confere(evento is not None, 'a trilha registrou o envio')
if evento is not None:
    tudo = f'{evento.purpose} {evento.integrity_metadata} {evento.object_type}'
    confere('Texto do roteiro' not in tudo, 'o texto da mensagem NAO foi para a trilha')
    confere(evento.integrity_metadata.get('kind') == 'suggestion',
            'a trilha guarda o tipo', str(evento.integrity_metadata))

print('=== 7. tentativa recusada nao gasta a cota de quem erra ===')
limpar_cota()
for _ in range(5):
    cliente_a.post('/app/mensagem/support/', {'subject': 'x', 'body': 'curto'})
antes = ClinicMessage.objects.count()
cliente_a.post('/app/mensagem/support/', {
    'subject': 'Assunto valido depois de errar',
    'body': 'Texto suficiente para passar no minimo exigido.',
}, follow=True)
passou = ClinicMessage.objects.count() == antes + 1
if passou:
    criados.append(ClinicMessage.objects.order_by('-created_at').first().id)
confere(passou, 'cinco tentativas invalidas nao trancam quem acerta na sexta')

print('=== 8. mas a cota vale para envio de verdade ===')
limpar_cota()
antes = ClinicMessage.objects.count()
for i in range(7):
    cliente_a.post('/app/mensagem/support/', {
        'subject': f'Roteiro cota {i}',
        'body': 'Texto suficiente para passar no minimo exigido.',
    }, follow=True)
gravadas = ClinicMessage.objects.count() - antes
criados += list(
    ClinicMessage.objects.filter(subject__startswith='Roteiro cota').values_list('id', flat=True)
)
confere(gravadas <= 4, f'sete envios viraram no maximo quatro', str(gravadas))

print('=== 9. o console le as duas clinicas, e exige MFA ===')
confere(Client().get('/instalacao/mensagens/').status_code == 404,
        'sem MFA o console nao abre')

conta, nova_conta = User.objects.get_or_create(
    email='check-mensagem@example.invalid',
    defaults={'is_active': True, 'is_staff': True, 'is_superuser': True},
)
conta.is_staff = conta.is_superuser = conta.is_active = True
conta.email_verified_at = conta.email_verified_at or timezone.now()
conta.save()
aparelho = (
    TOTPDevice.objects.filter(user=conta, confirmed=True).first()
    or TOTPDevice.objects.create(user=conta, name='roteiro', confirmed=True)
)
console = Client()
console.force_login(conta)
pedido = type('R', (), {'session': console.session, 'user': conta})()
otp_login(pedido, aparelho)
pedido.session.save()
console.cookies['sessionid'] = pedido.session.session_key

# Uma mensagem na clinica B, para o console ter as duas.
vinculo_da_b = Membership.objects.filter(tenant__slug='demo-clinica-b').first()
outra = ClinicMessage.objects.create(
    tenant_id=vinculo_da_b.tenant_id, author=vinculo_da_b,
    kind=ClinicMessageKind.SUPPORT, subject='Roteiro: mensagem da clinica B',
    body='Texto do roteiro.',
)
criados.append(outra.id)

corpo = console.get('/instalacao/mensagens/').content.decode(errors='replace')
confere('Roteiro: filtrar agenda por convenio' in corpo, 'o console mostra a mensagem da clinica A')
confere('Roteiro: mensagem da clinica B' in corpo, 'e a da clinica B')

so_suporte = console.get('/instalacao/mensagens/?kind=support').content.decode(errors='replace')
confere(
    'Roteiro: mensagem da clinica B' in so_suporte
    and 'Roteiro: filtrar agenda por convenio' not in so_suporte,
    'o filtro por tipo separa as duas portas',
)

print('=== limpeza ===')
removidas = ClinicMessage.objects.filter(id__in=criados).delete()[0]
print(f'  mensagens do roteiro removidas: {removidas}')
print('  (os eventos de auditoria ficam -- a trilha nao se apaga)')
if nova_conta:
    TOTPDevice.objects.filter(user=conta).delete()
    if not AuditEvent.objects.filter(actor=conta).exists():
        conta.delete()

print()
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: as duas portas funcionam para qualquer vinculo, a mensagem fica na clinica')
print('    de quem escreveu, e o texto nao vaza para a trilha nem para a clinica vizinha.')
