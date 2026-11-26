"""A LME — laudo do medicamento de alto custo (CEAF) — no modelo do Ministério.

Tenta quebrar `documents/lme.py`, `documents/pdf/lme.py` e as telas. As
perguntas:

- o modelo é o travado (SHA-256), e todo campo que o código usa existe nele?
- a validação recusa cada item obrigatório que falta, o CNES/CNS/CPF de
  tamanho errado, o CID que não é CID-10, o "sim" sem o complemento, a
  quantidade que não é número, a sétima linha, e o texto que **não cabe**
  no campo — e aceita medicamento escrito livremente, fora da lista?
- o PDF é o formulário oficial **sem campos editáveis nem botões**, uma
  página, com cada valor **dentro do retângulo** do seu campo (medido pela
  posição do texto), a caixa certa marcada, a tarja no rascunho e o número
  e a data de Brasília no emitido?
- **a LME não é assinada digitalmente**: a recusa vem do servidor, sem
  número gasto, com a trilha; o papel funciona; o envio por link recusa?
- as telas: o aviso de "sempre impressa", o formulário que cria o rascunho
  e o que recusa sem criar nada, a página do documento sem "Assinar e
  emitir", os botões na Conduta e na ficha, a secretária e outra clínica de
  fora, "a partir desta" só do mesmo paciente, e o formulário genérico que
  não emite LME?
- o preenchimento inicial: peso e altura da ficha (altura em cm), o CNS do
  médico e a raça/cor da LME anterior, o CID das hipóteses do atendimento?
"""
import io
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from pypdf import PdfReader

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import Encounter
from documents import document_kinds, issuance, lme
from documents.models import Attachment, MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from documents.storage import read_bytes
from patients.models import Observation, ObservationKind, Patient
from tenancy.models import Membership, Tenant

DOMINIO = 'demo.neurodoc.local'
falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=tenant.id).filter(slug__startswith='demo-').first()
medico = User.objects.get(email=f'doctor-a@{DOMINIO}')
vinculo = Membership.objects.get(tenant=tenant, user=medico)
secretaria = User.objects.get(email=f'secretary-a@{DOMINIO}')
paciente = Patient.objects.create(tenant=tenant, full_name='Roteiro LME Paciente', mother_name='Roteiro LME Mae',
                                  cpf='52998224725')
outro_paciente = Patient.objects.create(tenant=tenant, full_name='Roteiro LME Outro')
observacoes = [
    Observation.objects.create(tenant=tenant, patient=paciente, kind=ObservationKind.WEIGHT,
                               numeric_value=Decimal('72.50'), unit='kg', observed_at=timezone.now()),
    Observation.objects.create(tenant=tenant, patient=paciente, kind=ObservationKind.HEIGHT,
                               numeric_value=Decimal('1.68'), unit='m', observed_at=timezone.now()),
]
atendimento = Encounter.objects.filter(tenant=tenant, patient__isnull=False).exclude(status='finalized').first()
criados_docs = []

COMPLETO = {
    'cnes': '1234567', 'estabelecimento': 'CLINICA ROTEIRO LME', 'paciente': 'ROTEIRO LME PACIENTE',
    'mae': 'ROTEIRO LME MAE', 'peso': '72,5', 'altura': '168',
    'medicamentos': [
        {'nome': 'Fingolimode 0,5 mg (cápsula)', 'quantidades': ['30', '30', '30', '30', '30', '30']},
        {'nome': 'Remédio escrito à mão 10 mg (fora da lista)', 'quantidades': ['60', '60', '60', '', '', '']},
    ],
    'cid': 'G35', 'diagnostico': 'Esclerose múltipla remitente-recorrente',
    'anamnese': 'Surtos em 2024 e 2025.\nRM com lesões novas captantes.',
    'tratamento_previo': 'sim', 'tratamento_relato': 'Betainterferona 1a de 2019 a 2024',
    'incapaz': 'nao', 'responsavel': '', 'medico': 'DRA. ROTEIRO', 'medico_cns': '700000000000005',
    'preenchido_por': 'medico', 'preenchido_outro_nome': '', 'preenchido_outro_cpf': '',
    'raca': 'parda', 'etnia': '', 'telefone1': '11999990000', 'telefone2': '',
    'documento_tipo': 'cpf', 'documento_numero': '529.982.247-25', 'email': 'roteiro@exemplo.invalid',
    'modelo': lme.VERSAO_MODELO,
}


def com(**mudancas):
    c = dict(COMPLETO)
    c.update(mudancas)
    return c


def recusa(conteudo):
    try:
        lme.validar(conteudo)
        return None
    except lme.LmeInvalida as exc:
        return exc.erros


def nova(conteudo=None, encounter=None, pac=None):
    d = issuance.create_draft(tenant, pac or paciente, encounter, vinculo, medico.id, MedicalDocumentKind.LME,
                              dict(conteudo or COMPLETO))
    criados_docs.append(d)
    return d


def pdf_do(documento):
    documento.refresh_from_db()
    anexo = documento.pdf_attachment
    return read_bytes(anexo)


def textos_com_posicao(pdf):
    pagina = PdfReader(io.BytesIO(pdf)).pages[0]
    saida = []

    def visitante(texto, cm, tm, *_):
        if texto.strip():
            x = tm[4] * cm[0] + cm[4]
            y = tm[5] * cm[3] + cm[5]
            saida.append((texto.strip(), x, y))

    pagina.extract_text(visitor_text=visitante)
    return saida


def dentro(pdf, texto, nome_campo, estado=None):
    ret = lme.retangulo_da_caixa(nome_campo, estado) if estado else lme.retangulo(nome_campo)
    x0, y0, x1, y1 = ret
    achados = [(x, y) for t, x, y in textos_com_posicao(pdf) if texto in t]
    return any(x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1 for x, y in achados), achados, ret


def entrar(usuario, clinica=tenant):
    c = Client()
    c.force_login(usuario)
    s = c.session
    s['tenant_id'] = str(clinica.id)
    s.save()
    return c


def post_do_formulario(conteudo):
    dados = {k: v for k, v in conteudo.items() if k not in ('medicamentos', 'modelo')}
    for n, item in enumerate(conteudo.get('medicamentos') or [], start=1):
        dados[f'med_{n}_nome'] = item['nome']
        for m, q in enumerate(item['quantidades'], start=1):
            dados[f'med_{n}_q{m}'] = q
    return dados


try:
    print('=== 1. o modelo do Ministério ===')
    conferir('o modelo confere com o SHA-256', bool(lme.carregar_modelo()))
    conferir('todo campo usado existe no modelo', not lme.campos_que_faltam(), lme.campos_que_faltam())
    sugeridos = lme.medicamentos_do_modelo()
    conferir('a lista de sugestão veio do modelo (mais de 300)', len(sugeridos) > 300, len(sugeridos))
    conferir('com fingolimode e natalizumabe', any('Fingolimode' in s for s in sugeridos)
             and any('Natalizumabe' in s for s in sugeridos))
    conferir('sem item vazio nem repetido', all(sugeridos) and len(set(sugeridos)) == len(sugeridos))

    print('=== 2. a validação ===')
    conferir('o conteúdo completo passa', recusa(COMPLETO) is None, recusa(COMPLETO))
    conferir('medicamento fora da lista do modelo passa', recusa(com(medicamentos=[
        {'nome': 'Qualquer coisa que o médico sabe 5 mg', 'quantidades': ['1', '', '', '', '', '']}])) is None)
    for chave in ('paciente', 'mae', 'peso', 'altura', 'anamnese', 'medico'):
        erros = recusa(com(**{chave: ''}))
        conferir(f'sem {chave}: recusada no campo', bool(erros) and chave in erros, erros)
    casos = {
        'CNES com 6 dígitos': (com(cnes='123456'), 'cnes'),
        'CNS do médico com 14 dígitos': (com(medico_cns='70000000000000'), 'medico_cns'),
        'CID-11 (8A40)': (com(cid='8A40'), 'cid'),
        'CID vazio': (com(cid=''), 'cid'),
        'peso com letra': (com(peso='72kg'), 'peso'),
        'altura em metros': (com(altura='1,68'), 'altura'),
        'tratamento "sim" sem relato': (com(tratamento_relato=''), 'tratamento_relato'),
        'tratamento sem resposta': (com(tratamento_previo=''), 'tratamento_previo'),
        'incapaz "sim" sem responsável': (com(incapaz='sim'), 'responsavel'),
        'incapaz sem resposta': (com(incapaz=''), 'incapaz'),
        '"outro" sem CPF': (com(preenchido_por='outro', preenchido_outro_nome='FULANO'), 'preenchido_outro_cpf'),
        'preenchido por valor inventado': (com(preenchido_por='robo'), 'preenchido_por'),
        'indígena sem etnia': (com(raca='indigena'), 'etnia'),
        'sem raça/cor': (com(raca=''), 'raca'),
        'CPF do paciente com 10 dígitos': (com(documento_numero='1234567890'), 'documento_numero'),
        'número sem dizer o documento': (com(documento_tipo=''), 'documento_tipo'),
        'sem medicamento': (com(medicamentos=[]), 'medicamentos'),
        'medicamento sem quantidade': (com(medicamentos=[{'nome': 'X', 'quantidades': [''] * 6}]), 'medicamento_1'),
        'quantidade com letra': (com(medicamentos=[{'nome': 'X', 'quantidades': ['3a', '', '', '', '', '']}]),
                                 'medicamento_1'),
        'quantidade de 5 dígitos': (com(medicamentos=[{'nome': 'X', 'quantidades': ['12345', '', '', '', '', '']}]),
                                    'medicamento_1'),
        'sete medicamentos': (com(medicamentos=[{'nome': f'M{i}', 'quantidades': ['1'] + [''] * 5}
                                                for i in range(7)]), 'medicamentos'),
        'anamnese que não cabe': (com(anamnese='palavra ' * 900), 'anamnese'),
        'medicamento que não cabe em duas linhas': (com(medicamentos=[
            {'nome': 'NOME MUITO LONGO ' * 20, 'quantidades': ['1'] + [''] * 5}]), 'medicamento_1'),
    }
    for rotulo, (conteudo, chave) in casos.items():
        erros = recusa(conteudo)
        conferir(f'{rotulo}: recusado', bool(erros) and chave in erros, erros)
    longo = ('DIPROPIONATO DE BECLOMETASONA + FUMARATO DE FORMOTEROL DI-HIDRATADO + BROMETO DE GLICOPIRRÔNIO '
             '(SOLUÇÃO AEROSSOL CONTENDO 120 DOSES)')
    conferir('o nome longo da lista cabe (duas linhas, letra menor)',
             recusa(com(medicamentos=[{'nome': longo, 'quantidades': ['1'] + [''] * 5}])) is None)
    conferir('CID normalizado (g350 → G35.0)', lme.normalizar_cid('g350') == 'G35.0' and lme.normalizar_cid('G35') == 'G35')
    conferir('caractere fora da fonte vira "?" (e não lixo)', lme.imprimivel('dose ≥ 2 ✓') == 'dose >= 2 ?')
    try:
        nova(com(cnes='1'))
        conferir('create_draft recusa CNES errado', False, 'criou')
    except ValueError as exc:
        conferir('create_draft recusa CNES errado (ValueError)', 'CNES' in str(exc), str(exc))

    print('=== 3. o PDF do rascunho ===')
    rascunho = nova()
    pdf = pdf_do(rascunho)
    leitor = PdfReader(io.BytesIO(pdf))
    conferir('uma página', len(leitor.pages) == 1, len(leitor.pages))
    conferir('sem campos editáveis nem botões (/Annots)', '/Annots' not in leitor.pages[0])
    conferir('sem formulário (/AcroForm)', '/AcroForm' not in leitor.trailer['/Root'])
    texto = leitor.pages[0].extract_text()
    conferir('o desenho oficial está lá', 'COMPONENTE ESPECIALIZADO' in texto and 'Atestado de capacidade' in texto)
    conferir('os botões do Acrobat sumiram', 'Salvar como' not in texto and 'Limpar' not in texto)
    conferir('a linha de suporte do Ministério redesenhada', 'ceaf.daf@saude.gov.br' in texto)
    conferir('tarja de rascunho', 'RASCUNHO' in texto)
    for valor, campo in (('ROTEIRO LME PACIENTE', 'Nome do paciente'), ('ROTEIRO LME MAE', 'Nome da mãe do paciente'),
                         ('1234567', 'CNES'), ('72,5', 'Peso'), ('168', 'Altura'), ('G35', 'CID'),
                         ('Fingolimode', 'Selecao med 1'), ('fora da lista', 'Selecao med 2'),
                         ('Betainterferona', 'Tratamento'), ('DRA. ROTEIRO', 'Médico Solicitante'),
                         ('700.0000.0000.0005', 'TextCNS'), ('(11) 99999-0000', 'Telefone I'),
                         ('529.982.247-25', 'Documento'), ('roteiro@exemplo.invalid', 'email'),
                         ('Surtos em 2024', 'Anamnese'), ('RM com lesões', 'Anamnese')):
        ok, achados, ret = dentro(pdf, valor, campo)
        conferir(f'"{valor}" dentro do campo {campo}', ok, f'{achados} fora de {ret}')
    ok, achados, ret = dentro(pdf, '30', 'Text8a')
    conferir('a quantidade do 6º mês da linha 1 no lugar dela', ok, f'{achados} fora de {ret}')
    ok, achados, ret = dentro(pdf, '60', 'Text12')
    conferir('a quantidade do 3º mês da linha 2 no lugar dela', ok, f'{achados} fora de {ret}')
    for chave, (campo, estados) in lme.CAIXAS.items():
        valor = COMPLETO.get(chave)
        if valor in estados:
            ok, achados, ret = dentro(pdf, 'X', campo, estados[valor])
            conferir(f'caixa marcada: {chave}={valor}', ok, f'{achados} fora de {ret}')
    xs = [t for t, *_ in textos_com_posicao(pdf) if t == 'X']
    conferir('só as caixas escolhidas levam X (5)', len(xs) == 5, len(xs))

    print('=== 4. a assinatura digital é recusada ===')
    issuance.mark_reviewed(rascunho, medico.id)
    rascunho.refresh_from_db()
    antes = AuditEvent.objects.filter(action='documents.medicaldocument_sign_failed', object_id=rascunho.id).count()
    try:
        issuance.sign_and_issue(rascunho, None, vinculo)
        conferir('a assinatura da LME é recusada', False, 'assinou')
    except issuance.NotReadyToSign as exc:
        conferir('recusada com NotReadyToSign, apontando o papel', 'impressa' in str(exc) and 'carimbar' in str(exc),
                 str(exc))
    rascunho.refresh_from_db()
    conferir('continua pronta para assinar', rascunho.status == MedicalDocumentStatus.READY_TO_SIGN, rascunho.status)
    conferir('nenhum número gasto', not rascunho.document_number, rascunho.document_number)
    evento = AuditEvent.objects.filter(action='documents.medicaldocument_sign_failed',
                                       object_id=rascunho.id).order_by('-created_at').first()
    conferir('a recusa na trilha, com o motivo', AuditEvent.objects.filter(
        action='documents.medicaldocument_sign_failed', object_id=rascunho.id).count() == antes + 1
        and (evento.integrity_metadata or {}).get('reason') == lme.MOTIVO_AUDITORIA)

    print('=== 5. emitida em papel ===')
    papel = issuance.issue_on_paper(rascunho, medico.id)
    papel.refresh_from_db()
    conferir('emitida em papel', papel.status == MedicalDocumentStatus.ISSUED_ON_PAPER, papel.status)
    ano = timezone.localdate().year
    conferir('número LME-<ano>-', re.fullmatch(rf'LME-{ano}-\d{{6}}', papel.document_number or ''),
             papel.document_number)
    pdf = pdf_do(papel)
    texto = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    conferir('sem a tarja de rascunho', 'RASCUNHO' not in texto)
    conferir('com o número no alto', papel.document_number in texto)
    hoje = timezone.localdate().strftime('%d/%m/%Y')
    ok, achados, ret = dentro(pdf, hoje, 'Today')
    conferir('a data de Brasília no campo 16', ok, f'{achados} fora de {ret}')
    conferir('sem PDF assinado', not papel.signed_pdf_attachment_id)

    print('=== 6. as telas ===')
    c = entrar(medico)
    from communications.models import Delivery

    c.post(f'/app/documents/medical/{papel.id}/enviar/')
    conferir('o envio por link recusa a LME em papel', not Delivery.objects.filter(document=papel).exists())
    html = c.get(f'/app/documents/medical/{papel.id}/').content.decode()
    conferir('a página da LME emitida: aviso de imprimir', 'data-nd-lme-impressa' in html)
    conferir('o PDF para imprimir, não "rascunho"', 'Baixar PDF para imprimir' in html)
    conferir('"Nova LME a partir desta"', 'Nova LME a partir desta' in html)
    conferir('sem retificação por texto', 'correction-form' not in html)

    outra_lme = nova()
    issuance.mark_reviewed(outra_lme, medico.id)
    html = c.get(f'/app/documents/medical/{outra_lme.id}/').content.decode()
    conferir('pronta: sem "Assinar e emitir"', 'Assinar e emitir' not in html and 'Habilitar sessão' not in html)
    conferir('pronta: "Emitir para assinar e carimbar" continua', 'Emitir para assinar e carimbar' in html)
    r = c.post(f'/app/documents/medical/{outra_lme.id}/sign/')
    outra_lme.refresh_from_db()
    conferir('POST de assinar não assina', outra_lme.status == MedicalDocumentStatus.READY_TO_SIGN, outra_lme.status)

    html = c.get(f'/app/documents/patients/{paciente.id}/lme/nova/').content.decode()
    conferir('a tela abre com o aviso de "sempre impressa"', 'A LME é sempre impressa' in html)
    conferir('com a lista de sugestão', 'nd-lme-medicamentos' in html and 'Fingolimode' in html)
    conferir('peso e altura da ficha (altura em cm)', 'value="72,5"' in html and 'value="168"' in html)
    conferir('CNS do médico da LME anterior', 'value="700000000000005"' in html)
    conferir('raça/cor da LME anterior', 'value="parda" selected' in html)
    conferir('CPF do cadastro', '529.982.247-25' in html)

    total = MedicalDocument.objects.filter(patient=paciente, kind=MedicalDocumentKind.LME).count()
    r = c.post(f'/app/documents/patients/{paciente.id}/lme/nova/', post_do_formulario(com(cnes='12')))
    conferir('envio inválido volta com o erro, sem criar', r.status_code == 200 and 'sete dígitos' in r.content.decode()
             and MedicalDocument.objects.filter(patient=paciente, kind=MedicalDocumentKind.LME).count() == total)
    r = c.post(f'/app/documents/patients/{paciente.id}/lme/nova/', post_do_formulario(COMPLETO))
    criada = MedicalDocument.objects.filter(patient=paciente, kind=MedicalDocumentKind.LME).order_by('-created_at').first()
    if criada and criada.id not in [d.id for d in criados_docs]:
        criados_docs.append(criada)
    conferir('envio válido cria o rascunho e leva ao documento', r.status_code == 302 and criada is not None
             and r['Location'].endswith(f'/medical/{criada.id}/'), r.status_code)
    conferir('o conteúdo gravado tem os medicamentos e o modelo',
             criada and len(criada.content_snapshot['medicamentos']) == 2
             and criada.content_snapshot['modelo'] == lme.VERSAO_MODELO)

    html = c.get(f'/app/documents/patients/{paciente.id}/lme/nova/?a_partir_de={papel.id}').content.decode()
    conferir('"a partir desta" traz a anamnese', 'Surtos em 2024' in html)
    html = c.get(f'/app/documents/patients/{outro_paciente.id}/lme/nova/?a_partir_de={papel.id}').content.decode()
    conferir('"a partir desta" de outro paciente é ignorado', 'Surtos em 2024' not in html)
    r = c.get(f'/app/documents/patients/{paciente.id}/lme/nova/?a_partir_de=nao-e-uuid')
    conferir('"a partir de" que não é id não dá erro', r.status_code == 200, r.status_code)

    if atendimento is not None:
        html = c.get(f'/app/clinical/{atendimento.id}/').content.decode()
        conferir('botão LME na Conduta', 'data-nd-lme' in html and f'/encounters/{atendimento.id}/lme/nova/' in html)
        r = c.get(f'/app/documents/encounters/{atendimento.id}/lme/nova/')
        conferir('a tela pelo atendimento abre', r.status_code == 200, r.status_code)
    html = c.get(f'/app/patients/{paciente.id}/').content.decode()
    conferir('botão LME na ficha', f'/patients/{paciente.id}/lme/nova/' in html)
    html = c.get(f'/app/documents/patients/{paciente.id}/medical/new/').content.decode()
    conferir('atalho da LME na tela "Emitir documento"', 'data-nd-lme' in html)
    conferir('o formulário genérico não oferece LME', 'value="lme"' not in html)
    antes = MedicalDocument.objects.filter(patient=paciente).count()
    c.post(f'/app/documents/patients/{paciente.id}/medical/new/', {'kind': 'lme', 'prescription_text': 'x'})
    conferir('POST forjado com kind=lme no genérico não cria',
             MedicalDocument.objects.filter(patient=paciente).count() == antes)

    s = entrar(secretaria)
    r = s.get(f'/app/documents/patients/{paciente.id}/lme/nova/')
    conferir('secretária não abre a tela', r.status_code in (403, 404), r.status_code)
    r = s.post(f'/app/documents/patients/{paciente.id}/lme/nova/', post_do_formulario(COMPLETO))
    conferir('secretária não cria', r.status_code in (403, 404), r.status_code)
    if outra is not None:
        estranho = Patient.objects.filter(tenant=outra).first()
        if estranho is not None:
            r = c.get(f'/app/documents/patients/{estranho.id}/lme/nova/')
            conferir('paciente de outra clínica em 404', r.status_code == 404, r.status_code)

    antes = MedicalDocument.objects.filter(patient=paciente).count()
    r = c.post(f'/app/documents/medical/{papel.id}/correction/', {'kind': 'lme', 'prescription_text': 'x'})
    conferir('retificação forjada de LME não cria nada', r.status_code in (200, 403)
             and MedicalDocument.objects.filter(patient=paciente).count() == antes, r.status_code)

    print('=== 7. o tipo no resto do sistema ===')
    conferir('prefixo e título', document_kinds.NUMBER_PREFIX[MedicalDocumentKind.LME] == 'LME'
             and 'LME' in document_kinds.TITLE[MedicalDocumentKind.LME])
finally:
    print('=== limpeza ===')
    ids = [d.id for d in criados_docs]
    ids += list(MedicalDocument.objects.filter(patient__in=[paciente, outro_paciente]).values_list('id', flat=True))
    anexos = []
    for d in MedicalDocument.objects.filter(id__in=ids).values('pdf_attachment_id', 'signed_pdf_attachment_id'):
        anexos += [v for v in d.values() if v]
    MedicalDocument.objects.filter(id__in=ids).delete()
    from pathlib import Path

    anexos += list(Attachment.objects.filter(patient__in=[paciente, outro_paciente]).values_list('id', flat=True))
    for att in Attachment.objects.filter(id__in=anexos):
        if att.storage_key:
            Path(att.storage_key).unlink(missing_ok=True)
    Attachment.objects.filter(id__in=anexos).delete()
    for o in observacoes:
        o.delete()
    paciente.delete()
    outro_paciente.delete()
    print(f'  {len(set(ids))} documento(s), {len(set(anexos))} anexo(s) e 2 pacientes removidos')

if falhas:
    print(f'\n{len(falhas)} FALHA(S):')
    for f in falhas:
        print('  -', f)
    raise SystemExit(1)
print('\nTODAS AS CONFERÊNCIAS PASSARAM')
