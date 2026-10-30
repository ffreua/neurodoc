"""O TISS só abre com as três chaves, e nunca abre prontuário (1.30, Sprint 1).

Tenta quebrar:

- os quatro planos: só Completo e Personalizado têm `has_tiss`;
- plano com TISS e clínica **não** liberada: nenhuma capacidade TISS;
- clínica liberada no Básico: nenhuma;
- `capabilities_for` sem o argumento: nada de TISS (o padrão só nega);
- nenhuma capacidade TISS traz `READ_CLINICAL` — a secretária continua sem
  prontuário;
- a matriz: secretária prepara, fecha e exporta, não configura; médico
  idem; dono e gestor configuram;
- com as duas chaves da clínica e a da instalação **desligada**: 404 e o
  menu sem o item;
- dez minutos sem uso: a área TISS pede o segundo fator de novo, sem
  derrubar a sessão; reconfirmado, abre;
- a secretária não abre cadastro de configuração (404), por GET nem POST;
- formulário com operadora de outra clínica forjada no POST: recusado, e o
  banco recusa o `INSERT` direto (chave composta);
- o console: ligar exige `LIGAR` e motivo; desligar é um clique; liberar
  clínica exige plano com TISS e motivo; tudo na trilha.

    docker compose exec -T app python manage.py shell < checks/check_tiss_liberacao.py
"""
import atexit

from django.conf import settings as dj_settings
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.mfa import RECENT_MFA_SESSION_KEY
from audit.models import AuditEvent
from patients.models import Insurer
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.permissions import Capability, capabilities_for
from tenancy.plans import PLANS, PlanCode, has_tiss
from tiss import views as tiss_views
from tiss.models import Configuracao, Credenciamento, Prestador

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


clinica = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=clinica.id).order_by('created_at').first()
vinculos = list(Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE).select_related('user'))


def com_papel(papel, sem=()):
    return next((m for m in vinculos if papel in (m.roles or []) and not set(sem) & set(m.roles or [])), None)


dono = com_papel(Role.OWNER)
secretaria = com_papel(Role.SECRETARY, sem=(Role.OWNER, Role.MANAGER, Role.DOCTOR))
medico = com_papel(Role.DOCTOR, sem=(Role.OWNER, Role.MANAGER))
if None in (dono, secretaria, medico, outra):
    print('  (demonstração incompleta; roteiro pulado)')
    raise SystemExit(0)

original = {'plan': clinica.plan, 'tiss_liberado': clinica.tiss_liberado, 'tiss_nota': clinica.tiss_nota}
config = Configuracao.carregar()
config_original = config.ativo


@atexit.register
def restaurar():
    Tenant.objects.filter(id=clinica.id).update(**original)
    Configuracao.objects.filter(id=config.id).update(ativo=config_original)


def estado(plano, liberado, ligado):
    Tenant.objects.filter(id=clinica.id).update(plan=plano, tiss_liberado=liberado)
    Configuracao.objects.filter(id=config.id).update(ativo=ligado)


def cliente(quem, mfa_recente=True):
    c = Client(SERVER_NAME='localhost')
    c.force_login(quem.user)
    sessao = c.session
    sessao['tenant_id'] = str(clinica.id)
    if mfa_recente:
        sessao[RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
    sessao.save()
    return c


TISS = {Capability.TISS_VIEW, Capability.TISS_PREPARE, Capability.TISS_CLOSE,
        Capability.TISS_EXPORT, Capability.TISS_CONFIGURE}

print('=== 1. Só Completo e Personalizado incluem o TISS ===')
conferir('free sem', not has_tiss(PlanCode.FREE))
conferir('basic sem', not has_tiss(PlanCode.BASIC))
conferir('complete com', has_tiss(PlanCode.COMPLETE))
conferir('custom com', has_tiss(PlanCode.CUSTOM))
conferir('plano desconhecido nega', not has_tiss('inexistente'))
conferir('todo plano declara a chave', all('tiss' in p for p in PLANS.values()))

print('=== 2. A matriz, e nenhuma capacidade TISS abre prontuário ===')
def caps(papeis, contratado=True):
    return capabilities_for(papeis, clinically_enabled=False, ai_contracted=False,
                            tiss_contracted=contratado)

conferir('sem o argumento, nada de TISS',
         not (TISS & capabilities_for([Role.OWNER], clinically_enabled=False, ai_contracted=False)))
conferir('não contratado, nada de TISS', not (TISS & caps([Role.OWNER], False)))
sec = caps([Role.SECRETARY])
conferir('secretária vê, prepara, fecha e exporta',
         {Capability.TISS_VIEW, Capability.TISS_PREPARE, Capability.TISS_CLOSE, Capability.TISS_EXPORT} <= sec)
conferir('secretária não configura', Capability.TISS_CONFIGURE not in sec)
conferir('secretária continua sem prontuário', Capability.READ_CLINICAL not in sec)
conferir('médico não configura', Capability.TISS_CONFIGURE not in caps([Role.DOCTOR]))
conferir('dono configura', Capability.TISS_CONFIGURE in caps([Role.OWNER]))
conferir('gestor configura', Capability.TISS_CONFIGURE in caps([Role.MANAGER]))
conferir('dono não ganha prontuário pelo TISS', Capability.READ_CLINICAL not in caps([Role.OWNER]))

print('=== 3. As três chaves, pela URL ===')
url = '/app/tiss/'
for plano, liberado, ligado, abre, rotulo in (
    (PlanCode.COMPLETE, True, True, True, 'Completo + liberada + ligado'),
    (PlanCode.CUSTOM, True, True, True, 'Personalizado + liberada + ligado'),
    (PlanCode.BASIC, True, True, False, 'Básico liberada'),
    (PlanCode.FREE, True, True, False, 'Gratuito liberada'),
    (PlanCode.COMPLETE, False, True, False, 'Completo não liberada'),
    (PlanCode.COMPLETE, True, False, False, 'Completo liberada com a instalação desligada'),
):
    estado(plano, liberado, ligado)
    r = cliente(dono).get(url)
    conferir(f'{rotulo}: {"abre" if abre else "404"}', (r.status_code == 200) == abre, str(r.status_code))
    menu = cliente(dono).get('/app/patients/')
    tem_item = b'Faturamento TISS' in menu.content
    conferir(f'{rotulo}: menu {"com" if abre else "sem"} o item', tem_item == abre)

print('=== 4. Dez minutos sem uso pedem o segundo fator, só nesta área ===')
estado(PlanCode.COMPLETE, True, True)
c = cliente(dono, mfa_recente=False)
r = c.get(url)
conferir('sem segundo fator recente: vai à reconfirmação',
         r.status_code == 302 and '/accounts/mfa/confirmar/' in r['Location'], r.get('Location', str(r.status_code)))
conferir('e volta para a área TISS', 'next=%2Fapp%2Ftiss%2F' in r.get('Location', ''))
conferir('o resto do sistema continua aberto', c.get('/app/patients/').status_code == 200)
sessao = c.session
sessao[RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
sessao.save()
conferir('reconfirmado, abre', c.get(url).status_code == 200)
sessao = c.session
antigo = (timezone.now() - timezone.timedelta(seconds=tiss_views.INATIVIDADE_MAXIMA_SEGUNDOS + 30)).isoformat()
sessao[tiss_views.ULTIMO_USO_SESSAO] = antigo
sessao[RECENT_MFA_SESSION_KEY] = antigo
sessao.save()
r = c.get(url)
conferir('parado onze minutos: pede de novo', r.status_code == 302, str(r.status_code))
sessao = c.session
sessao[tiss_views.ULTIMO_USO_SESSAO] = (timezone.now() - timezone.timedelta(seconds=120)).isoformat()
sessao[RECENT_MFA_SESSION_KEY] = antigo
sessao.save()
conferir('em uso há dois minutos: segue sem pedir', c.get(url).status_code == 200)

print('=== 5. Configurar é de dono e gestor ===')
conferir('secretária abre a área', cliente(secretaria).get(url).status_code == 200)
conferir('secretária não abre o cadastro de prestador',
         cliente(secretaria).get('/app/tiss/prestadores/novo/').status_code == 404)
r = cliente(secretaria).post('/app/tiss/prestadores/novo/', {'nome': 'X', 'tipo_pessoa': 'pj', 'cnpj': '69887146000105'})
conferir('nem por POST', r.status_code == 404 and not Prestador.objects.filter(tenant=clinica, nome='X').exists())
conferir('médico não abre o cadastro', cliente(medico).get('/app/tiss/credenciamentos/novo/').status_code == 404)

print('=== 6. Fronteira entre clínicas ===')
operadora_alheia = Insurer.objects.create(tenant=outra, name='OPERADORA ROTEIRO ALHEIA', ans_registration='368253')
try:
    c = cliente(dono)
    r = c.post('/app/tiss/prestadores/novo/', {
        'nome': 'PRESTADOR ROTEIRO', 'tipo_pessoa': 'pj', 'cnpj': '12.ABC.345/01DE-35', 'ativo': 'on',
    })
    prestador = Prestador.objects.filter(tenant=clinica, nome='PRESTADOR ROTEIRO').first()
    conferir('prestador com CNPJ alfanumérico gravado', prestador is not None and prestador.cnpj == '12ABC34501DE35',
             str(r.status_code))
    r = c.post('/app/tiss/credenciamentos/novo/', {
        'prestador': prestador.id if prestador else '', 'operadora': operadora_alheia.id,
        'identificacao': 'codigo', 'codigo_na_operadora': '001', 'versao': '4.03.00',
        'ciclo': 'mensal', 'canal': 'xml_portal', 'ativo': 'on',
    })
    conferir('operadora de outra clínica recusada no formulário',
             r.status_code == 200 and not Credenciamento.objects.filter(operadora=operadora_alheia).exists())
    if prestador:
        try:
            with transaction.atomic():
                Credenciamento.objects.create(
                    tenant=clinica, prestador=prestador, operadora=operadora_alheia,
                    codigo_na_operadora='001',
                )
            conferir('o banco recusa o INSERT cruzado', False, 'gravou')
        except IntegrityError:
            conferir('o banco recusa o INSERT cruzado', True)
finally:
    Credenciamento.objects.filter(prestador__nome='PRESTADOR ROTEIRO').delete()
    Prestador.objects.filter(nome='PRESTADOR ROTEIRO').delete()
    operadora_alheia.delete()

print('=== 7. O console ===')
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User


class DesfazerConsole(Exception):
    pass


try:
    with transaction.atomic():
        # Superadministrador descartável, desfeito no fim com o resto: a
        # base de demonstração não tem um, e `force_login` sozinho não marca
        # `is_verified()` — sem o `otp_login` o console devolveria 404 e o
        # roteiro acusaria a view errada (ver `check_contrato`).
        su = User.objects.create_superuser(
            email='su-roteiro-tiss@example.invalid', password=None, email_verified_at=timezone.now(),
        )
        dispositivo = TOTPDevice.objects.create(user=su, name='roteiro-tiss', confirmed=True)
        s = Client(SERVER_NAME='localhost')
        s.force_login(su)
        requisicao = type('R', (), {'session': s.session, 'user': su})()
        otp_login(requisicao, dispositivo)
        requisicao.session.save()
        s.cookies['sessionid'] = requisicao.session.session_key

        estado(PlanCode.COMPLETE, False, False)
        s.post('/instalacao/operacao/tiss/', {'acao': 'ligar', 'confirmacao': 'ligar', 'motivo': 'x'})
        conferir('ligar sem a palavra exata não liga', not Configuracao.carregar().ativo)
        s.post('/instalacao/operacao/tiss/', {'acao': 'ligar', 'confirmacao': 'LIGAR', 'motivo': ''})
        conferir('ligar sem motivo não liga', not Configuracao.carregar().ativo)
        r = s.post('/instalacao/operacao/tiss/', {'acao': 'ligar', 'confirmacao': 'LIGAR', 'motivo': 'roteiro'})
        conferir('com palavra e motivo, liga', Configuracao.carregar().ativo, str(r.status_code))
        s.post('/instalacao/operacao/tiss/', {'acao': 'desligar'})
        conferir('desligar é um clique', not Configuracao.carregar().ativo)
        conferir('as duas mudanças na trilha', AuditEvent.objects.filter(
            actor=su, action__in=['ops.tiss_enabled', 'ops.tiss_disabled']).count() == 2)
        conferir('a tela de Operação mostra o cartão', b'data-nd-tiss-console' in s.get('/instalacao/operacao/').content)
        estado(PlanCode.BASIC, False, False)
        s.post(f'/instalacao/organizacoes/{clinica.id}/tiss/', {'acao': 'liberar', 'tiss_nota': 'roteiro'})
        clinica.refresh_from_db()
        conferir('no Básico não se libera', not clinica.tiss_liberado)
        estado(PlanCode.COMPLETE, False, False)
        s.post(f'/instalacao/organizacoes/{clinica.id}/tiss/', {'acao': 'liberar', 'tiss_nota': ''})
        clinica.refresh_from_db()
        conferir('sem motivo não se libera', not clinica.tiss_liberado)
        s.post(f'/instalacao/organizacoes/{clinica.id}/tiss/', {'acao': 'liberar', 'tiss_nota': 'piloto do roteiro'})
        clinica.refresh_from_db()
        conferir('no Completo, com motivo, libera', clinica.tiss_liberado and clinica.tiss_nota == 'piloto do roteiro')
        s.post(f'/instalacao/organizacoes/{clinica.id}/tiss/', {'acao': 'recolher'})
        clinica.refresh_from_db()
        conferir('recolher é um clique', not clinica.tiss_liberado)
        conferir('quem não é superadministrador não alcança o console',
                 cliente(dono).post('/instalacao/operacao/tiss/', {'acao': 'desligar'}).status_code == 404)
        raise DesfazerConsole
except DesfazerConsole:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Tudo certo.')
