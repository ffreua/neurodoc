"""O paciente manda o laudo pelo portal, e ele chega ao prontuario -- so ele?

Tenta quebrar. As perguntas sao:

- a tela diz, em vermelho e antes do formulario, que e so laudo e so PDF?
- arquivo que nao e PDF (inclusive o renomeado), maior que 3 MB, sexto
  arquivo, data no futuro, sem local, "Outro" sem nome: tudo recusado,
  e recusado **sem gravar nada**?
- tudo ou nada: um arquivo ruim entre dois bons nao deixa os bons
  entrarem sozinhos?
- o formulario aberto para um paciente nao grava na ficha de outro?
- o que entra vai para o prontuario certo, clinico, sem autor de conta,
  com a data do exame, em quarentena, e o antivirus e pedido pelo worker?
- o medico e avisado e a secretaria nao?
- o alerta aparece no prontuario para o medico e some no "Ciente"; a
  secretaria nao ve o alerta nem o nome do exame, e nao marca ciente?
- a janela de retorno (180 dias) barra o pedido, mas **nao** o envio de
  laudo?
- outra clinica nao marca ciente, e portal desligado nao recebe nada?
"""
import atexit
import datetime
import io
from unittest import mock

from django.conf import settings as dj_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir.
dj_settings.SECURE_SSL_REDIRECT = False

from django.core.cache import cache
from django.utils import timezone

from accounts.models import User
from documents import portal_exames
from documents.models import Attachment, AttachmentClassification, PortalExamUpload
from documents.tasks import scan_attachment
from notifications.models import Notification
from patients.models import Patient, PatientStatus
from tenancy.models import ClinicProfile, Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')
clinica_b = Tenant.objects.get(slug='demo-clinica-b')
# Banco recem-semeado nao tem perfil de clinica (o `seed_demo` nao cria);
# sem ele o portal nao existe. Criado aqui, e apagado no fim se foi daqui.
perfil, _perfil_criado = ClinicProfile.objects.get_or_create(tenant=clinica)
medico = Membership.objects.filter(
    tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    user__email='doctor-a@demo.neurodoc.local',
).first()
if None in (perfil, medico):
    print('  (demonstracao incompleta; roteiro pulado)')
    raise SystemExit(0)

_original = (
    perfil.patient_portal_enabled, perfil.patient_portal_requires_recent_visit,
    medico.patient_portal_requires_recent_visit,
)

# Paciente proprio, sem consulta nenhuma: com a barreira ligada, ele e
# barrado no pedido -- e e assim que se prova que o laudo passa mesmo assim.
_paciente = Patient.objects.create(
    tenant=clinica, full_name='Paciente Do Roteiro De Exames',
    cpf='62096654203', birth_date=datetime.date(1979, 3, 14),
    status=PatientStatus.ACTIVE,
)
_outro = Patient.objects.create(
    tenant=clinica, full_name='Outro Paciente Do Roteiro De Exames',
    cpf='87072297120', birth_date=datetime.date(1990, 1, 2),
    status=PatientStatus.ACTIVE,
)
_notificacoes_antes = set(Notification.objects.values_list('id', flat=True))


def restaurar():
    if _perfil_criado:
        _limpar_dados()
        ClinicProfile.objects.filter(id=perfil.id).delete()
        Membership.objects.filter(id=medico.id).update(
            patient_portal_requires_recent_visit=_original[2],
        )
        return
    perfil.patient_portal_enabled = _original[0]
    perfil.patient_portal_requires_recent_visit = _original[1]
    perfil.save(update_fields=['patient_portal_enabled', 'patient_portal_requires_recent_visit'])
    Membership.objects.filter(id=medico.id).update(
        patient_portal_requires_recent_visit=_original[2],
    )
    _limpar_dados()


def _limpar_dados():
    from pathlib import Path

    pacientes = [_paciente.id, _outro.id]
    anexos = list(Attachment.objects.filter(patient_id__in=pacientes))
    PortalExamUpload.objects.filter(patient_id__in=pacientes).delete()
    for a in anexos:
        if a.storage_key:
            Path(a.storage_key).unlink(missing_ok=True)
    Attachment.objects.filter(patient_id__in=pacientes).delete()
    Notification.objects.exclude(id__in=_notificacoes_antes).filter(
        kind='portal_exam',
    ).delete()
    Patient.objects.filter(id__in=pacientes).delete()


atexit.register(restaurar)


def zera_balde():
    for b in ('lookup', 'submit', 'exames'):
        cache.delete(f'portal:{b}:127.0.0.1')


def pdf(texto='Laudo de teste'):
    """Um PDF de verdade, e nao so o cabecalho: o validador fareja o tipo."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, texto)
    c.save()
    return buf.getvalue()


def arquivo(nome='laudo.pdf', conteudo=None):
    return SimpleUploadedFile(nome, conteudo if conteudo is not None else pdf(),
                              content_type='application/pdf')


ONTEM = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
AMANHA = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()


def identificado(paciente=_paciente):
    zera_balde()
    c = Client()
    c.post(f'/solicitacoes/{clinica.slug}/', {
        'cpf': paciente.cpf, 'birth_date': paciente.birth_date.isoformat(), 'privacy_ack': '1',
    })
    return c


def linha(n, **campos):
    base = {f'tipo_{n}': 'ressonancia', f'data_{n}': ONTEM, f'local_{n}': 'Laboratorio Exemplo'}
    base.update(campos)
    return base


def envia(c, dados, token=None):
    zera_balde()
    dados = dict(dados)
    dados.setdefault('identidade', token if token is not None
                     else (c.session.get('portal_patient') or {}).get('token', ''))
    dados.setdefault('requester', 'self')
    return c.post(f'/solicitacoes/{clinica.slug}/exames/', dados)


def anexos_do(paciente):
    return Attachment.objects.filter(patient=paciente).count()


def logado(email, tenant):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


perfil.patient_portal_enabled = True
perfil.patient_portal_requires_recent_visit = True
perfil.save(update_fields=['patient_portal_enabled', 'patient_portal_requires_recent_visit'])
Membership.objects.filter(id=medico.id).update(patient_portal_requires_recent_visit=None)

print('=== 1. a janela de retorno barra o pedido, nao o laudo ===')
c = identificado()
r = c.get(f'/solicitacoes/{clinica.slug}/solicitar/')
confere(r.status_code == 403, f'/solicitar/ de quem nunca consultou -> 403 ({r.status_code})')
confere(f'/solicitacoes/{clinica.slug}/exames/' in r.content.decode(),
        'a tela de bloqueio oferece o envio de exames')
r = c.get(f'/solicitacoes/{clinica.slug}/exames/')
corpo = r.content.decode()
confere(r.status_code == 200, f'/exames/ abre para o mesmo paciente ({r.status_code})')
r_id = c.get(f'/solicitacoes/{clinica.slug}/')
confere(r_id.status_code == 200,
        f'quem foi barrado volta ao formulario de identificacao, e nao ao bloqueio ({r_id.status_code})')

print('=== 2. o aviso vem antes, em vermelho, com os limites ===')
confere('alert-danger' in corpo and 'APENAS laudos de exames e resultados finais' in corpo,
        'aviso vermelho "APENAS laudos de exames e resultados finais"')
confere('somente arquivos PDF' in corpo, 'a tela diz que so aceita PDF')
confere(corpo.index('alert-danger') < corpo.index('<form'), 'o aviso vem antes do formulario')
confere('5' in corpo and '3 MB' in corpo, 'a tela traz o limite de 5 arquivos e 3 MB')
for i in range(1, 6):
    confere(f'name="arquivo_{i}"' in corpo, f'linha {i} desenhada')
confere('name="arquivo_6"' not in corpo, 'nao ha sexta linha')
confere('Eletroneuromiografia' in corpo and 'Ressonância magnética' in corpo,
        'os tipos de exame estao no menu')

print('=== 3. recusas, todas sem gravar nada ===')
antes = anexos_do(_paciente)
casos = [
    ('sem arquivo nenhum', {}),
    ('linha preenchida sem arquivo', linha(1)),
    ('texto renomeado para .pdf', {**linha(1), 'arquivo_1': arquivo('laudo.pdf', b'isto nao e pdf ' * 50)}),
    ('extensao que nao e pdf', {**linha(1), 'arquivo_1': arquivo('laudo.png')}),
    ('maior que 3 MB', {**linha(1), 'arquivo_1': arquivo(
        'grande.pdf', pdf() + b'%' + b'0' * (portal_exames.MAX_BYTES + 10))}),
    ('data no futuro', {**linha(1, data_1=AMANHA), 'arquivo_1': arquivo()}),
    ('sem data', {**linha(1, data_1=''), 'arquivo_1': arquivo()}),
    ('sem local', {**linha(1, local_1=''), 'arquivo_1': arquivo()}),
    ('tipo invalido', {**linha(1, tipo_1='raio_gama'), 'arquivo_1': arquivo()}),
    ('"Outro" sem o nome', {**linha(1, tipo_1='outro'), 'arquivo_1': arquivo()}),
    ('seis arquivos', {**{f'arquivo_{i}': arquivo(f'l{i}.pdf') for i in range(1, 7)},
                       **{k: v for i in range(1, 6) for k, v in linha(i).items()}}),
]
for rotulo, dados in casos:
    c = identificado()
    r = envia(c, dados)
    confere(r.status_code == 400, f'{rotulo} -> 400 ({r.status_code})')
confere(anexos_do(_paciente) == antes, 'nenhuma recusa gravou anexo')

print('=== 4. tudo ou nada ===')
c = identificado()
with mock.patch.object(scan_attachment, 'delay') as fila:
    r = envia(c, {
        **linha(1), 'arquivo_1': arquivo('a.pdf'),
        **linha(2, local_2=''), 'arquivo_2': arquivo('b.pdf'),
        **linha(3), 'arquivo_3': arquivo('c.pdf'),
    })
confere(r.status_code == 400, f'um ruim entre dois bons -> 400 ({r.status_code})')
confere(anexos_do(_paciente) == antes, 'nenhum dos bons entrou sozinho')
confere(not fila.called, 'nenhum antivirus pedido')
confere('exame 2' in r.content.decode(), 'a mensagem diz qual linha corrigir')

print('=== 5. o formulario de um paciente nao grava na ficha de outro ===')
c = identificado()
token_velho = c.session['portal_patient']['token']
c.post(f'/solicitacoes/{clinica.slug}/', {
    'cpf': _outro.cpf, 'birth_date': _outro.birth_date.isoformat(), 'privacy_ack': '1',
})
r = envia(c, {**linha(1), 'arquivo_1': arquivo()}, token=token_velho)
confere(r.status_code == 409, f'token de outra identificacao -> 409 ({r.status_code})')
confere(anexos_do(_paciente) == antes and anexos_do(_outro) == 0, 'nada gravado em nenhuma das fichas')

print('=== 6. o envio certo ===')
c = identificado()
notif_antes = Notification.objects.filter(kind='portal_exam').count()
with mock.patch.object(scan_attachment, 'delay') as fila:
    r = envia(c, {
        **linha(1), 'arquivo_1': arquivo('Ressonância (1).pdf'),
        **linha(2, tipo_2='outro', outro_2='Teste do pezinho', local_2='Dra. Fulana'),
        'arquivo_2': arquivo('outro.pdf'),
    })
confere(r.status_code == 302 and r['Location'].endswith('/exames/enviados/'),
        f'envio valido -> 302 para a tela de enviados ({r.status_code})')
envios = list(PortalExamUpload.objects.filter(patient=_paciente).select_related('attachment'))
confere(len(envios) == 2, f'dois envios gravados ({len(envios)})')
for e in envios:
    a = e.attachment
    confere(a.patient_id == _paciente.id and a.tenant_id == clinica.id, f'{e.exam_label}: ficha e clinica certas')
    confere(a.classification == AttachmentClassification.CLINICAL, f'{e.exam_label}: clinico')
    confere(a.uploaded_by_id is None, f'{e.exam_label}: sem autor de conta')
    confere(a.document_date == timezone.localdate() - datetime.timedelta(days=1),
            f'{e.exam_label}: data do documento = data do exame')
    confere(a.scan_status == 'quarantined', f'{e.exam_label}: em quarentena ate o antivirus')
    confere(a.original_name.endswith('.pdf') and ' ' not in a.original_name,
            f'{e.exam_label}: nome gerado ({a.original_name})')
    confere(e.acknowledged_at is None, f'{e.exam_label}: nasce pendente')
confere(fila.call_count == 2, f'antivirus pedido ao worker para os dois ({fila.call_count})')
rotulos = sorted(e.exam_label for e in envios)
confere(rotulos == ['Ressonância magnética', 'Teste do pezinho'], f'rotulos {rotulos}')
confere(any(e.original_filename == 'Ressonância (1).pdf' for e in envios),
        'o nome original fica registrado')
r = c.get(f'/solicitacoes/{clinica.slug}/exames/')
confere(r.status_code == 302, 'a identificacao foi encerrada depois do envio')

print('=== 7. quem e avisado ===')
novas = Notification.objects.filter(kind='portal_exam').exclude(id__in=_notificacoes_antes)
destinos = set(novas.values_list('user__email', flat=True))
confere(Notification.objects.filter(kind='portal_exam').count() > notif_antes, 'houve aviso')
confere('doctor-a@demo.neurodoc.local' in destinos, 'o medico foi avisado')
confere('secretary-a@demo.neurodoc.local' not in destinos, 'a secretaria nao foi avisada')
from notifications.targets import url_for

n = novas.first()
confere(n is not None and url_for(n) == f'/app/documents/patients/{_paciente.id}/',
        f'o aviso leva aos anexos do paciente ({url_for(n) if n else None})')

print('=== 8. o alerta no prontuario ===')
doc = logado('doctor-a@demo.neurodoc.local', clinica)
sec = logado('secretary-a@demo.neurodoc.local', clinica)
for rota in (f'/app/clinical/patients/{_paciente.id}/timeline/', f'/app/patients/{_paciente.id}/'):
    corpo = doc.get(rota).content.decode()
    confere('enviou 2 exames pelo portal' in corpo and 'Teste do pezinho' in corpo,
            f'medico ve o alerta em {rota}')
corpo = sec.get(f'/app/patients/{_paciente.id}/').content.decode()
confere('pelo portal' not in corpo and 'Teste do pezinho' not in corpo,
        'secretaria nao ve o alerta na ficha')
corpo = sec.get(f'/app/documents/patients/{_paciente.id}/').content.decode()
confere('Teste do pezinho' not in corpo and 'Documento clínico' in corpo,
        'secretaria ve a linha, nao o exame')
confere('Enviado pelo paciente' in corpo, 'secretaria sabe que veio do paciente')
corpo = doc.get(f'/app/documents/patients/{_paciente.id}/').content.decode()
confere('Teste do pezinho' in corpo and 'Dra. Fulana' in corpo and '>Novo<' in corpo,
        'medico ve tipo, local e "Novo" na lista de anexos')

print('=== 9. o ciente ===')
ack = f'/app/documents/patients/{_paciente.id}/exames-do-portal/ciente/'
r = sec.post(ack)
confere(r.status_code == 404, f'secretaria nao marca ciente ({r.status_code})')
confere(PortalExamUpload.objects.filter(patient=_paciente, acknowledged_at=None).count() == 2,
        'continua pendente')
doc_b = logado('doctor-a@demo.neurodoc.local', clinica_b)
r = doc_b.post(ack)
confere(r.status_code == 404, f'o mesmo medico, na outra clinica, nao marca ({r.status_code})')
r = doc.get(ack)
confere(r.status_code == 405, f'GET nao marca nada ({r.status_code})')
r = doc.post(ack, {'next': 'https://exemplo.invalid/'})
confere(r.status_code == 302 and 'exemplo.invalid' not in r['Location'],
        f'"next" de fora do dominio e ignorado ({r.get("Location")})')
pend = PortalExamUpload.objects.filter(patient=_paciente, acknowledged_at=None).count()
confere(pend == 0, f'medico marcou ciente ({pend} pendentes)')
confere(PortalExamUpload.objects.filter(patient=_paciente, acknowledged_by=medico).count() == 2,
        'ciente registra quem viu')
corpo = doc.get(f'/app/clinical/patients/{_paciente.id}/timeline/').content.decode()
confere('pelo portal' not in corpo, 'o alerta sumiu do prontuario')

print('=== 10. portal desligado nao recebe ===')
c = identificado()
perfil.patient_portal_enabled = False
perfil.save(update_fields=['patient_portal_enabled'])
r = envia(c, {**linha(1), 'arquivo_1': arquivo()})
confere(r.status_code == 404, f'portal desligado -> 404 ({r.status_code})')
perfil.patient_portal_enabled = True
perfil.save(update_fields=['patient_portal_enabled'])

print('=== 11. limite por endereco ===')
cache.set('portal:exames:127.0.0.1', portal_exames.ENVIOS_POR_HORA, 3600)
c = identificado()
cache.set('portal:exames:127.0.0.1', portal_exames.ENVIOS_POR_HORA, 3600)
dados = {**linha(1), 'arquivo_1': arquivo(),
         'identidade': c.session['portal_patient']['token'], 'requester': 'self'}
r = c.post(f'/solicitacoes/{clinica.slug}/exames/', dados)
confere(r.status_code == 429, f'acima do limite -> 429 ({r.status_code})')
zera_balde()

# Daqui em diante, com o CSRF ligado, como num navegador. O cliente de
# teste do Django dispensa o CSRF por padrao, e foi por isso que as
# secoes acima passaram enquanto a producao recusava o primeiro envio
# real (2026-10-18): o formulario fora aberto antes de um login no mesmo
# navegador, e o login troca o token.
import re

from documents import portal as portal_mod


def token_da_pagina(r):
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.content.decode())
    return m.group(1) if m else ''


def navegador_identificado(paciente=_paciente):
    zera_balde()
    b = Client(enforce_csrf_checks=True)
    r = b.get(f'/solicitacoes/{clinica.slug}/')
    b.post(f'/solicitacoes/{clinica.slug}/', {
        'cpf': paciente.cpf, 'birth_date': paciente.birth_date.isoformat(),
        'privacy_ack': '1', 'csrfmiddlewaretoken': token_da_pagina(r),
    })
    return b


print('=== 12. com CSRF de verdade, o envio passa ===')
b = navegador_identificado()
r = b.get(f'/solicitacoes/{clinica.slug}/exames/')
confere(r.status_code == 200, f'navegador identificado abre /exames/ ({r.status_code})')
antes = PortalExamUpload.objects.filter(patient=_paciente).count()
with mock.patch.object(scan_attachment, 'delay'):
    r = b.post(f'/solicitacoes/{clinica.slug}/exames/', {
        **linha(1), 'arquivo_1': arquivo(), 'requester': 'self',
        'identidade': b.session['portal_patient']['token'],
        'csrfmiddlewaretoken': token_da_pagina(r),
    })
confere(r.status_code == 302, f'envio com token do formulario -> 302 ({r.status_code})')
novo = PortalExamUpload.objects.filter(patient=_paciente).order_by('-created_at').first()
confere(PortalExamUpload.objects.filter(patient=_paciente).count() == antes + 1, 'o envio gravou')
confere(novo is not None and novo.privacy_notice_version == portal_mod.PRIVACY_NOTICE_VERSION
        == '2026-10-v2', 'grava a versao do aviso que cita o envio de laudos')

print('=== 13. login no meio: nada gravado, saida clara, identificacao encerrada ===')
b = navegador_identificado()
r = b.get(f'/solicitacoes/{clinica.slug}/exames/')
token_velho, identidade = token_da_pagina(r), b.session['portal_patient']['token']
b.force_login(User.objects.get(email='doctor-a@demo.neurodoc.local'))
confere('portal_patient' not in b.session, 'o login encerrou a identificacao do portal')
# O login de verdade troca o cookie CSRF (`rotate_token`); o `force_login`
# do cliente de teste so grava o cookie de sessao. A troca e feita a mao,
# para o formulario aberto antes ficar com o token velho, como no navegador.
from django.middleware.csrf import _get_new_csrf_string

b.cookies[dj_settings.CSRF_COOKIE_NAME] = _get_new_csrf_string()
antes = PortalExamUpload.objects.filter(patient=_paciente).count()
r = b.post(f'/solicitacoes/{clinica.slug}/exames/', {
    **linha(1), 'arquivo_1': arquivo(), 'requester': 'self',
    'identidade': identidade, 'csrfmiddlewaretoken': token_velho,
})
corpo = r.content.decode()
confere(r.status_code == 403, f'formulario de antes do login -> 403 ({r.status_code})')
confere(PortalExamUpload.objects.filter(patient=_paciente).count() == antes, 'nada gravado')
confere('Os arquivos não foram enviados' in corpo, 'a tela diz que os arquivos nao foram')
confere(f'href="/solicitacoes/{clinica.slug}/exames/"' in corpo, 'e oferece abrir a pagina de novo')
anon = Client(enforce_csrf_checks=True)
r = anon.post(f'/solicitacoes/{clinica.slug}/exames/', {'csrfmiddlewaretoken': 'x' * 64})
corpo = r.content.decode()
confere(r.status_code == 403 and 'tela de entrada' not in corpo,
        'paciente sem conta nao e mandado ao login do sistema')
r = b.get(f'/solicitacoes/{clinica.slug}/exames/')
confere(r.status_code == 302, f'depois do login, /exames/ pede identificacao de novo ({r.status_code})')

print('=== 14. sair sem enviar ===')
b = navegador_identificado()
r = b.get(f'/solicitacoes/{clinica.slug}/exames/')
confere('Encerrar identificação' in r.content.decode(), 'o botao de sair esta na tela de envio')
r = b.get(f'/solicitacoes/{clinica.slug}/sair/')
confere(r.status_code == 405, f'GET nao encerra ({r.status_code})')
r = b.post(f'/solicitacoes/{clinica.slug}/sair/', {'csrfmiddlewaretoken': token_da_pagina(
    b.get(f'/solicitacoes/{clinica.slug}/exames/'))})
confere(r.status_code == 302 and 'portal_patient' not in b.session, 'POST encerra a identificacao')
r = b.get(f'/solicitacoes/{clinica.slug}/exames/')
confere(r.status_code == 302, f'e /exames/ volta a pedir CPF ({r.status_code})')

print('=== 15. os textos ===')
corpo = Client().get(f'/solicitacoes/{clinica.slug}/').content.decode()
confere('enviar os laudos dos exames' in corpo, 'a primeira tela diz que o portal recebe laudos')
confere('receber os laudos de exames que eu enviar' in corpo, 'o aviso de privacidade cita o envio')
perfil.patient_portal_requires_recent_visit = False
perfil.save(update_fields=['patient_portal_requires_recent_visit'])
b = navegador_identificado()
corpo = b.get(f'/solicitacoes/{clinica.slug}/solicitar/').content.decode()
confere('alert-danger' in corpo and 'APENAS laudos de exames e resultados finais' in corpo,
        'a pagina de solicitacao ja traz o aviso vermelho')
confere('Encerrar identificação' in corpo, 'e o botao de sair')
zera_balde()

if falhas:
    print(f'\nFALHA: {len(falhas)} problema(s):')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('\nOK: o laudo chega ao prontuario certo, e so o laudo.')
