"""Dispositivo confiável: entrar sem o código, sem prazo, com a clínica decidindo.

O que este roteiro tenta quebrar (`accounts/dispositivo_confiavel.py`):

- a clínica nasce **proibindo**, e a tela do código não oferece a opção;
  a caixa forjada num POST não cria nada;
- permitir pede ciência **e** o código recente; proibir é um clique e
  revoga os dispositivos da equipe — e permitir de novo não os ressuscita;
- confiar grava o termo inteiro, versão e hash, e põe o cookie só em
  `/accounts/`, `HttpOnly`;
- no dispositivo confiável a senha basta, a entrada vai para a trilha
  marcada, e o código recente **não** é carimbado (assinar, certificados,
  exportação, TISS continuam pedindo);
- outro navegador, cookie de outra pessoa, token errado, cookie quebrado:
  código pedido, sem erro 500;
- quem atende numa clínica que proíbe não usa, mesmo com a outra
  permitindo; superadministrador e equipe técnica nunca;
- senha trocada, segundo fator refeito e reset pelo responsável revogam,
  cada um com o seu motivo;
- Minha conta revoga só o que é da pessoa, só por POST;
- e a tela de configurar mostra só a chave, com o nome do sistema no QR.

Tudo numa transação desfeita no fim.
"""
import re
import uuid

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import dispositivo_confiavel as dc
from accounts import mfa
from accounts.models import DispositivoConfiavel, User
from audit.models import AuditEvent
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []
CHR = chr(10)
SENHA = 'Senha-forte-123!'


def conferir(rotulo, condicao, detalhe=''):
    print(f'  {"ok " if condicao else "FALHA"}  {rotulo}' + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        falhas.append(rotulo)


class Desfazer(Exception):
    pass


def nova_clinica(nome):
    return Tenant.objects.create(
        legal_name=nome, slug=f'disp-{uuid.uuid4().hex[:10]}',
        cpf=str(uuid.uuid4().int)[:11],
    )


def nova_pessoa(rotulo, tenant, papeis, *, totp_conf=True):
    user = User.objects.create_user(email=f'{rotulo}-{uuid.uuid4().hex[:6]}@example.com', password=SENHA)
    user.email_verified_at = timezone.now()
    user.save(update_fields=['email_verified_at'])
    vincular(user, tenant, papeis)
    if totp_conf:
        TOTPDevice.objects.create(user=user, confirmed=True, name='roteiro')
    return user


def vincular(user, tenant, papeis):
    return Membership.objects.create(
        tenant=tenant, user=user, roles=papeis, status=MembershipStatus.ACTIVE, activated_at=timezone.now(),
    )


def codigo(user):
    dev = mfa.get_confirmed_device(user)
    TOTPDevice.objects.filter(id=dev.id).update(last_t=-1, throttling_failure_count=0)
    dev.refresh_from_db()
    return f'{totp(dev.bin_key, dev.step, dev.t0, dev.digits, dev.drift):0{dev.digits}d}'


def senha(client, user, valor=SENHA):
    return client.post(reverse('accounts:login'), {'username': user.email, 'password': valor})


def entrou(client):
    return '_auth_user_id' in client.session


def eventos(acao, **filtros):
    return AuditEvent.objects.filter(action=acao, **filtros)


def na_clinica(client, user, tenant):
    client.force_login(user)
    sessao = client.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()


try:
    with transaction.atomic():
        clinica_a = nova_clinica('Clínica A do roteiro')
        clinica_b = nova_clinica('Clínica B do roteiro')
        dona_a = nova_pessoa('dona-a', clinica_a, [Role.OWNER])
        medico = nova_pessoa('medico', clinica_a, [Role.DOCTOR])
        colega = nova_pessoa('colega', clinica_a, [Role.DOCTOR])

        print(CHR + '1. A clínica nasce proibindo')
        campo = Tenant._meta.get_field('dispositivo_confiavel_permitido')
        conferir('padrão False no Python e no banco', campo.default is False and campo.db_default is False)
        conferir('clínica nova proíbe', not Tenant.objects.get(id=clinica_a.id).dispositivo_confiavel_permitido)
        conferir('a política recusa', not dc.politica_permite(medico))

        print(CHR + '2. Proibido: a tela não oferece, e o POST forjado não cria nada')
        c = Client()
        r = senha(c, medico)
        conferir('a senha leva ao código', r.status_code == 302 and r['Location'].endswith(reverse('accounts:mfa-challenge')))
        r = c.get(reverse('accounts:mfa-challenge'))
        html = r.content.decode()
        conferir('sem a caixa nem o termo', 'confiar_dispositivo' not in html and 'TERMO DE CONFIANÇA' not in html)
        r = c.post(reverse('accounts:mfa-challenge'), {'code': codigo(medico), 'confiar_dispositivo': 'sim'})
        conferir('entra com o código', entrou(c))
        conferir('nenhum dispositivo criado', not DispositivoConfiavel.objects.filter(user=medico).exists())
        conferir('nenhum cookie', dc.COOKIE not in r.cookies)

        print(CHR + '3. Permitir pede ciência e código recente; fica na trilha')
        dono = Client()
        na_clinica(dono, dona_a, clinica_a)
        url_politica = reverse('tenancy:dispositivo-confiavel')
        r = dono.get(reverse('tenancy:team'))
        conferir('Equipe mostra o cartão, proibido', r.status_code == 200 and 'Dispositivo confiável' in r.content.decode() and 'proibido' in r.content.decode())
        r = dono.post(url_politica, {'permitir': 'sim'})
        conferir('sem a ciência, continua proibido', not Tenant.objects.get(id=clinica_a.id).dispositivo_confiavel_permitido)
        r = dono.post(url_politica, {'permitir': 'sim', 'ciente': 'sim'})
        conferir('sem código recente, vai à reconfirmação', r.status_code == 302 and reverse('accounts:mfa-confirm') in r['Location'], r.get('Location'))
        conferir('e continua proibido', not Tenant.objects.get(id=clinica_a.id).dispositivo_confiavel_permitido)
        sessao = dono.session
        sessao[mfa.RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
        sessao.save()
        dono.post(url_politica, {'permitir': 'sim', 'ciente': 'sim'})
        conferir('com os dois, permitido', Tenant.objects.get(id=clinica_a.id).dispositivo_confiavel_permitido)
        conferir('na trilha, com quem', eventos('tenancy.dispositivo_confiavel_permitido', tenant_id=clinica_a.id, actor_id=dona_a.id).count() == 1)
        r = dono.get(url_politica)
        conferir('GET não muda nada (405)', r.status_code == 405)
        medico_secretaria = Client()
        na_clinica(medico_secretaria, medico, clinica_a)
        r = medico_secretaria.post(url_politica, {'permitir': 'nao'})
        conferir('médico não decide pela clínica', r.status_code in (403, 404) and Tenant.objects.get(id=clinica_a.id).dispositivo_confiavel_permitido, r.status_code)

        print(CHR + '4. Confiar: termo inteiro, versão, hash, cookie só em /accounts/')
        navegador = Client(HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/131.0 Safari/537.36')
        senha(navegador, medico)
        html = navegador.get(reverse('accounts:mfa-challenge')).content.decode()
        conferir('a caixa e o termo aparecem', 'confiar_dispositivo' in html and 'TERMO DE CONFIANÇA DE DISPOSITIVO' in html)
        conferir('o rótulo diz que é aceite', 'Li e aceito o termo' in html)
        r = navegador.post(reverse('accounts:mfa-challenge'), {'code': codigo(medico), 'confiar_dispositivo': 'sim'})
        disp = DispositivoConfiavel.objects.filter(user=medico).first()
        conferir('dispositivo criado e ativo', disp is not None and disp.ativo)
        conferir('termo inteiro, versão e hash', disp.termo_texto == dc.TERMO_TEXTO and disp.termo_versao == dc.TERMO_VERSAO and disp.termo_sha256 == dc.TERMO_SHA256)
        conferir('o hash é do texto', __import__('hashlib').sha256(disp.termo_texto.encode()).hexdigest() == disp.termo_sha256)
        conferir('navegador descrito', disp.descricao == 'Chrome no Windows', disp.descricao)
        conferir('o token não está no banco', r.cookies[dc.COOKIE].value.split('.', 1)[1] not in (disp.token_hash, disp.senha_marca))
        morsel = r.cookies.get(dc.COOKIE)
        conferir('cookie em /accounts/, HttpOnly, Lax', morsel['path'] == '/accounts/' and morsel['httponly'] and morsel['samesite'] == 'Lax')
        conferir('cookie com o teto do navegador', int(morsel['max-age']) == dc.COOKIE_SEGUNDOS)
        conferir('o aceite na trilha, sem conteúdo', eventos('accounts.dispositivo_confiado', object_id=disp.id).filter(
            integrity_metadata__termo_sha256=dc.TERMO_SHA256).count() == 1)

        print(CHR + '5. No dispositivo confiável a senha basta, e o código recente não é carimbado')
        navegador.logout()
        navegador.cookies[dc.COOKIE] = morsel.value
        r = senha(navegador, medico)
        conferir('entra só com a senha', entrou(navegador) and r.status_code == 302 and reverse('accounts:mfa-challenge') not in r['Location'])
        conferir('sessão verificada (django-otp)', 'otp_device_id' in navegador.session)
        conferir('código recente NÃO carimbado', mfa.RECENT_MFA_SESSION_KEY not in navegador.session)
        conferir('cookie renovado', dc.COOKIE in r.cookies)
        conferir('entrada na trilha, marcada', eventos('auth.login', object_id=disp.id, integrity_metadata__mfa='dispositivo_confiavel').count() == 1)
        disp.refresh_from_db()
        conferir('último uso atualizado', disp.ultimo_uso_em is not None)
        # A ação sensível de verdade, pela tela: a responsável entra pelo
        # dispositivo confiável e pede o acervo inteiro. Tem de ir à
        # reconfirmação do código, e nenhuma exportação nasce.
        from reporting.models import ReportExport

        cli_dona = Client()
        senha(cli_dona, dona_a)
        r = cli_dona.post(reverse('accounts:mfa-challenge'), {'code': codigo(dona_a), 'confiar_dispositivo': 'sim'})
        valor_dona = r.cookies[dc.COOKIE].value
        cli_dona = Client()
        cli_dona.cookies[dc.COOKIE] = valor_dona
        senha(cli_dona, dona_a)
        conferir('a responsável entra pelo dispositivo', entrou(cli_dona))
        cli_dona.get(reverse('accounts:tenant-picker'))
        antes = ReportExport.objects.count()
        r = cli_dona.post(reverse('reporting:acervo'), {'acervo': 'acervo_pacientes', 'formato': 'json'})
        conferir('exportar o acervo pede o código', r.status_code == 302 and reverse('accounts:mfa-confirm') in r['Location'], r.status_code)
        conferir('e nenhuma exportação nasce', ReportExport.objects.count() == antes)

        print(CHR + '6. Outro navegador, cookie alheio, token errado, cookie quebrado: pede o código')
        outro = Client()
        senha(outro, medico)
        conferir('outro navegador pede o código', not entrou(outro))
        for rotulo, valor in (
            ('token errado', f'{disp.id}.{"x" * 43}'),
            ('id inexistente', f'{uuid.uuid4()}.abc'),
            ('sem ponto', 'lixo'),
            ('id que não é UUID', "1' OR 1=1.abc"),
            ('token enorme', f'{disp.id}.{"a" * 500}'),
        ):
            cli = Client()
            cli.cookies[dc.COOKIE] = valor
            r = senha(cli, medico)
            conferir(f'{rotulo}: pede o código, sem 500', r.status_code == 302 and not entrou(cli))
        cli = Client()
        cli.cookies[dc.COOKIE] = morsel.value
        senha(cli, colega)
        conferir('o cookie do médico não entra na conta do colega', not entrou(cli))
        conferir('e não revoga o do médico', DispositivoConfiavel.objects.get(id=disp.id).ativo)
        cli = Client()
        cli.cookies[dc.COOKIE] = morsel.value
        senha(cli, medico, 'senha-errada')
        conferir('senha errada com cookie certo não entra', not entrou(cli))

        print(CHR + '7. Várias clínicas: a mais restritiva vence; técnico nunca')
        vinculo_b = vincular(medico, clinica_b, [Role.DOCTOR])
        conferir('com uma clínica proibindo, a política recusa', not dc.politica_permite(medico))
        cli = Client()
        cli.cookies[dc.COOKIE] = morsel.value
        senha(cli, medico)
        conferir('o dispositivo não vale', not entrou(cli))
        html = cli.get(reverse('accounts:mfa-challenge')).content.decode()
        conferir('e a tela não oferece confiar', 'confiar_dispositivo' not in html)
        conferir('o dispositivo não é revogado por isso', DispositivoConfiavel.objects.get(id=disp.id).ativo)
        Membership.objects.filter(id=vinculo_b.id).update(status=MembershipStatus.REVOKED)
        conferir('vínculo revogado não conta', dc.politica_permite(medico))
        User.objects.filter(id=medico.id).update(is_staff=True)
        conferir('equipe técnica nunca', not dc.politica_permite(User.objects.get(id=medico.id)))
        User.objects.filter(id=medico.id).update(is_staff=False, is_superuser=True)
        conferir('superadministrador nunca', not dc.politica_permite(User.objects.get(id=medico.id)))
        User.objects.filter(id=medico.id).update(is_superuser=False)
        sem_vinculo = User.objects.create_user(email=f'solto-{uuid.uuid4().hex[:6]}@example.com', password=SENHA)
        conferir('sem vínculo ativo nenhum, não', not dc.politica_permite(sem_vinculo))

        print(CHR + '8. Minha conta: lista, revoga só o seu, só por POST')
        conta = Client()
        conta.force_login(medico)
        conta.cookies[dc.COOKIE] = morsel.value
        html = conta.get(reverse('accounts:minha-conta')).content.decode()
        conferir('lista o dispositivo e marca este', 'Chrome no Windows' in html and 'este dispositivo' in html)
        url_revogar = reverse('accounts:dispositivo-revogar', args=[disp.id])
        conferir('GET em revogar: 405', conta.get(url_revogar).status_code == 405)
        intruso = Client()
        intruso.force_login(colega)
        conferir('o colega não revoga (404)', intruso.post(url_revogar).status_code == 404 and DispositivoConfiavel.objects.get(id=disp.id).ativo)
        r = conta.post(url_revogar)
        disp.refresh_from_db()
        conferir('revogado pela pessoa', not disp.ativo and disp.revogado_motivo == DispositivoConfiavel.Motivo.PELA_PESSOA)
        conferir('o cookie é apagado', r.cookies.get(dc.COOKIE) is not None and r.cookies[dc.COOKIE].value == '')
        conferir('revogação na trilha com o motivo', eventos('accounts.dispositivo_revogado', object_id=disp.id, integrity_metadata__motivo='pela_pessoa').count() == 1)
        conferir('revogar de novo: 404', conta.post(url_revogar).status_code == 404)
        cli = Client()
        cli.cookies[dc.COOKIE] = morsel.value
        senha(cli, medico)
        conferir('revogado, pede o código', not entrou(cli))

        def confiar_de_novo(user):
            cli = Client()
            senha(cli, user)
            r = cli.post(reverse('accounts:mfa-challenge'), {'code': codigo(user), 'confiar_dispositivo': 'sim'})
            return r.cookies[dc.COOKIE].value, DispositivoConfiavel.objects.filter(user=user, revogado_em=None).latest('created_at')

        valor2, disp2 = confiar_de_novo(medico)
        valor3, disp3 = confiar_de_novo(medico)
        conta.post(reverse('accounts:dispositivos-revogar-todos'))
        conferir('revogar todos', not DispositivoConfiavel.objects.filter(user=medico, revogado_em=None).exists())

        print(CHR + '9. Senha trocada e segundo fator refeito revogam, com o motivo')
        valor4, disp4 = confiar_de_novo(medico)
        medico = User.objects.get(id=medico.id)
        medico.set_password('Outra-senha-forte-456!')
        medico.save()
        cli = Client()
        cli.cookies[dc.COOKIE] = valor4
        senha(cli, medico, 'Outra-senha-forte-456!')
        disp4.refresh_from_db()
        conferir('senha nova: pede o código', not entrou(cli))
        conferir('revogado por senha trocada', disp4.revogado_motivo == DispositivoConfiavel.Motivo.SENHA_TROCADA)
        cli = Client()
        cli.post(reverse('accounts:login'), {'username': medico.email, 'password': 'Outra-senha-forte-456!'})
        r = cli.post(reverse('accounts:mfa-challenge'), {'code': codigo(medico), 'confiar_dispositivo': 'sim'})
        valor5 = r.cookies[dc.COOKIE].value
        disp5 = DispositivoConfiavel.objects.filter(user=medico, revogado_em=None).latest('created_at')
        TOTPDevice.objects.filter(user=medico).delete()
        TOTPDevice.objects.create(user=medico, confirmed=True, name='roteiro-novo')
        cli = Client()
        cli.cookies[dc.COOKIE] = valor5
        cli.post(reverse('accounts:login'), {'username': medico.email, 'password': 'Outra-senha-forte-456!'})
        disp5.refresh_from_db()
        conferir('segundo fator novo: pede o código', not entrou(cli))
        conferir('revogado por segundo fator refeito', disp5.revogado_motivo == DispositivoConfiavel.Motivo.SEGUNDO_FATOR_REFEITO)

        print(CHR + '10. Reset do MFA pelo responsável revoga, com o motivo')
        valor6, disp6 = confiar_de_novo(colega)
        vinculo_colega = Membership.objects.get(user=colega, tenant=clinica_a)
        dono.post(reverse('tenancy:membership-mfa-reset', args=[vinculo_colega.id]), {'code': codigo(dona_a)})
        disp6.refresh_from_db()
        conferir('revogado por reset do responsável', disp6.revogado_motivo == DispositivoConfiavel.Motivo.MFA_RESETADO)
        conferir('na trilha com a clínica e quem resetou', eventos('accounts.dispositivo_revogado', object_id=disp6.id, tenant_id=clinica_a.id, actor_id=dona_a.id).exists())

        print(CHR + '11. Proibir revoga a equipe, e permitir de novo não ressuscita')
        TOTPDevice.objects.create(user=colega, confirmed=True, name='roteiro')
        valor7, disp7 = confiar_de_novo(colega)
        dono.get(reverse('tenancy:team'))
        html = dono.get(reverse('tenancy:team')).content.decode()
        conferir('Equipe mostra quem usa (contagem)', '1 dispositivo' in html)
        dono.post(url_politica, {'permitir': 'nao'})
        disp7.refresh_from_db()
        conferir('proibido', not Tenant.objects.get(id=clinica_a.id).dispositivo_confiavel_permitido)
        conferir('revogado porque a clínica proibiu', disp7.revogado_motivo == DispositivoConfiavel.Motivo.CLINICA_PROIBIU)
        conferir('na trilha, com o total (colega e responsável)', eventos('tenancy.dispositivo_confiavel_proibido', tenant_id=clinica_a.id).filter(integrity_metadata__revogados=2).exists())
        sessao = dono.session
        sessao[mfa.RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
        sessao.save()
        dono.post(url_politica, {'permitir': 'sim', 'ciente': 'sim'})
        disp7.refresh_from_db()
        conferir('permitir de novo não reativa o revogado', not disp7.ativo)

        print(CHR + '12. O banco recusa revogado sem motivo')
        try:
            with transaction.atomic():
                DispositivoConfiavel.objects.filter(id=disp7.id).update(revogado_motivo='')
            conferir('revogado sem motivo recusado', False)
        except IntegrityError:
            conferir('revogado sem motivo recusado', True)

        print(CHR + '13. A trilha não leva token, senha nem termo')
        proibidos = {'token', 'senha', 'termo_texto', 'cookie', 'user_agent'}
        metadados = AuditEvent.objects.filter(action__in=[
            'accounts.dispositivo_confiado', 'accounts.dispositivo_revogado', 'auth.login',
            'tenancy.dispositivo_confiavel_permitido', 'tenancy.dispositivo_confiavel_proibido',
        ], actor_id__in=[medico.id, colega.id, dona_a.id]).values_list('integrity_metadata', flat=True)
        conferir('nenhuma chave proibida', not any(proibidos & set(m or {}) for m in metadados))

        print(CHR + '14. Configurar: só a chave, e o nome do sistema no QR')
        novo = nova_pessoa('novo', clinica_a, [Role.DOCTOR], totp_conf=False)
        cli = Client()
        cli.force_login(novo)
        html = cli.get(reverse('accounts:mfa-setup')).content.decode()
        conferir('a URL otpauth não aparece', 'otpauth://' not in html and 'secret=' not in html)
        pendente = TOTPDevice.objects.get(user=novo, confirmed=False)
        chave = mfa.chave_para_digitar(pendente)
        conferir('a chave em grupos de quatro', re.fullmatch(r'([A-Z2-7]{4} )*[A-Z2-7]{1,4}', chave) is not None and chave in html, chave[:9])
        conferir('o QR traz o emissor', f'issuer={dj_settings.OTP_TOTP_ISSUER}' in pendente.config_url)

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} falha(s):')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('OK: o dispositivo confiável só vale onde a clínica permite, para quem aceitou o termo, e nada mais.')
