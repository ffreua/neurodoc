"""Receita eletrônica do SNCR: itens, classificação, limites, o PDF oficial e o número.

Sprint 2 da integração (`docs/sncr/`). A numeração é a da Sprint 1, com
os blocos registrados aqui como se a Anvisa os tivesse entregado — o
teste real é o primeiro pedido em produção (decisão D8). A **assinatura é
real**: o roteiro gera um certificado de teste, assina o PDF com o pyHanko
e valida a assinatura. Tenta quebrar. As perguntas são:

- a regra: quantidade por extenso com o gênero certo; 1, 2 e 3
  medicamentos passam e o quarto não; o art. 57 (3 substâncias da C1 por
  receita) vale **por folha** — 4 da C1 espalhadas em dois medicamentos
  passam, 4 num medicamento só não; controlado de Notificação
  (clonazepam) não entra na RCE; o do adendo (tramadol) e o que a lista
  não acha só entram com a confirmação do médico; a marca é resolvida
  pela substância da CMED; controlado na RET é recusado (FAQ P48)?
- a porta: integração desligada, paciente sem CPF e RCE sem endereço
  recusam o rascunho; com ela desligada, o formulário nem oferece o
  formato?
- o rascunho: os itens estruturados, a prescrição em texto para quem já a
  lê, e o PDF **no modelo da Anvisa** (os rótulos do modelo, o tamanho da
  página, nenhum timbre da clínica), com "RASCUNHO" e sem número?
- a assinatura: **uma folha e um número por medicamento** (decisão I12),
  o n-ésimo número na n-ésima folha, todos do bloco **do médico** e
  consumidos só depois de assinado; faltando número para alguma folha,
  nenhuma sai e nenhum número é gasto; registrado nos metadados; a assinatura PAdES válida;
  sem número livre, a recusa vai à trilha e o documento continua pronto;
  falha na assinatura devolve o número a livre; o outro médico da clínica
  não usa o bloco; o mesmo médico usa o bloco nas duas clínicas; o número
  da homologação sai com "HOMOLOGAÇÃO"?
- o que não muda: o papel e a retificação recusam a eletrônica, e as
  receitas impressas continuam com o leiaute da clínica e sem os itens?
"""
import io
import secrets
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from asn1crypto import x509 as a1x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pypdf import PdfReader

from accounts.models import PhysicianProfile, User
from audit.models import AuditEvent
from documents import issuance
from documents.forms import MedicalDocumentForm
from documents.models import Attachment, MedicalDocument, MedicalDocumentStatus
from documents.signing import validate_signed_pdf
from documents.storage import read_bytes
from patients.models import Patient
from sncr import numeracao, receita
from sncr.models import (
    BlocoNumeracao, Configuracao, EstadoNumero, EstadoPedido, NumeroSncr, PedidoNumeracao,
)
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


def recusa(funcao, *args, **kwargs):
    """A mensagem da recusa, ou `None` se passou."""
    try:
        funcao(*args, **kwargs)
    except ValueError as exc:
        return str(exc)
    return None


tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
user_a = User.objects.get(email='doctor-a@demo.neurodoc.local')
user_b = User.objects.get(email='doctor-b@demo.neurodoc.local')
vinculo_a = Membership.objects.get(tenant=tenant_a, user=user_a)
vinculo_a_b = Membership.objects.get(tenant=tenant_b, user=user_a)
vinculo_b = Membership.objects.get(tenant=tenant_a, user=user_b)
medico_a = PhysicianProfile.objects.get(user=user_a)
medico_b = PhysicianProfile.objects.get(user=user_b)
config = Configuracao.carregar()
original_config = (config.ativo, config.ambiente, config.cnpj_mantenedora)
CNPJ = '11222333000181'

pacientes, documentos = [], []


def cpf_valido():
    while True:
        base = [secrets.randbelow(10) for _ in range(9)]
        for _ in range(2):
            soma = sum(d * p for d, p in zip(base, range(len(base) + 1, 1, -1)))
            base.append((soma * 10 % 11) % 10)
        texto = ''.join(map(str, base))
        if len(set(texto)) > 1 and not Patient.objects.filter(cpf=texto).exists():
            return texto


def paciente(tenant, **extra):
    dados = dict(
        full_name=f'PACIENTE ROTEIRO SNCR {secrets.token_hex(3).upper()}', birth_date=date(1980, 5, 1),
        cpf=cpf_valido(), street='Rua das Acácias', number='120', district='Jardim Paulista',
        city='São Paulo', state='SP', postal_code='01415000', sex_at_registration='female',
    )
    dados.update(extra)
    p = Patient.objects.create(tenant=tenant, **dados)
    pacientes.append(p.id)
    return p


def itens(*lista):
    campos = {'prescription_text': '', 'special_instructions': ''}
    for n, (nome, conc, forma, qtd, poso) in enumerate(lista, start=1):
        campos.update({f'item{n}_nome': nome, f'item{n}_concentracao': conc, f'item{n}_forma': forma,
                       f'item{n}_quantidade': qtd, f'item{n}_posologia': poso})
    return campos


SERTRALINA = ('Sertralina', '50 mg', 'comprimido revestido', '60 comprimidos', '1 comprimido pela manhã')
PREGABALINA = ('Pregabalina', '75 mg', 'cápsula dura', '60 cápsulas', '1 cápsula de 12 em 12 horas')
TEGRETOL = ('Tegretol', '200 mg', 'comprimido', '90 comprimidos', '1 comprimido de 8 em 8 horas')
CLONAZEPAM = ('Clonazepam', '2 mg', 'comprimido', '30 comprimidos', '1 comprimido à noite')
TRAMADOL = ('Tramadol', '50 mg', 'cápsula', '20 cápsulas', '1 cápsula de 8 em 8 horas se dor')
AMOXICILINA = ('Amoxicilina', '500 mg', 'cápsula', '21 cápsulas', '1 cápsula de 8 em 8 horas por 7 dias')


def rascunho(paciente_, formato, campos, vinculo=None, confirmada=False):
    vinculo = vinculo or vinculo_a
    conteudo = dict(campos, prescription_format=formato, classificacao_confirmada=confirmada)
    doc = issuance.create_draft(vinculo.tenant, paciente_, None, vinculo, vinculo.user_id, 'prescription', conteudo)
    documentos.append(doc.id)
    return doc


def bloco(medico, tipo, inicio, fim, ambiente='producao'):
    pedido = PedidoNumeracao.objects.create(
        medico=medico, solicitado_por=medico.user, tenant=tenant_a, tipo=tipo, ambiente=ambiente,
        uf=medico.crm_state, documento=medico.crm_number, cnpj=CNPJ, estado=EstadoPedido.CONCLUIDO,
    )
    return numeracao.registrar_bloco(pedido, {'inicio': inicio, 'fim': fim})


def limpar_numeracao():
    for medico in (medico_a, medico_b):
        NumeroSncr.objects.filter(medico=medico).delete()
        BlocoNumeracao.objects.filter(medico=medico).delete()
        PedidoNumeracao.objects.filter(medico=medico).delete()


# --- certificado de teste e a sessão de assinatura simulada --------------------
chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'DRA ANA NEURO:00000000191')])
agora = datetime.now(dt_timezone.utc)
certificado = (
    x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=1))
    .not_valid_after(agora + timedelta(days=30))
    .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
    .sign(chave, hashes.SHA256())
)
SENHA = 'senha-do-roteiro'
PFX = pkcs12.serialize_key_and_certificates(
    b'roteiro', chave, certificado, None, serialization.BestAvailableEncryption(SENHA.encode()),
)


class Credencial:
    certificate_serial = format(certificado.serial_number, 'X')
    certificate_fingerprint = certificado.fingerprint(hashes.SHA256()).hex()


class Sessao:
    credential = Credencial()


SIMULADOS = {
    'get_active_session': lambda request, membro: Sessao(),
    'credential_is_usable': lambda credencial: True,
    'decrypt_pfx_bytes': lambda credencial: PFX,
    'unlock_password': lambda sessao: SENHA,
}


def assinar(doc, vinculo=None, sign_pdf=None):
    """Assina de verdade, trocando só a sessão (que exige navegador e tmpfs)."""
    guardado = {n: getattr(issuance, n) for n in [*SIMULADOS, 'sign_pdf']}
    for n, f in SIMULADOS.items():
        setattr(issuance, n, f)
    if sign_pdf is not None:
        issuance.sign_pdf = sign_pdf
    try:
        doc.status = MedicalDocumentStatus.READY_TO_SIGN
        doc.save(update_fields=['status'])
        return issuance.sign_and_issue(doc, None, vinculo or vinculo_a)
    finally:
        for n, f in guardado.items():
            setattr(issuance, n, f)


def guardar(nome, dados):
    """Com `ND_GUARDAR_PDF=<pasta>`, grava o PDF para conferência visual."""
    import os

    pasta = os.environ.get('ND_GUARDAR_PDF')
    if pasta:
        with open(os.path.join(pasta, f'{nome}.pdf'), 'wb') as arquivo:
            arquivo.write(dados)


def texto_do_pdf(dados):
    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(dados)).pages)


try:
    limpar_numeracao()
    config.ativo, config.ambiente, config.cnpj_mantenedora = True, 'producao', CNPJ
    config.save()
    p = paciente(tenant_a)

    print('=== 1. a quantidade por extenso ===')
    for entrada, esperado in (('60 comprimidos', '60 (sessenta) comprimidos'), ('1 caixa', '1 (uma) caixa'),
                              ('21 cápsulas', '21 (vinte e uma) cápsulas'), ('200 gotas', '200 (duzentas) gotas'),
                              ('1230 ml', '1230 (mil duzentos e trinta) ml'),
                              ('30 (trinta) comprimidos', '30 (trinta) comprimidos')):
        conferir(f'"{entrada}"', receita.quantidade_com_extenso(entrada) == esperado,
                 receita.quantidade_com_extenso(entrada))
    conferir('quantidade sem número é recusada', recusa(receita.quantidade_com_extenso, 'uma caixa') is not None)

    print('=== 2. quantos medicamentos ===')
    for n, lista in ((1, [SERTRALINA]), (2, [SERTRALINA, PREGABALINA]), (3, [SERTRALINA, PREGABALINA, TEGRETOL])):
        doc = rascunho(p, receita.SNCR_RCE, itens(*lista))
        conferir(f'{n} medicamento(s) passam', len(doc.content_snapshot['itens']) == n)
    quatro = dict(itens(SERTRALINA, PREGABALINA, TEGRETOL),
                  item4_nome='Topiramato', item4_concentracao='25 mg', item4_forma='comprimido',
                  item4_quantidade='30 comprimidos', item4_posologia='1 à noite')
    erro = recusa(rascunho, p, receita.SNCR_RCE, quatro)
    conferir('o quarto medicamento (montado à mão) é recusado, não ignorado', erro and 'No máximo 3' in erro, erro)
    erro = recusa(rascunho, p, receita.SNCR_RCE, itens(
        ('Fluoxetina e olanzapina', '20 mg + 5 mg', 'cápsula', '30 cápsulas', '1 à noite'),
        ('Sertralina e topiramato', '50 mg + 25 mg', 'comprimido', '30 comprimidos', '1 ao dia'),
    ))
    conferir('4 substâncias da C1 em 2 medicamentos passam: cada folha é uma receita (art. 57 por folha)',
             erro is None, erro)
    erro = recusa(rascunho, p, receita.SNCR_RCE, itens(
        ('Fluoxetina, olanzapina, sertralina e topiramato', '20 mg + 5 mg + 50 mg + 25 mg', 'cápsula',
         '30 cápsulas', '1 à noite'),
    ))
    conferir('4 substâncias da C1 num medicamento só: art. 57 recusa', erro and 'art. 57' in erro, erro)
    erro = recusa(rascunho, p, receita.SNCR_RCE, dict(itens(SERTRALINA), item2_nome='Pregabalina'))
    conferir('medicamento pela metade é recusado com o que falta', erro and 'Medicamento 2' in erro, erro)

    print('=== 3. a classificação pela lista oficial ===')
    erro = recusa(rascunho, p, receita.SNCR_RCE, itens(CLONAZEPAM))
    conferir('clonazepam (B1) pede Notificação e não entra na RCE', erro and 'Notificação' in erro and 'B1' in erro, erro)
    erro = recusa(rascunho, p, receita.SNCR_RCE, itens(TRAMADOL))
    conferir('tramadol (adendo da A2) sem confirmação: recusado, citando o adendo', erro and 'adendo' in erro, erro)
    doc = rascunho(p, receita.SNCR_RCE, itens(TRAMADOL), confirmada=True)
    conferir('tramadol com a confirmação do médico: passa e a confirmação fica gravada',
             doc.content_snapshot['classificacao_confirmada'] is True)
    erro = recusa(rascunho, p, receita.SNCR_RCE, itens(AMOXICILINA))
    conferir('amoxicilina na RCE (nada da C1/C5): recusada', erro and 'receita simples' in erro, erro)
    doc = rascunho(p, receita.SNCR_RCE, itens(TEGRETOL))
    cls = doc.content_snapshot['classificacao'][0]
    conferir('a marca (Tegretol) é resolvida pela substância da CMED',
             cls['origem'] == 'cmed' and cls['substancias'][0]['lista'] == 'C1', cls)
    conferir('a versão da lista oficial fica no documento', doc.content_snapshot['lista_oficial'].startswith('RDC'))
    erro = recusa(rascunho, p, receita.SNCR_RET, itens(SERTRALINA))
    conferir('controlado na RET é recusado (FAQ P48)', erro and 'Portaria 344' in erro, erro)
    doc_ret = rascunho(p, receita.SNCR_RET, itens(AMOXICILINA))
    conferir('antimicrobiano na RET passa', doc_ret.content_snapshot['itens'][0]['nome'] == 'Amoxicilina')

    print('=== 4. a porta ===')
    config.ativo = False
    config.save()
    erro = recusa(rascunho, p, receita.SNCR_RCE, itens(SERTRALINA))
    conferir('integração desligada: o rascunho é recusado', erro and 'não está ligada' in erro, erro)
    formatos = dict(MedicalDocumentForm().fields['prescription_format'].choices)
    conferir('desligada, o formulário nem oferece o formato', receita.SNCR_RCE not in formatos)
    config.ativo = True
    config.save()
    formatos = dict(MedicalDocumentForm().fields['prescription_format'].choices)
    conferir('ligada, oferece as duas eletrônicas', receita.SNCR_RCE in formatos and receita.SNCR_RET in formatos)
    sem_cpf = paciente(tenant_a, cpf=None)
    erro = recusa(rascunho, sem_cpf, receita.SNCR_RCE, itens(SERTRALINA))
    conferir('paciente sem CPF: recusado', erro and 'CPF' in erro, erro)
    sem_endereco = paciente(tenant_a, street='', city='', state='')
    erro = recusa(rascunho, sem_endereco, receita.SNCR_RCE, itens(SERTRALINA))
    conferir('RCE sem endereço do paciente: recusada', erro and 'endereço' in erro, erro)
    form = MedicalDocumentForm(data=dict(itens(), kind='prescription', prescription_format=receita.SNCR_RCE))
    conferir('o formulário exige o primeiro medicamento inteiro', not form.is_valid() and 'item1_nome' in form.errors)

    print('=== 5. o rascunho ===')
    doc = rascunho(p, receita.SNCR_RCE, itens(SERTRALINA, PREGABALINA))
    conferir('a prescrição em texto existe para quem já a lê',
             doc.content_snapshot['prescription_text'].startswith('1. Sertralina') and
             '60 (sessenta) comprimidos' in doc.content_snapshot['prescription_text'])
    conferir('nenhum campo solto de item fica no conteúdo',
             not any(k.startswith('item') for k in doc.content_snapshot))
    pdf = read_bytes(doc.pdf_attachment)
    texto = texto_do_pdf(pdf)
    leitor = PdfReader(io.BytesIO(pdf))
    for rotulo in ('RECEITA DE CONTROLE ESPECIAL', 'ELETRÔNICA', 'EMITENTE', 'PACIENTE', 'PRESCRIÇÃO',
                   'NOME DO MEDICAMENTO OU SUBSTÂNCIA', 'IDENTIFICAÇÃO DA PLATAFORMA',
                   'VALIDE ESSA ASSINATURA EM', 'sncr.anvisa.gov.br'):
        conferir(f'rótulo do modelo: {rotulo}', rotulo in texto)
    caixas = {tuple(round(float(v), 1) for v in pg.mediabox) for pg in leitor.pages}
    conferir('as páginas são as do modelo (595,5 × 842,25)', caixas == {(0.0, 7.8, 595.5, 850.1)}, caixas)
    conferir('uma folha por medicamento (2 medicamentos, 2 folhas)', len(leitor.pages) == 2, len(leitor.pages))
    folhas = [pg.extract_text() or '' for pg in leitor.pages]
    conferir('cada folha só com o seu medicamento',
             'Sertralina' in folhas[0] and 'Pregabalina' not in folhas[0]
             and 'Pregabalina' in folhas[1] and 'Sertralina' not in folhas[1])
    conferir('cada folha é uma receita inteira (emitente, paciente e rodapé em todas)',
             all('EMITENTE' in f and 'PACIENTE' in f and 'sncr.anvisa.gov.br' in f and p.full_name in f
                 for f in folhas))
    conferir('a folha diz de quantas faz parte', 'receita 1 de 2' in folhas[0] and 'receita 2 de 2' in folhas[1])
    conferir('o rascunho diz que não vale, nas duas', all('RASCUNHO' in f for f in folhas))
    conferir('sem número no rascunho', all('atribuído pelo SNCR na assinatura' in f for f in folhas))
    unica = rascunho(p, receita.SNCR_RCE, itens(SERTRALINA))
    texto_unica = texto_do_pdf(read_bytes(unica.pdf_attachment))
    conferir('um medicamento: uma folha, sem "receita 1 de 1"',
             len(PdfReader(io.BytesIO(read_bytes(unica.pdf_attachment))).pages) == 1
             and 'receita 1 de' not in texto_unica)
    nomes_da_clinica = [n for n in (tenant_a.legal_name, getattr(tenant_a, 'trade_name', '')) if n]
    conferir('nenhum timbre da clínica (nome da clínica ausente)',
             nomes_da_clinica and not any(n in texto for n in nomes_da_clinica), nomes_da_clinica)
    conferir('os valores estão no PDF', 'Sertralina' in texto and '60 (sessenta) comprimidos' in texto)
    erro = recusa(issuance.issue_on_paper, doc, user_a.id)
    conferir('a eletrônica não é emitida em papel', erro and 'só existe assinada' in erro, erro)

    print('=== 6. a assinatura e o número ===')
    erro = None
    try:
        assinar(doc)
    except Exception as exc:  # noqa: BLE001 — a recusa é o que se testa
        erro = str(exc)
    doc.refresh_from_db()
    conferir('sem número livre: recusado, com o caminho', erro and 'bloco' in erro, erro)
    conferir('e o documento continua pronto para assinar', doc.status == MedicalDocumentStatus.READY_TO_SIGN)
    conferir('a recusa vai à trilha', AuditEvent.objects.filter(
        object_id=doc.id, action='documents.medicaldocument_sign_failed',
        integrity_metadata__reason='sncr_sem_numero').exists())

    bloco_a = bloco(medico_a, 'RCE', '000000100', '000000104')
    bloco(medico_b, 'RCE', '000000900', '000000904')
    falhou = None
    try:
        def quebra(*a, **k):
            from documents.signing import SigningFailed
            raise SigningFailed('roteiro')
        assinar(doc, sign_pdf=quebra)
    except Exception as exc:  # noqa: BLE001
        falhou = exc
    conferir('falha na assinatura: erro devolvido', falhou is not None)
    conferir('e os números voltam a livre (o PDF nunca saiu do servidor)',
             numeracao.saldo(medico_a, 'RCE', 'producao') == 5)

    emitido = assinar(doc)
    emitido.refresh_from_db()
    numeros = list(NumeroSncr.objects.filter(documento=emitido).order_by('ordem'))
    conferir('assinado e emitido', emitido.status == MedicalDocumentStatus.ISSUED)
    conferir('dois medicamentos, dois números: os dois primeiros do bloco do médico',
             [n.numero for n in numeros] == ['000000100', '000000101']
             and all(n.bloco_id == bloco_a.id for n in numeros), [n.numero for n in numeros])
    conferir('consumidos, e só depois de assinado', all(n.estado == EstadoNumero.CONSUMIDO for n in numeros))
    conferir('nos metadados da assinatura, na ordem das folhas',
             emitido.signature_metadata.get('sncr', {}).get('numeros') == ['000000100', '000000101'],
             emitido.signature_metadata.get('sncr'))
    assinado = read_bytes(emitido.signed_pdf_attachment)
    texto = texto_do_pdf(assinado)
    folhas = [pg.extract_text() or '' for pg in PdfReader(io.BytesIO(assinado)).pages]
    conferir('cada número na folha do seu medicamento, e só nela',
             len(folhas) == 2 and '000000100' in folhas[0] and 'Sertralina' in folhas[0]
             and '000000101' not in folhas[0] and '000000101' in folhas[1] and 'Pregabalina' in folhas[1]
             and '000000100' not in folhas[1])
    conferir('o QR e a verificação em todas as folhas',
             all(f'/verificar/{emitido.validation_token}/' in f for f in folhas))
    conferir('o registro da assinatura está no PDF', 'Assinado digitalmente por' in texto and 'ICP-Brasil' in texto)
    conferir('a verificação aponta para o NeuroDoc', f'/verificar/{emitido.validation_token}/' in texto)
    conferir('a assinada não diz rascunho', 'RASCUNHO' not in texto)
    validacao = validate_signed_pdf(assinado, a1x509.Certificate.load(certificado.public_bytes(serialization.Encoding.DER)))
    conferir('a assinatura PAdES é íntegra e válida', validacao.intact and validacao.valid,
             f'intact={validacao.intact} valid={validacao.valid} coverage={validacao.coverage.name}')
    guardar('rce_assinada', assinado)
    erro = recusa(issuance.create_correction, emitido, user_a.id, {})
    conferir('a eletrônica emitida não é retificada', erro and 'não é retificada' in erro, erro)

    outro = rascunho(paciente(tenant_a), receita.SNCR_RCE, itens(SERTRALINA))
    outro = assinar(outro)
    conferir('a receita seguinte leva o número seguinte', NumeroSncr.objects.get(documento=outro).numero == '000000102')

    do_b = rascunho(paciente(tenant_a), receita.SNCR_RCE, itens(SERTRALINA), vinculo=vinculo_b)
    do_b = assinar(do_b, vinculo=vinculo_b)
    num_b = NumeroSncr.objects.get(documento=do_b)
    conferir('o outro médico da clínica usa o bloco dele, nunca o da colega',
             num_b.medico_id == medico_b.id and num_b.numero == '000000900', num_b.numero)

    na_b = rascunho(paciente(tenant_b), receita.SNCR_RCE, itens(SERTRALINA), vinculo=vinculo_a_b)
    na_b = assinar(na_b, vinculo=vinculo_a_b)
    num_na_b = NumeroSncr.objects.get(documento=na_b)
    conferir('o mesmo médico usa o mesmo bloco na outra clínica, com a clínica registrada',
             num_na_b.bloco_id == bloco_a.id and num_na_b.tenant_id == tenant_b.id, num_na_b.numero)

    tres = rascunho(paciente(tenant_a), receita.SNCR_RCE, itens(SERTRALINA, PREGABALINA, TEGRETOL))
    erro = None
    try:
        assinar(tres)
    except Exception as exc:  # noqa: BLE001 — a recusa é o que se testa
        erro = str(exc)
    tres.refresh_from_db()
    conferir('3 medicamentos com 1 número livre: recusado, dizendo quantas folhas', erro and '3 folha' in erro, erro)
    conferir('e nenhum número foi gasto nem ficou reservado',
             numeracao.saldo(medico_a, 'RCE', 'producao') == 1
             and not NumeroSncr.objects.filter(documento=tres).exists())
    conferir('e o rascunho continua pronto para assinar', tres.status == MedicalDocumentStatus.READY_TO_SIGN)

    config.ambiente = 'homologacao'
    config.save()
    bloco(medico_a, 'RCE', '000000500', '000000501', ambiente='homologacao')
    treino = assinar(rascunho(paciente(tenant_a), receita.SNCR_RCE, itens(SERTRALINA)))
    texto = texto_do_pdf(read_bytes(treino.signed_pdf_attachment))
    conferir('número da homologação sai marcado como sem validade', 'HOMOLOGAÇÃO' in texto)
    config.ambiente = 'producao'
    config.save()

    print('=== 7. a RET ===')
    bloco(medico_a, 'RET', '000000700', '000000701')
    ret = assinar(doc_ret)
    texto = texto_do_pdf(read_bytes(ret.signed_pdf_attachment))
    guardar('ret_assinada', read_bytes(ret.signed_pdf_attachment))
    conferir('a RET sai com o título dela, sem o da RCE',
             'RECEITA SUJEITA À RETENÇÃO' in texto and 'CONTROLE ESPECIAL' not in texto)
    conferir('com idade e sexo do paciente (RDC 471)', 'IDADE E SEXO' in texto and 'anos' in texto)
    conferir('e o número do bloco RET', NumeroSncr.objects.get(documento=ret).tipo == 'RET')

    print('=== 8. o que não muda ===')
    simples = issuance.create_draft(tenant_a, p, None, vinculo_a, user_a.id, 'prescription', dict(
        itens(), prescription_format='simple', prescription_text='Dipirona 500 mg', classificacao_confirmada=False))
    documentos.append(simples.id)
    conferir('a receita simples não guarda campos de item', set(simples.content_snapshot) == {
        'prescription_format', 'prescription_text', 'special_instructions'}, sorted(simples.content_snapshot))
    texto = texto_do_pdf(read_bytes(simples.pdf_attachment))
    conferir('e continua no leiaute da clínica (timbre, sem o modelo da Anvisa)',
             'Receita médica' in texto and 'EMITENTE' not in texto)
    especial = issuance.create_draft(tenant_a, p, None, vinculo_a, user_a.id, 'prescription', dict(
        itens(), prescription_format='special_control', prescription_text='Sertralina 50 mg',
        classificacao_confirmada=False))
    documentos.append(especial.id)
    texto = texto_do_pdf(read_bytes(especial.pdf_attachment))
    conferir('a RCE impressa continua em duas vias, no leiaute da clínica',
             'RETENÇÃO DA FARMÁCIA' in texto and 'EMITENTE' not in texto)

    print('=== 9. a tela ===')
    c = Client()
    c.force_login(user_a)
    s = c.session
    s['tenant_id'] = str(tenant_a.id)
    s.save()
    pagina = c.get(f'/app/documents/medical/{emitido.id}/')
    html = pagina.content.decode()
    conferir('o detalhe mostra os números SNCR, um por medicamento, e a classificação',
             pagina.status_code == 200 and '000000100, 000000101' in html and 'SNCR 000000101' in html
             and 'lista C1' in html, pagina.status_code)
    conferir('e não oferece retificação', 'Correção (nova versão)' not in html)
    novo = c.get(f'/app/documents/patients/{p.id}/medical/new/').content.decode()
    conferir('o formulário traz os três medicamentos e a confirmação',
             'item3_posologia' in novo and 'classificacao_confirmada' in novo and 'data-nd-rx="sncr"' in novo)
    conferir('ligada, o menu mostra "Numeração SNCR" a quem emite', 'Numeração SNCR' in novo)
    config.ativo = False
    config.save()
    conferir('desligada, o menu não mostra', 'Numeração SNCR' not in c.get('/app/documents/patients/'
                                                                         f'{p.id}/medical/new/').content.decode())
    config.ativo = True
    config.save()
    secretaria = Client()
    secretaria.force_login(User.objects.get(email='secretary-a@demo.neurodoc.local'))
    s = secretaria.session
    s['tenant_id'] = str(tenant_a.id)
    s.save()
    conferir('a secretária não vê o item no menu',
             'Numeração SNCR' not in secretaria.get('/app/patients/').content.decode())
finally:
    print('=== limpeza ===')
    NumeroSncr.objects.filter(documento_id__in=documentos).update(documento=None)
    limpar_numeracao()
    for d in MedicalDocument.objects.filter(id__in=documentos):
        anexos = [a for a in (d.pdf_attachment_id, d.signed_pdf_attachment_id) if a]
        d.delete()
        Attachment.objects.filter(id__in=anexos).delete()
    Patient.objects.filter(id__in=pacientes).delete()
    config.ativo, config.ambiente, config.cnpj_mantenedora = original_config
    config.save()
    print('  rascunhos, receitas, blocos, números e pacientes do roteiro removidos; configuração restaurada')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: receita eletrônica do SNCR — classificação pela lista oficial, limites, modelo da Anvisa,')
print('    número do bloco do médico consumido só depois de assinado, e o papel intocado.')
