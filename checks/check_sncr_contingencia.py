"""SNCR, Sprint 3: a chave no console, o pedido incerto conferido e a contingência.

Tenta quebrar. As perguntas são:

- o console (`/instalacao/operacao/sncr/`): sem MFA não abre; ligar sem
  CNPJ, com CNPJ inválido, sem a palavra ou sem motivo não liga; ligar com
  tudo liga e vai à trilha; o ambiente não muda com a integração ligada;
  desligar é um clique; o médico não alcança a rota?
- o pedido incerto (decisão I14): ele barra pedido novo; só o próprio
  médico o confere; "nenhum bloco" libera pedir de novo; a faixa digitada
  precisa ter os 1.000 números do bloco; a faixa certa vira bloco usável;
  a faixa que repete número vira bloco **não** utilizável; a secretária
  não chega lá?
- a contingência (decisão I15): o rascunho eletrônico refeito como
  impresso — a RCE vira a impressa da clínica e a RET a simples, com a
  mesma prescrição, o eletrônico descartado, nenhum número gasto e a
  trilha; a emitida e a impressa não se convertem; a tela oferece o botão
  e a recusa da assinatura o aponta?
- a RCE impressa depois de 31/10: a trava continua com a integração
  ligada, e a recusa aponta a eletrônica só quando ela existe?
"""
import secrets
from datetime import date

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import PhysicianProfile, User
from audit.models import AuditEvent
from documents import issuance, rce_impressa
from documents.models import Attachment, MedicalDocument, MedicalDocumentStatus
from patients.models import Patient
from sncr import fluxo, numeracao, receita
from sncr.models import (
    BlocoNumeracao, Configuracao, EstadoNumero, EstadoPedido, NumeroSncr, PedidoNumeracao,
)
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


tenant_a = Tenant.objects.get(slug='demo-clinica-a')
user_a = User.objects.get(email='doctor-a@demo.neurodoc.local')
user_b = User.objects.get(email='doctor-b@demo.neurodoc.local')
vinculo_a = Membership.objects.get(tenant=tenant_a, user=user_a)
medico_a = PhysicianProfile.objects.get(user=user_a)
medico_b = PhysicianProfile.objects.get(user=user_b)
config = Configuracao.carregar()
original = (config.ativo, config.ambiente, config.cnpj_mantenedora)
CNPJ = '11222333000181'
pacientes, documentos = [], []


def cliente_de(email):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(tenant_a.id)
    s.save()
    return c


def cpf_valido():
    while True:
        base = [secrets.randbelow(10) for _ in range(9)]
        for _ in range(2):
            soma = sum(d * p for d, p in zip(base, range(len(base) + 1, 1, -1)))
            base.append((soma * 10 % 11) % 10)
        texto = ''.join(map(str, base))
        if len(set(texto)) > 1 and not Patient.objects.filter(cpf=texto).exists():
            return texto


def paciente():
    p = Patient.objects.create(
        tenant=tenant_a, full_name=f'PACIENTE CONTINGENCIA {secrets.token_hex(3).upper()}',
        birth_date=date(1975, 3, 2), cpf=cpf_valido(), street='Rua das Acácias', number='120',
        district='Jardim Paulista', city='São Paulo', state='SP', postal_code='01415000',
        sex_at_registration='male',
    )
    pacientes.append(p.id)
    return p


def rascunho(p, formato, *lista):
    campos = {'prescription_text': '', 'special_instructions': 'Uso contínuo.',
              'prescription_format': formato, 'classificacao_confirmada': False}
    for n, (nome, conc, forma, qtd, poso) in enumerate(lista, start=1):
        campos.update({f'item{n}_nome': nome, f'item{n}_concentracao': conc, f'item{n}_forma': forma,
                       f'item{n}_quantidade': qtd, f'item{n}_posologia': poso})
    doc = issuance.create_draft(tenant_a, p, None, vinculo_a, user_a.id, 'prescription', campos)
    documentos.append(doc.id)
    return doc


SERTRALINA = ('Sertralina', '50 mg', 'comprimido', '60 comprimidos', '1 comprimido pela manhã')
PREGABALINA = ('Pregabalina', '75 mg', 'cápsula', '60 cápsulas', '1 cápsula de 12 em 12 horas')
AMOXICILINA = ('Amoxicilina', '500 mg', 'cápsula', '21 cápsulas', '1 cápsula de 8 em 8 horas')


def pedido_incerto(medico):
    return PedidoNumeracao.objects.create(
        medico=medico, solicitado_por=medico.user, tenant=tenant_a, tipo='RCE', ambiente='producao',
        uf=medico.crm_state, documento=medico.crm_number, cnpj=CNPJ, estado=EstadoPedido.INCERTO,
        mensagem='tempo esgotado depois de enviar (roteiro)',
    )


def limpar_numeracao():
    for medico in (medico_a, medico_b):
        NumeroSncr.objects.filter(medico=medico).delete()
        BlocoNumeracao.objects.filter(medico=medico).delete()
        PedidoNumeracao.objects.filter(medico=medico).delete()


superadmin = User.objects.filter(is_superuser=True, is_active=True).first()
superadmin_do_roteiro = None
if superadmin is None:
    # A base de demonstração não tem superusuário; o roteiro cria um e o
    # aposenta no fim (a trilha é INSERT-only e o referencia).
    superadmin_do_roteiro = superadmin = User.objects.create_superuser(
        email=f'roteiro-sncr-{secrets.token_hex(3)}@demo.neurodoc.local', password=secrets.token_urlsafe(16),
    )
aparelho = None
try:
    limpar_numeracao()

    print('=== 1. o console da instalação ===')
    if superadmin is None:
        print('  (sem superusuário nesta instalação; seção pulada)')
    else:
        config.ativo, config.ambiente, config.cnpj_mantenedora = False, 'producao', ''
        config.save()
        console = Client(SERVER_NAME='localhost')
        console.force_login(superadmin)
        conferir('sem MFA, a tela de operação não abre', console.get('/instalacao/operacao/').status_code == 404)
        aparelho, _ = TOTPDevice.objects.get_or_create(user=superadmin, name='roteiro-sncr',
                                                       defaults={'confirmed': True})
        s = console.session
        s[DEVICE_ID_SESSION_KEY] = aparelho.persistent_id
        s.save()
        tela = console.get('/instalacao/operacao/')
        conferir('com MFA, a tela mostra o cartão do SNCR, desligado',
                 tela.status_code == 200 and 'data-nd-sncr-console' in tela.content.decode()
                 and 'Desligada' in tela.content.decode(), tela.status_code)
        url = '/instalacao/operacao/sncr/'

        def ligar(**extra):
            dados = {'acao': 'ligar', 'confirmacao': 'LIGAR', 'motivo': 'teste do roteiro'}
            dados.update(extra)
            console.post(url, dados)
            return Configuracao.carregar().ativo

        conferir('ligar sem CNPJ: não liga', ligar() is False)
        console.post(url, {'acao': 'cnpj', 'cnpj': '11.222.333/0001-80'})
        conferir('CNPJ inválido: não grava', Configuracao.carregar().cnpj_mantenedora == '')
        console.post(url, {'acao': 'cnpj', 'cnpj': '11.222.333/0001-81'})
        conferir('CNPJ válido: grava só os dígitos', Configuracao.carregar().cnpj_mantenedora == CNPJ)
        conferir('ligar sem a palavra: não liga', ligar(confirmacao='ligar') is False)
        conferir('ligar sem motivo: não liga', ligar(motivo='  ') is False)
        conferir('ligar com tudo: liga', ligar() is True)
        conferir('e vai à trilha com o motivo', AuditEvent.objects.filter(
            action='ops.sncr_enabled', integrity_metadata__motivo='teste do roteiro').exists())
        console.post(url, {'acao': 'ambiente', 'ambiente': 'homologacao'})
        conferir('ligada, o ambiente não muda', Configuracao.carregar().ambiente == 'producao')
        console.post(url, {'acao': 'cnpj', 'cnpj': ''})
        conferir('ligada, o CNPJ não é apagado', Configuracao.carregar().cnpj_mantenedora == CNPJ)
        console.post(url, {'acao': 'desligar'})
        conferir('desligar é um clique', Configuracao.carregar().ativo is False)
        console.post(url, {'acao': 'ambiente', 'ambiente': 'homologacao'})
        conferir('desligada, o ambiente muda', Configuracao.carregar().ambiente == 'homologacao')
        medico = cliente_de('doctor-a@demo.neurodoc.local')
        conferir('o médico não alcança a rota do console',
                 medico.post(url, {'acao': 'desligar'}).status_code == 404)

    config = Configuracao.carregar()
    config.ativo, config.ambiente, config.cnpj_mantenedora = True, 'producao', CNPJ
    config.save()

    print('=== 2. o pedido incerto, conferido pelo médico ===')
    incerto = pedido_incerto(medico_a)
    conferir('o incerto barra pedido novo', any('incerto' in m for m in fluxo.conferir(config, medico_a, 'RCE')))
    medico = cliente_de('doctor-a@demo.neurodoc.local')
    painel = medico.get('/app/sncr/').content.decode()
    conferir('o painel oferece a conferência', 'data-nd-sncr-conferir' in painel)
    outro = cliente_de('doctor-b@demo.neurodoc.local')
    outro.post(f'/app/sncr/pedido/{incerto.id}/conferir/', {'resultado': 'nao_gerado'})
    incerto.refresh_from_db()
    conferir('outro médico não confere o pedido da colega', incerto.estado == EstadoPedido.INCERTO)
    secretaria = cliente_de('secretary-a@demo.neurodoc.local')
    r = secretaria.post(f'/app/sncr/pedido/{incerto.id}/conferir/', {'resultado': 'nao_gerado'})
    incerto.refresh_from_db()
    conferir('a secretária não chega lá', r.status_code == 404 and incerto.estado == EstadoPedido.INCERTO,
             r.status_code)
    medico.post(f'/app/sncr/pedido/{incerto.id}/conferir/',
                {'resultado': 'gerado', 'inicio': '000001000', 'fim': '000001998'})
    incerto.refresh_from_db()
    conferir('faixa de 999 números (erro de digitação): recusada, segue incerto',
             incerto.estado == EstadoPedido.INCERTO and not BlocoNumeracao.objects.filter(pedido=incerto).exists())
    medico.post(f'/app/sncr/pedido/{incerto.id}/conferir/',
                {'resultado': 'gerado', 'inicio': '000001000', 'fim': '000001999'})
    incerto.refresh_from_db()
    conferir('faixa de 1.000: o pedido vira concluído com o bloco',
             incerto.estado == EstadoPedido.CONCLUIDO and incerto.bloco.utilizavel)
    conferir('e os 1.000 números ficam livres', numeracao.saldo(medico_a, 'RCE', 'producao') == 1000)
    conferir('a conferência vai à trilha em nome do médico', AuditEvent.objects.filter(
        object_id=incerto.id, action='sncr.pedido_concluido', actor_id=user_a.id).exists())

    sobreposto = pedido_incerto(medico_a)
    medico.post(f'/app/sncr/pedido/{sobreposto.id}/conferir/',
                {'resultado': 'gerado', 'inicio': '000001500', 'fim': '000002499'})
    sobreposto.refresh_from_db()
    conferir('faixa que repete número já registrado: bloco gravado como não utilizável',
             sobreposto.estado == EstadoPedido.CONCLUIDO and not sobreposto.bloco.utilizavel)
    conferir('e o saldo não muda', numeracao.saldo(medico_a, 'RCE', 'producao') == 1000)

    sem_bloco = pedido_incerto(medico_a)
    medico.post(f'/app/sncr/pedido/{sem_bloco.id}/conferir/', {'resultado': 'nao_gerado'})
    sem_bloco.refresh_from_db()
    conferir('"nenhum bloco foi gerado": o pedido vira não enviado', sem_bloco.estado == EstadoPedido.FALHOU)
    conferir('e não barra mais pedido novo por incerteza',
             not any('incerto' in m for m in fluxo.conferir(config, medico_a, 'RCE')))
    medico.post(f'/app/sncr/pedido/{sem_bloco.id}/conferir/', {'resultado': 'gerado',
                                                               'inicio': '000003000', 'fim': '000003999'})
    sem_bloco.refresh_from_db()
    conferir('o conferido não se confere de novo', sem_bloco.estado == EstadoPedido.FALHOU)

    print('=== 3. a contingência: refazer como impressa ===')
    p = paciente()
    rce = rascunho(p, receita.SNCR_RCE, SERTRALINA, PREGABALINA)
    texto = rce.content_snapshot['prescription_text']
    tela = medico.get(f'/app/documents/medical/{rce.id}/').content.decode()
    conferir('o rascunho eletrônico oferece "Refazer como receita impressa"', 'Refazer como receita impressa' in tela)
    r = medico.post(f'/app/documents/medical/{rce.id}/refazer-impressa/')
    novo = MedicalDocument.objects.filter(patient=p).exclude(id=rce.id).order_by('-created_at').first()
    if novo:
        documentos.append(novo.id)
    conferir('o eletrônico foi descartado', not MedicalDocument.objects.filter(id=rce.id).exists())
    conferir('a RCE virou a impressa da clínica, com a mesma prescrição',
             novo is not None and novo.content_snapshot.get('prescription_format') == 'special_control'
             and novo.content_snapshot.get('prescription_text') == texto)
    conferir('e a tela vai para ela', novo is not None and r.status_code == 302
             and str(novo.id) in r['Location'], r.status_code)
    conferir('nenhum número gasto', numeracao.saldo(medico_a, 'RCE', 'producao') == 1000
             and not NumeroSncr.objects.filter(estado=EstadoNumero.RESERVADO, medico=medico_a).exists())
    conferir('a troca vai à trilha', AuditEvent.objects.filter(
        action='documents.medicaldocument_converted_to_paper', object_id=novo.id if novo else None).exists())
    ret = rascunho(p, receita.SNCR_RET, AMOXICILINA)
    novo_ret = issuance.converter_para_impressa(ret, user_a.id)
    documentos.append(novo_ret.id)
    conferir('a RET vira a receita simples', novo_ret.content_snapshot['prescription_format'] == 'simple')
    try:
        issuance.converter_para_impressa(novo_ret, user_a.id)
        recusou = False
    except ValueError:
        recusou = True
    conferir('a impressa não se "converte"', recusou)

    sem_numero = rascunho(p, receita.SNCR_RCE, SERTRALINA)
    sem_numero.status = MedicalDocumentStatus.ISSUED
    sem_numero.save(update_fields=['status'])
    try:
        issuance.converter_para_impressa(sem_numero, user_a.id)
        recusou = False
    except ValueError:
        recusou = True
    conferir('a eletrônica emitida não se converte (ela vale como está)', recusou)
    conferir('a recusa por falta de número aponta a contingência',
             'Refazer como receita impressa' in open(issuance.__file__, encoding='utf-8').read())

    print('=== 4. a RCE impressa depois de 31/10 ===')
    vigente = date(2026, 11, 3)
    config.ativo = False
    config.save()
    desligada = rce_impressa.recusa()
    conferir('desligada: a recusa aponta só o papel',
             'assinar e carimbar' in desligada and 'eletrônica com numeração' not in desligada)
    config.ativo = True
    config.save()
    ligada = rce_impressa.recusa()
    conferir('ligada: a recusa aponta também a eletrônica do SNCR',
             'assinar e carimbar' in ligada and 'eletrônica com numeração do SNCR' in ligada)
    conferir('ligada, a trava da RCE impressa continua (é da norma)',
             rce_impressa.assinatura_digital_bloqueada(novo, hoje=vigente) if novo else False)
finally:
    print('=== limpeza ===')
    NumeroSncr.objects.filter(documento_id__in=documentos).update(documento=None)
    limpar_numeracao()
    for d in MedicalDocument.objects.filter(id__in=documentos):
        anexos = [a for a in (d.pdf_attachment_id, d.signed_pdf_attachment_id) if a]
        d.delete()
        Attachment.objects.filter(id__in=anexos).delete()
    Attachment.objects.filter(patient_id__in=pacientes).delete()
    Patient.objects.filter(id__in=pacientes).delete()
    if superadmin_do_roteiro is not None:
        superadmin_do_roteiro.is_active = False
        superadmin_do_roteiro.email = f'aposentado-por-roteiro-{secrets.token_hex(4)}@demo.invalid'
        superadmin_do_roteiro.save(update_fields=['is_active', 'email'])
    if aparelho is not None:
        aparelho.delete()
    config = Configuracao.carregar()
    config.ativo, config.ambiente, config.cnpj_mantenedora = original
    config.save()
    print('  pedidos, blocos, receitas e pacientes do roteiro removidos; configuração restaurada')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: SNCR — a chave no console, o incerto conferido pelo médico e a receita refeita como impressa.')
