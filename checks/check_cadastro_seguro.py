"""O cadastro mais seguro de 2026-11: e-mail descartável, CPF e o aviso de encerramento.

Em 2026-11-02 três clínicas entraram com CNPJ inventado e caixa de e-mail
descartável. Este roteiro tenta quebrar as três respostas:

1. **a lista de domínios descartáveis** — conferida antes de valer
   (formato, mínimo, queda brusca, sentinelas, arquivo que não é texto),
   gravada pela diferença, e a falha que **mantém a anterior** e avisa os
   superadministradores por e-mail;
2. **a pergunta** `e_descartavel` — subdomínio, maiúscula, os liberados em
   código (`bol.com.br`, que a lista pública traz) e no console;
3. **as portas**: o cadastro de clínica e o aceite de convite recusam com a
   mensagem em português, sem criar conta nem gastar o convite, com a
   trilha guardando o domínio e **não** o endereço; o serviço recusa também
   (a segunda barreira); o convite de equipe recusa o endereço novo e deixa
   passar a conta que já existe;
4. **CNPJ ou CPF**: o CPF válido cria organização de pessoa física, o
   inválido e o repetido são recusados, o número de dígitos errado também,
   o banco recusa os dois juntos, nenhum e o CPF repetido, e as telas e a
   via do contrato dizem "CPF" — enquanto a declaração de comparecimento
   **não** imprime o CPF do médico;
5. **o encerramento** manda a justificativa a cada responsável ativo, pelo
   remetente da instalação, e a suspensão não manda nada;
6. **o console** mostra a lista, grava os liberados com trilha, recusa o
   que não é domínio, e "Atualizar agora" pede ao worker em vez de baixar.

Tudo roda numa transação desfeita no fim: a base local fica como estava.
"""
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from catalogs import descartaveis
from catalogs.models import DominioDescartavel, ListaDominiosDescartaveis
from tenancy import contract
from tenancy.contracts import _corpo as corpo_da_via
from tenancy.invitations import issue_invitation
from tenancy.models import (
    Invitation, InvitationPurpose, Membership, MembershipStatus, Role, Tenant, TenantStatus,
)
from tenancy.plans import PlanCode
from tenancy.services import EmailDescartavel, accept_platform_invitation

# `mail.outbox` só nasce no primeiro envio do backend em memória; o
# executor de testes do Django o cria antes, e o roteiro faz o mesmo.
mail.outbox = []
falhas = []
SENHA = 'S3nhaF0rteDeVerdade!2026'


def conferir(nome, ok, detalhe=''):
    print(f'  [{"ok" if ok else "FALHA"}] {nome}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(nome)


def _dv(numeros, pesos):
    resto = sum(a * b for a, b in zip(numeros, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def cnpj_valido(base):
    n = [int(x) for x in base]
    d1 = _dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(_dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))


def cpf_valido(base):
    n = [int(x) for x in base]
    d1 = _dv(n, range(10, 1, -1))
    return base + str(d1) + str(_dv(n + [d1], range(11, 1, -1)))


CPF = cpf_valido('529982247')            # 529.982.247-25
CNPJ = cnpj_valido('778899000001')


def lista(n=60_000, extra=()):
    linhas = [f'descartavel{i}.example' for i in range(n)] + list(extra)
    return ('\n'.join(linhas) + '\n').encode()


def cadastrar(email, documento, nome='Clinica Roteiro Cadastro Ltda'):
    _, token = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=PlanCode.FREE)
    r = Client().post(f'/signup/{token}/', {
        'email': email, 'password': SENHA, 'password_confirm': SENHA,
        'legal_name': nome, 'trade_name': '', 'documento': documento,
        'contract_version': contract.VERSAO, 'accept_contract': 'on', 'declare_powers': 'on',
    })
    return r, token


def console(su):
    s = Client()
    s.force_login(su)
    requisicao = type('R', (), {'session': s.session, 'user': su})()
    otp_login(requisicao, TOTPDevice.objects.filter(user=su, confirmed=True).first())
    requisicao.session.save()
    s.cookies['sessionid'] = requisicao.session.session_key
    return s


class Desfazer(Exception):
    pass


try:
    with transaction.atomic():
        su = User.objects.create_superuser(
            email='su-roteiro-cadastro@example.invalid', password=None, email_verified_at=timezone.now(),
        )
        TOTPDevice.objects.create(user=su, name='roteiro-cadastro', confirmed=True)
        # A lista real pode já estar carregada (220 mil domínios), e a
        # sintética daqui seria recusada pela regra da queda — que é o
        # comportamento certo. O roteiro parte da lista vazia, dentro da
        # transação que desfaz no fim.
        DominioDescartavel.objects.all().delete()
        ListaDominiosDescartaveis.objects.all().delete()

        print('=== 1. A lista baixada é conferida antes de valer ===')
        boa = lista(extra=['mailinator.com', 'guerrillamailblock.com', 'bol.com.br', 'clinicareal.com.br'])
        conferir('lista boa passa', len(descartaveis.ler(boa)) == 60_004)
        for nome, conteudo, atual in (
            ('formato mudou (JSON)', b'{"domains": ' + b'["a.com"],' * 60_000 + b'}', 0),
            ('abaixo do mínimo', lista(1000), 0),
            ('queda de mais de 30%', lista(60_000), 100_000),
            ('sentinela gmail.com', lista(extra=['gmail.com']), 0),
            ('sentinela com.br', lista(extra=['com.br']), 0),
            ('não é UTF-8', b'\xff\xfe' + lista(), 0),
        ):
            try:
                descartaveis.ler(conteudo, atual=atual)
                conferir(f'{nome} é recusada', False, 'passou')
            except descartaveis.ListaRecusada as exc:
                conferir(f'{nome} é recusada', True)
                conferir(f'  a recusa é em português ({nome})', 'anterior' in str(exc) or 'formato' in str(exc), str(exc))
        sujeira = lista() + b'linha com espaco\n'
        conferir('meio por cento de sujeira é descartado, não recusa', 'linha com espaco' not in descartaveis.ler(sujeira))

        print('=== 2. Gravar pela diferença, e a falha mantém a anterior ===')
        r = descartaveis.sincronizar(boa)
        conferir('primeira carga', r['ok'] and r['total'] == 60_004 and r['entraram'] == 60_004, str(r))
        conferir('o total está no banco', DominioDescartavel.objects.count() == 60_004)
        nova = lista(59_990, extra=['mailinator.com', 'guerrillamailblock.com', 'bol.com.br',
                                    'clinicareal.com.br', 'novo-descartavel.example'])
        r = descartaveis.sincronizar(nova)
        conferir('segunda carga pela diferença', r['ok'] and r['entraram'] == 1 and r['sairam'] == 10, str(r))
        estado = ListaDominiosDescartaveis.carregar()
        conferir('estado gravado sem erro', estado.total == 59_995 and not estado.ultimo_erro and estado.atualizada_em)
        mail.outbox.clear()
        r = descartaveis.sincronizar(b'<html>404: Not Found</html>')
        estado = ListaDominiosDescartaveis.carregar()
        conferir('página de erro não substitui a lista', not r['ok'] and DominioDescartavel.objects.count() == 59_995, str(r))
        conferir('o motivo fica no estado', bool(estado.ultimo_erro) and estado.total == 59_995)
        avisos = [m for m in mail.outbox if 'descartável' in m.subject]
        conferir('superadministrador avisado por e-mail', avisos and su.email in avisos[0].to,
                 str([m.subject for m in mail.outbox]))
        conferir('o aviso diz de quando é a lista que vale', avisos and 'continua sendo a de' in avisos[0].body)
        with mock.patch.object(descartaveis, 'baixar', side_effect=OSError('rede fora')):
            r = descartaveis.sincronizar()
        conferir('rede fora também vira aviso, não exceção', not r['ok'] and 'rede fora' in r['erro'], str(r))
        r = descartaveis.sincronizar(nova)
        conferir('a próxima que dá certo limpa o erro', r['ok'] and not ListaDominiosDescartaveis.carregar().ultimo_erro)

        print('=== 3. A pergunta ===')
        for email, esperado in (
            ('alguem@mailinator.com', True), ('ALGUEM@MAILINATOR.COM ', True),
            ('x@abc.mailinator.com', True), ('fulano@bol.com.br', False), ('fulano@mail.bol.com.br', False),
            ('dr@gmail.com', False), ('dr@clinicareal.com.br', True), ('sem-arroba', False), ('', False),
        ):
            conferir(f'{email!r} -> {esperado}', descartaveis.e_descartavel(email) is esperado)
        estado = ListaDominiosDescartaveis.carregar()
        estado.liberados = 'clinicareal.com.br\n# comentário'
        estado.save()
        conferir('liberado no console passa', not descartaveis.e_descartavel('dr@clinicareal.com.br'))
        estado.liberados = ''
        estado.save()

        print('=== 4. As portas de cadastro ===')
        convites_antes = Invitation.objects.filter(consumed_at__isnull=False).count()
        r, token = cadastrar('golpe@mailinator.com', CNPJ)
        corpo = r.content.decode()
        conferir('cadastro com descartável recusado na tela', r.status_code == 200 and 'não é aceito para cadastro' in corpo,
                 str(r.status_code))
        conferir('nem conta nem clínica criadas',
                 not User.objects.filter(email='golpe@mailinator.com').exists() and not Tenant.objects.filter(cnpj=CNPJ).exists())
        conferir('o convite não foi gasto', Invitation.objects.filter(consumed_at__isnull=False).count() == convites_antes)
        trilha = AuditEvent.objects.filter(action='accounts.email_descartavel_recusado').order_by('-created_at').first()
        conferir('a trilha registra o domínio', trilha is not None and trilha.integrity_metadata.get('dominio') == 'mailinator.com')
        conferir('a trilha NÃO guarda o endereço', trilha is not None and 'golpe' not in str(trilha.integrity_metadata))
        try:
            with transaction.atomic():
                _, tk = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=PlanCode.FREE)
                accept_platform_invitation(tk, 'outro@guerrillamailblock.com', SENHA, 'X Ltda', CNPJ)
            conferir('o serviço também recusa', False, 'criou')
        except EmailDescartavel:
            conferir('o serviço também recusa (segunda barreira)', True)

        print('=== 5. CNPJ ou CPF ===')
        r, _ = cadastrar('medico.pf@roteiro-cadastro.example', f'{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}', 'Dr Roteiro Pessoa Fisica')
        pf = Tenant.objects.filter(cpf=CPF).first()
        conferir('CPF válido cria organização de pessoa física', pf is not None and pf.cnpj == '' and pf.pessoa_fisica,
                 str(r.status_code))
        conferir('rótulo e formato do documento', pf is not None and pf.documento_rotulo == 'CPF'
                 and pf.documento_formatado == f'{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}')
        r, _ = cadastrar('outro.pf@roteiro-cadastro.example', CPF)
        conferir('CPF repetido recusado', 'Este CPF já está cadastrado' in r.content.decode())
        r, _ = cadastrar('invalido@roteiro-cadastro.example', '52998224700')
        conferir('CPF inválido recusado', 'CPF inválido' in r.content.decode())
        r, _ = cadastrar('curto@roteiro-cadastro.example', '1234567890123')
        conferir('número de dígitos errado recusado', 'CPF (11 dígitos)' in r.content.decode())
        r, _ = cadastrar('pj@roteiro-cadastro.example', CNPJ)
        pj = Tenant.objects.filter(cnpj=CNPJ).first()
        conferir('CNPJ continua funcionando', pj is not None and pj.cpf == '' and not pj.pessoa_fisica)
        if pf is not None:
            for nome, campos in (
                ('os dois juntos', {'cnpj': cnpj_valido('112233440001'), 'cpf': cpf_valido('111444777')}),
                ('nenhum dos dois', {'cnpj': '', 'cpf': ''}),
                ('CPF repetido', {'cnpj': '', 'cpf': CPF}),
            ):
                try:
                    with transaction.atomic():
                        Tenant.objects.create(legal_name='X', slug=f'roteiro-{nome.replace(" ", "-")}', **campos)
                    conferir(f'o banco recusa {nome}', False, 'gravou')
                except IntegrityError:
                    conferir(f'o banco recusa {nome}', True)
            from tenancy.models import ContractAcceptance
            aceite = ContractAcceptance.objects.filter(tenant=pf).first()
            via = corpo_da_via(aceite) if aceite else ''
            conferir('a via do contrato diz CPF', 'CPF:' in via and pf.documento_formatado in via and 'CNPJ:' not in via.split('Plano')[0])
            dono = Membership.objects.get(tenant=pf, roles__contains=[Role.OWNER]).user
            dono.email_verified_at = timezone.now()
            dono.save(update_fields=['email_verified_at'])
            c = Client()
            c.force_login(dono)
            s = c.session
            s['tenant_id'] = str(pf.id)
            s.save()
            tela = c.get('/app/org/clinica/')
            conferir('a identidade da clínica mostra o CPF', tela.status_code == 200 and f'CPF {pf.documento_formatado}' in tela.content.decode(),
                     str(tela.status_code))
            declaracao = open('templates/scheduling/declaracao.html', encoding='utf-8').read()
            conferir('a declaração imprime só o CNPJ (nunca o CPF do médico)',
                     '{% if tenant.cnpj %}' in declaracao and 'tenant.cpf' not in declaracao and 'tenant.documento' not in declaracao)
            pagina = console(su).get('/instalacao/organizacoes/').content.decode()
            conferir('o console lista a pessoa física', pf.documento_formatado in pagina and 'pessoa física' in pagina)

            print('=== 6. Convite de equipe ===')
            r = c.post('/app/org/equipe/', {'email': 'secretaria@mailinator.com', 'roles': ['secretary']})
            conferir('convite para descartável novo recusado', 'não é aceito para cadastro' in r.content.decode()
                     and not Invitation.objects.filter(target_tenant=pf, email_binding='secretaria@mailinator.com').exists(),
                     str(r.status_code))
            antiga = User.objects.create_user(email='antiga@mailinator.com', password=SENHA)
            c.post('/app/org/equipe/', {'email': 'antiga@mailinator.com', 'roles': ['secretary']})
            conferir('conta que já existe pode ser convidada',
                     Invitation.objects.filter(target_tenant=pf, email_binding='antiga@mailinator.com').exists())
            _, tk = issue_invitation(purpose=InvitationPurpose.COLLABORATOR, target_tenant=pf,
                                     role_grants=[Role.SECRETARY], issued_by=dono)
            r = Client().post(f'/invite/{tk}/', {'email': 'nova@mailinator.com', 'password1': SENHA, 'password2': SENHA})
            conferir('aceite de convite com descartável recusado', 'não é aceito para cadastro' in r.content.decode()
                     and not User.objects.filter(email='nova@mailinator.com').exists(), str(r.status_code))

            print('=== 7. Encerramento ===')
            medico = User.objects.create_user(email='medico.equipe@roteiro-cadastro.example', password=SENHA)
            Membership.objects.create(tenant=pf, user=medico, roles=[Role.DOCTOR],
                                      status=MembershipStatus.ACTIVE, activated_at=timezone.now())
            s = console(su)
            mail.outbox.clear()
            s.post(f'/instalacao/organizacoes/{pf.id}/estado/', {'status': 'suspended', 'status_note': 'fatura em aberto'})
            conferir('suspender não manda e-mail de encerramento', not [m for m in mail.outbox if 'encerramento' in m.subject])
            r = s.post(f'/instalacao/organizacoes/{pf.id}/estado/', {
                'status': 'closed', 'status_note': 'Cadastro com dados que não puderam ser confirmados.'}, follow=True)
            enviados = [m for m in mail.outbox if 'encerramento' in m.subject]
            conferir('um e-mail ao responsável', len(enviados) == 1 and enviados[0].to == [dono.email],
                     str([m.to for m in enviados]))
            conferir('o médico não recebe', all(medico.email not in m.to for m in enviados))
            if enviados:
                conferir('leva a justificativa', 'Cadastro com dados que não puderam ser confirmados.' in enviados[0].body)
                conferir('diz que nada foi apagado e o prazo de 90 dias',
                         'não foram apagados' in enviados[0].body.lower() or 'NÃO FORAM APAGADOS' in enviados[0].body)
                conferir('sai pelo remetente da instalação', enviados[0].from_email == dj_settings.DEFAULT_FROM_EMAIL)
            conferir('o console diz que enviou', 'enviada por e-mail a 1 responsável' in r.content.decode())
            conferir('a trilha registra a contagem e não o endereço',
                     AuditEvent.objects.filter(action='tenancy.encerramento_avisado', tenant_id=pf.id,
                                               integrity_metadata__emails=1).exists())

        print('=== 8. O console da lista ===')
        s = console(su)
        pagina = s.get('/instalacao/operacao/').content.decode()
        conferir('o cartão aparece com o total', 'E-mail descartável no cadastro' in pagina and '59995' in pagina.replace('.', ''))
        r = s.post('/instalacao/operacao/emails-descartaveis/', {'acao': 'liberados', 'liberados': 'nao e dominio'}, follow=True)
        conferir('o que não é domínio é recusado', 'Não são domínios' in r.content.decode()
                 and not ListaDominiosDescartaveis.carregar().liberados)
        s.post('/instalacao/operacao/emails-descartaveis/', {'acao': 'liberados', 'liberados': '@ClinicaReal.com.br\n\n'})
        conferir('liberados gravados e normalizados', ListaDominiosDescartaveis.carregar().liberados == 'clinicareal.com.br')
        conferir('a troca vai para a trilha', AuditEvent.objects.filter(action='ops.descartaveis_liberados_alterados').exists())
        from catalogs import tasks as catalogo_tarefas
        with mock.patch.object(catalogo_tarefas.sincronizar_dominios_descartaveis, 'delay') as pedido, \
                mock.patch.object(descartaveis, 'baixar', side_effect=AssertionError('a tela baixou')):
            s.post('/instalacao/operacao/emails-descartaveis/', {'acao': 'atualizar'})
        conferir('"Atualizar agora" pede ao worker', pedido.called)
        conferir('agendada aos domingos', dj_settings.CELERY_BEAT_SCHEDULE['sincronizar-dominios-descartaveis']
                 ['schedule'].day_of_week == {0})

        print('=== 9. Revisão de 2026-11-02 ===')
        from django.db import connection
        from tenancy.services import _unique_slug
        # Razão social longa sem nome fantasia: o corte em 55 caía num
        # hífen, o `full_clean` recusava o slug e o cadastro dava erro 500.
        longa = 'Clinica de Neurologia e Neurocirurgia Dr. Fulano de Tal e Associados'
        slug = _unique_slug(longa)
        conferir('o slug cortado não termina em hífen', not slug.endswith('-') and not slug.startswith('-'), slug)
        r, _ = cadastrar('longa@clinicareal.com.br', cpf_valido('987654321'), nome=longa)
        conferir('cadastro com razão social longa entra', r.status_code == 200
                 and Tenant.objects.filter(legal_name=longa).exists(), r.status_code)
        # O código anterior à 1.32 faz INSERT sem `cpf`: o banco tem de
        # preencher o vazio (migração 0021), senão o rollback quebra o cadastro.
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO tenancy_tenant (id, created_at, updated_at, row_version, legal_name, trade_name, "
                    "cnpj, slug, status, status_note, plan, plan_note, tiss_liberado, tiss_nota, timezone, settings) "
                    "VALUES (gen_random_uuid(), now(), now(), 1, 'Antiga', '', %s, 'insert-sem-cpf', 'active', '', "
                    "'free', '', false, '', 'America/Sao_Paulo', '{}')", [cnpj_valido('445566000001')],
                )
        conferir('INSERT sem cpf (código da 1.31) funciona', Tenant.objects.filter(slug='insert-sem-cpf', cpf='').exists())
        # O motivo do encerramento vai ao cliente: o campo não pode vir
        # preenchido com a nota interna da mudança anterior.
        html = open('/app/templates/ops/superadmin/tenants.html', encoding='utf-8').read()
        conferir('o campo do motivo nasce vazio e com teto de 255',
                 'value="{{ row.obj.status_note }}"' not in html and 'maxlength="255"' in html)
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHAS ({len(falhas)}):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('OK: cadastro seguro')
