"""Notificação de Receita A, B e B2 eletrônica (1.34): os números, a regra, o PDF e o QR.

Decisões D9, D10 e I17 a I20 de `docs/sncr/DECISOES.md`. A Anvisa é
**simulada** (`httpx.MockTransport`) — o teste real é a primeira Notificação
com a cota da Vigilância Sanitária (D10) — e a **assinatura é real**, com
certificado de teste. Tenta quebrar. As perguntas são:

- o pedido de números: sem CNPJ da mantenedora ele começa (a Notificação não
  o leva); o corpo é o do manual (`receita`, `conselho`, `uf`, `documento`,
  `quantidade`) e sem `cnpj`; o lote padrão é 10, o médico escolhe até 50,
  fora de 10 a 50 é recusado sem pedido; a lista vem como lista **ou** como
  texto e vira um número por linha, como texto; o saldo da cota fica gravado;
  com 3 ou mais livres não se pede outro, com menos sim; o limite de 50 por
  dia barra o que não cabe;
- os desfechos: sem cota (400) é recusa; 500, tempo esgotado depois de enviar,
  lista irreconhecível e erro nosso são **incertos**; lista vazia é recusa;
  número repetido na lista ou já registrado deixa o lote não utilizável;
- o incerto barra pedido novo e é **dado por perdido** pelo próprio médico (não
  conferido como o bloco da RCE; nem por outro médico, nem pela secretária), e
  então libera; o pedido parado vira incerto com o texto da Notificação;
- a regra: cada medicamento é do tipo da Notificação (clonazepam na B,
  metilfenidato na A, sibutramina na B2, a marca pela CMED), o tipo errado é
  recusado apontando o certo, o que vai à RCE ou à receita simples é recusado,
  retinoide e talidomida vão ao talonário, o desconhecido só com confirmação,
  o adendo da lista passa; endereço e CPF do paciente; uso contínuo; a RCE
  recusa o clonazepam apontando a Notificação B;
- o PDF: o modelo oficial de cada tipo (título, página do modelo), uma folha
  por medicamento, e os valores **nas posições da Notificação**, não nas da
  RCE — e a RCE continua nas dela;
- a assinatura: um número do lote por folha, consumido só depois de
  assinado; o QR de cada folha abre a **consulta do número no SNCR** (o de
  treinamento na homologação), e a verificação do NeuroDoc fica no rodapé;
  sem número, a recusa fala do lote e da Vigilância; papel, contingência e
  retificação recusados;
- as telas: os formatos no formulário, o aviso dos limites, os saldos, a
  validade de 30 dias no detalhe, a Notificação sem "Refazer como impressa".
"""
import io
import json
import secrets
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

import httpx
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
from sncr import cliente as api
from sncr import fluxo, numeracao, pdf_oficial, receita
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
    try:
        funcao(*args, **kwargs)
    except ValueError as exc:
        return str(exc)
    return None


tenant_a = Tenant.objects.get(slug='demo-clinica-a')
user_a = User.objects.get(email='doctor-a@demo.neurodoc.local')
user_b = User.objects.get(email='doctor-b@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
vinculo_a = Membership.objects.get(tenant=tenant_a, user=user_a)
medico_a = PhysicianProfile.objects.get(user=user_a)
medico_b = PhysicianProfile.objects.get(user=user_b)
original_medico = (medico_a.verification_status, medico_a.crm_number, medico_a.crm_state)
config = Configuracao.carregar()
original_config = (config.ativo, config.ambiente, config.cnpj_mantenedora)

pacientes, documentos = [], []


def limpar():
    for medico in (medico_a, medico_b):
        NumeroSncr.objects.filter(medico=medico).update(documento=None)
        NumeroSncr.objects.filter(medico=medico).delete()
        BlocoNumeracao.objects.filter(medico=medico).delete()
        PedidoNumeracao.objects.filter(medico=medico).delete()


def entrar(u=user_a):
    c = Client()
    c.force_login(u)
    s = c.session
    s['tenant_id'] = str(tenant_a.id)
    s.save()
    return c


chamadas = []


def numeros(prefixo, inicio, quantidade):
    return [f'{prefixo}.{n:07d}' for n in range(inicio, inicio + quantidade)]


def anvisa(post):
    """Um SNCR falso. `post` é (status, corpo) ou uma exceção do httpx."""
    def handler(req):
        chamadas.append(req)
        if req.url.path.endswith('/auth/token'):
            return httpx.Response(200, json={'access_token': 'TOKEN-NR-XYZ', 'token_type': 'Bearer'})
        if isinstance(post, Exception):
            raise post
        status, corpo = post
        if isinstance(corpo, str):
            return httpx.Response(status, text=corpo)
        return httpx.Response(status, json=corpo)
    return handler


def com_anvisa(handler):
    return mock.patch.object(
        fluxo, 'criar_cliente',
        lambda cfg: api.Cliente(cfg.base_url, fluxo._origem(), transport=httpx.MockTransport(handler)),
    )


def pedir(tipo, handler, quantidade=None, session_id='sess-nr'):
    """Clique em pedir e retorno do Gov.br. Devolve (pedido criado ou None, resposta do POST)."""
    antes = set(PedidoNumeracao.objects.filter(medico=medico_a).values_list('id', flat=True))
    c = entrar()
    dados = {} if quantidade is None else {'quantidade': quantidade}
    with com_anvisa(handler):
        r = c.post(f'/app/sncr/pedir/{tipo}/', dados)
        if r.status_code == 200 and b'data-nd-sncr-govbr' in r.content:
            c.get('/app/sncr/retorno/', {'session_id': session_id})
    novo = PedidoNumeracao.objects.filter(medico=medico_a).exclude(id__in=antes).first()
    return novo, r


def corpo_do_post():
    for req in reversed(chamadas):
        if req.url.path.endswith('notificacao-receita'):
            return json.loads(req.content)
    return None


def gastar(tipo, quantos):
    """Marca `quantos` números livres do médico como usados (como se assinados)."""
    ids = list(NumeroSncr.objects.filter(medico=medico_a, tipo=tipo, estado=EstadoNumero.LIVRE)
               .order_by('ordem').values_list('id', flat=True)[:quantos])
    NumeroSncr.objects.filter(id__in=ids).update(estado=EstadoNumero.CONSUMIDO)


def cpf_valido():
    while True:
        base = [secrets.randbelow(10) for _ in range(9)]
        for _ in range(2):
            soma = sum(d * p for d, p in zip(base, range(len(base) + 1, 1, -1)))
            base.append((soma * 10 % 11) % 10)
        texto = ''.join(map(str, base))
        if len(set(texto)) > 1 and not Patient.objects.filter(cpf=texto).exists():
            return texto


def paciente(**extra):
    dados = dict(
        full_name=f'PACIENTE ROTEIRO NOTIFICACAO {secrets.token_hex(3).upper()}', birth_date=date(1975, 3, 9),
        cpf=cpf_valido(), street='Rua dos Ipês', number='45', district='Vila Mariana',
        city='São Paulo', state='SP', postal_code='04101000', sex_at_registration='male',
    )
    dados.update(extra)
    p = Patient.objects.create(tenant=tenant_a, **dados)
    pacientes.append(p.id)
    return p


def itens(*lista, continuo=()):
    campos = {'prescription_text': '', 'special_instructions': ''}
    for n, (nome, conc, forma, qtd, poso) in enumerate(lista, start=1):
        campos.update({f'item{n}_nome': nome, f'item{n}_concentracao': conc, f'item{n}_forma': forma,
                       f'item{n}_quantidade': qtd, f'item{n}_posologia': poso})
        if n in continuo:
            campos[f'item{n}_uso_continuo'] = True
    return campos


def rascunho(paciente_, formato, campos, confirmada=False):
    conteudo = dict(campos, prescription_format=formato, classificacao_confirmada=confirmada)
    doc = issuance.create_draft(tenant_a, paciente_, None, vinculo_a, user_a.id, 'prescription', conteudo)
    documentos.append(doc.id)
    return doc


CLONAZEPAM = ('Clonazepam', '2 mg', 'comprimido', '30 comprimidos', '1 comprimido à noite')
RIVOTRIL = ('Rivotril', '0,5 mg', 'comprimido', '30 comprimidos', '1 comprimido à noite')
ZOLPIDEM = ('Zolpidem', '10 mg', 'comprimido revestido', '30 comprimidos', '1 comprimido ao deitar')
METILFENIDATO = ('Metilfenidato', '10 mg', 'comprimido', '60 comprimidos', '1 comprimido de manhã e 1 ao meio-dia')
SIBUTRAMINA = ('Sibutramina', '10 mg', 'cápsula', '30 cápsulas', '1 cápsula pela manhã')
SERTRALINA = ('Sertralina', '50 mg', 'comprimido revestido', '30 comprimidos', '1 comprimido pela manhã')
AMOXICILINA = ('Amoxicilina', '500 mg', 'cápsula', '21 cápsulas', '1 cápsula de 8 em 8 horas')
ISOTRETINOINA = ('Isotretinoína', '20 mg', 'cápsula', '30 cápsulas', '1 cápsula ao dia')
TALIDOMIDA = ('Talidomida', '100 mg', 'comprimido', '30 comprimidos', '1 comprimido à noite')
FENOBARBITAL = ('Fenobarbital', '100 mg', 'comprimido', '60 comprimidos', '1 comprimido à noite')
DESCONHECIDO = ('Xyzqwertona', '5 mg', 'comprimido', '30 comprimidos', '1 ao dia')


# --- certificado de teste e a sessão de assinatura simulada (como check_sncr_receita) ---
chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
nome_cert = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'DRA ANA NEURO:00000000191')])
agora = datetime.now(dt_timezone.utc)
certificado = (
    x509.CertificateBuilder().subject_name(nome_cert).issuer_name(nome_cert).public_key(chave.public_key())
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


def assinar(doc):
    guardado = {n: getattr(issuance, n) for n in SIMULADOS}
    for n, f in SIMULADOS.items():
        setattr(issuance, n, f)
    try:
        doc.status = MedicalDocumentStatus.READY_TO_SIGN
        doc.save(update_fields=['status'])
        return issuance.sign_and_issue(doc, None, vinculo_a)
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


def posicoes(dados, pagina=0):
    """{texto: (x, topo)} dos trechos da página — topo medido do alto, como o leiaute."""
    achados = {}

    def visitar(texto, cm, tm, fonte, tamanho):
        texto = (texto or '').strip()
        if texto and texto not in achados:
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            achados[texto] = (round(x, 1), round(pdf_oficial.TOPO - y, 1))

    PdfReader(io.BytesIO(dados)).pages[pagina].extract_text(visitor_text=visitar)
    return achados


def x_de(achados, comeco):
    for texto, (x, _topo) in achados.items():
        if texto.startswith(comeco):
            return x
    return None


try:
    limpar()
    medico_a.verification_status = medico_a.VerificationStatus.VERIFIED
    medico_a.crm_number, medico_a.crm_state = '123.456', 'SP'
    medico_a.save(update_fields=['verification_status', 'crm_number', 'crm_state'])
    # Sem CNPJ de propósito: a Notificação não o leva (Manual v5, §2.3.1.3).
    config.ativo, config.ambiente, config.cnpj_mantenedora = True, 'homologacao', ''
    config.save()

    print('=== 1. o que impede começar ===')
    conferir('sem CNPJ da mantenedora, a Notificação B pode ser pedida', fluxo.conferir(config, medico_a, 'NRB') == [],
             fluxo.conferir(config, medico_a, 'NRB'))
    conferir('e a RCE continua exigindo o CNPJ', any('CNPJ' in m for m in fluxo.conferir(config, medico_a, 'RCE')))
    painel = entrar().get('/app/sncr/').content.decode()
    conferir('o painel mostra os três tipos de Notificação',
             all(f'data-nd-sncr-tipo="{t}"' in painel for t in ('NRA', 'NRB', 'NRB2')))
    conferir('com a escolha do lote (10 marcado) e a explicação da cota da Vigilância',
             'data-nd-sncr-quantidade' in painel and '<option value="10" selected>' in painel
             and 'Vigilância Sanitária' in painel)
    conferir('a secretária não abre o painel', entrar(secretaria).get('/app/sncr/').status_code == 404)

    print('=== 2. o pedido que dá certo ===')
    chamadas.clear()
    lote1 = numeros('2611.2-35', 1, 10)
    pedido, r = pedir('NRB', anvisa((201, {'numeracoesReceita': lote1, 'saldoReceitas': 40,
                                          'mensagem': 'Saldo inferior a 50 receitas disponíveis'})))
    conferir('o POST responde com a página do Gov.br', r.status_code == 200 and b'data-nd-sncr-govbr' in r.content,
             r.status_code)
    conferir('pedido concluído', pedido is not None and pedido.estado == EstadoPedido.CONCLUIDO,
             pedido and (pedido.estado, pedido.mensagem))
    corpo = corpo_do_post()
    conferir('o corpo é o do manual: receita, conselho, UF, CRM só em dígitos e o lote padrão de 10',
             corpo == {'receita': 'NRB', 'conselho': 'CRM', 'uf': 'SP', 'documento': '123456', 'quantidade': 10}, corpo)
    conferir('sem CNPJ no corpo nem no pedido', corpo is not None and 'cnpj' not in corpo and pedido.cnpj == '')
    gravados = list(NumeroSncr.objects.filter(medico=medico_a, tipo='NRB').order_by('ordem').values_list('numero', flat=True))
    conferir('10 números, como vieram e na ordem', gravados == lote1, gravados[:2])
    lote = BlocoNumeracao.objects.get(pedido=pedido)
    conferir('o saldo da cota fica gravado e vai na mensagem', lote.saldo_visa == 40 and 'Restam 40' in pedido.mensagem,
             pedido.mensagem)
    conferir('a mensagem da Anvisa vai junto', 'Saldo inferior' in pedido.mensagem)
    conferir('com 10 livres não se pede outro lote',
             any('livres' in m for m in fluxo.conferir(config, medico_a, 'NRB')))
    gastar('NRB', 8)
    conferir('com 2 livres (menos que uma receita de 3 medicamentos), pode pedir',
             fluxo.conferir(config, medico_a, 'NRB') == [], fluxo.conferir(config, medico_a, 'NRB'))

    print('=== 3. o tamanho do lote e o limite do dia ===')
    for ruim in ('5', '60', 'abc', '0'):
        chamadas.clear()
        p_ruim, r = pedir('NRB', anvisa((201, {'numeracoesReceita': numeros('9', 1, 10)})), quantidade=ruim)
        conferir(f'lote "{ruim}": recusado sem criar pedido nem falar com a Anvisa',
                 p_ruim is None and not chamadas and r.status_code == 302, (p_ruim, len(chamadas)))
    chamadas.clear()
    p20, _ = pedir('NRB', anvisa((201, {'numeracoesReceita': numeros('2611.2-35', 11, 20), 'saldoReceitas': 20})),
                   quantidade='20')
    conferir('lote de 20: o corpo pede 20', corpo_do_post() and corpo_do_post()['quantidade'] == 20)
    conferir('e chegam 20 números', p20 and BlocoNumeracao.objects.get(pedido=p20).quantidade == 20)
    conferir('hoje: 30 recebidos', fluxo.recebidos_hoje(medico_a, 'NRB', 'homologacao') == 30)
    gastar('NRB', 21)
    chamadas.clear()
    p30, r = pedir('NRB', anvisa((201, {'numeracoesReceita': numeros('8', 1, 30)})), quantidade='30')
    conferir('30 a mais passariam de 50 no dia: recusado, dizendo quanto cabe',
             p30 is None and not chamadas, len(chamadas))
    p20b, _ = pedir('NRB', anvisa((201, {'numeracoesReceita': numeros('2611.2-35', 31, 20)})), quantidade='20')
    gastar('NRB', 20)
    conferir('50 no dia: o limite barra', any('por dia' in m for m in fluxo.conferir(config, medico_a, 'NRB')),
             fluxo.conferir(config, medico_a, 'NRB'))

    print('=== 4. a lista como texto (manual) e os outros tipos ===')
    conferir('lista como texto entre colchetes',
             api._lista_de_numeros('[2411.1-00.0000001, 2411.1-00.0000002]') == ['2411.1-00.0000001', '2411.1-00.0000002'])
    conferir('lista com aspas', api._lista_de_numeros('["2411.1-00.0000003"]') == ['2411.1-00.0000003'])
    conferir('item que não é número recusa a lista inteira', api._lista_de_numeros(['2411.1-00.0000001', 'ok; DROP']) is None)
    conferir('nem texto nem lista não se reconhece', api._lista_de_numeros({'a': 1}) is None)
    pa, _ = pedir('NRA', anvisa((201, {'numeracoesReceita': '[2611.1-35.0000001, 2611.1-35.0000002, '
                                                         '2611.1-35.0000003, 2611.1-35.0000004]', 'saldoReceitas': 6})))
    conferir('Notificação A com a lista em texto: 4 números', pa and pa.estado == EstadoPedido.CONCLUIDO
             and numeracao.saldo(medico_a, 'NRA', 'homologacao') == 4, pa and pa.mensagem)
    pb2, _ = pedir('NRB2', anvisa((201, {'numeracoesReceita': numeros('2611.3-35', 1, 10)})))
    conferir('Notificação B2: 10 números', pb2 and numeracao.saldo(medico_a, 'NRB2', 'homologacao') == 10)

    print('=== 5. os desfechos (NRB2, com os livres gastos) ===')
    gastar('NRB2', 10)
    casos = [
        ('sem cota (400)', (400, {'codigo': 'ERRO', 'mensagem': 'Prescritor não possui saldo disponível.'}),
         EstadoPedido.RECUSADO),
        ('lista vazia', (201, {'numeracoesReceita': [], 'saldoReceitas': 0}), EstadoPedido.RECUSADO),
        ('204', (204, ''), EstadoPedido.RECUSADO),
    ]
    for rotulo, resposta, esperado in casos:
        p_caso, _ = pedir('NRB2', anvisa(resposta))
        conferir(f'{rotulo} → {esperado}', p_caso and p_caso.estado == esperado, p_caso and (p_caso.estado, p_caso.mensagem))
    conferir('nenhum número nasceu das recusas', numeracao.saldo(medico_a, 'NRB2', 'homologacao') == 0)
    p_rep, _ = pedir('NRB2', anvisa((201, {'numeracoesReceita': ['2611.3-35.0000090', '2611.3-35.0000090']})))
    lote_rep = BlocoNumeracao.objects.filter(pedido=p_rep).first()
    conferir('número repetido na própria lista: lote gravado e não utilizável',
             lote_rep is not None and not lote_rep.utilizavel and numeracao.saldo(medico_a, 'NRB2', 'homologacao') == 0)
    p_sob, _ = pedir('NRB2', anvisa((201, {'numeracoesReceita': numeros('2611.3-35', 1, 10)})))
    lote_sob = BlocoNumeracao.objects.filter(pedido=p_sob).first()
    conferir('lote que repete números já registrados: não utilizável',
             lote_sob is not None and not lote_sob.utilizavel and numeracao.saldo(medico_a, 'NRB2', 'homologacao') == 0)

    for rotulo, resposta in (('500', (500, {'codigo': 'ERRO_INTERNO'})),
                             ('tempo esgotado depois de enviar', httpx.ReadTimeout('lento')),
                             ('lista irreconhecível', (201, {'numeracoesReceita': 'nada disso'}))):
        PedidoNumeracao.objects.filter(medico=medico_a, tipo='NRB2', estado=EstadoPedido.INCERTO).update(
            estado=EstadoPedido.PERDIDO)
        p_inc, _ = pedir('NRB2', anvisa(resposta))
        conferir(f'{rotulo} → incerto, com o texto da Notificação',
                 p_inc and p_inc.estado == EstadoPedido.INCERTO and 'perdidos' in p_inc.mensagem,
                 p_inc and (p_inc.estado, p_inc.mensagem))
    conferir('o incerto barra pedido novo', any('perdidos' in m for m in fluxo.conferir(config, medico_a, 'NRB2')))
    chamadas.clear()
    p_barrado, _ = pedir('NRB2', anvisa((201, {'numeracoesReceita': numeros('7', 1, 10)})))
    conferir('com incerto pendente, o clique não pede nada', p_barrado is None and not chamadas)

    incerto = PedidoNumeracao.objects.get(medico=medico_a, tipo='NRB2', estado=EstadoPedido.INCERTO)
    url = f'/app/sncr/pedido/{incerto.id}/conferir/'
    entrar().post(url, {'resultado': 'gerado', 'inicio': '2611.3-35.0000001', 'fim': '2611.3-35.0001000'})
    incerto.refresh_from_db()
    conferir('o incerto da Notificação não se "confere" como o bloco', incerto.estado == EstadoPedido.INCERTO)
    entrar(user_b).post(url, {'resultado': 'perdido'})
    incerto.refresh_from_db()
    conferir('outro médico não dá por perdido o pedido da colega', incerto.estado == EstadoPedido.INCERTO)
    r = entrar(secretaria).post(url, {'resultado': 'perdido'})
    incerto.refresh_from_db()
    conferir('a secretária não chega lá', r.status_code == 404 and incerto.estado == EstadoPedido.INCERTO, r.status_code)
    entrar().post(url, {'resultado': 'perdido'})
    incerto.refresh_from_db()
    conferir('o próprio médico dá por perdido', incerto.estado == EstadoPedido.PERDIDO, incerto.estado)
    conferir('e libera pedido novo', not any('perdidos' in m for m in fluxo.conferir(config, medico_a, 'NRB2')))
    conferir('na trilha, em nome do médico', AuditEvent.objects.filter(
        object_id=incerto.id, action='sncr.pedido_perdido', actor_id=user_a.id).exists())
    painel = entrar().get('/app/sncr/').content.decode()
    PedidoNumeracao.objects.create(
        medico=medico_a, solicitado_por=user_a, tenant=tenant_a, tipo='NRA', ambiente='homologacao',
        uf='SP', documento='123456', estado=EstadoPedido.INCERTO, quantidade=10,
    )
    painel = entrar().get('/app/sncr/').content.decode()
    conferir('o painel oferece "dar por perdidos" ao incerto da Notificação', 'data-nd-sncr-perdido' in painel)
    PedidoNumeracao.objects.filter(medico=medico_a, tipo='NRA', estado=EstadoPedido.INCERTO).update(
        estado=EstadoPedido.PERDIDO)
    parado = PedidoNumeracao.objects.create(
        medico=medico_a, solicitado_por=user_a, tenant=tenant_a, tipo='NRB', ambiente='homologacao',
        uf='SP', documento='123456', estado=EstadoPedido.ENVIANDO, quantidade=10,
        enviado_em=timezone.now() - timedelta(minutes=10),
    )
    fluxo.pedidos_parados()
    parado.refresh_from_db()
    conferir('pedido de Notificação parado em "enviando" vira incerto, com o texto dela',
             parado.estado == EstadoPedido.INCERTO and 'perdidos' in parado.mensagem, parado.mensagem)
    conferir('o token nunca vai para a trilha', not any(
        'TOKEN-NR' in json.dumps(e.integrity_metadata or {})
        for e in AuditEvent.objects.filter(action__startswith='sncr.')))

    print('=== 6. a regra da Notificação ===')
    config.ambiente = 'producao'
    config.save()
    p = paciente()
    formatos = dict(MedicalDocumentForm().fields['prescription_format'].choices)
    conferir('o formulário oferece as três Notificações',
             all(f in formatos for f in (receita.SNCR_NRA, receita.SNCR_NRB, receita.SNCR_NRB2)))
    for formato, item, rotulo in ((receita.SNCR_NRB, CLONAZEPAM, 'clonazepam na B'),
                                  (receita.SNCR_NRB, RIVOTRIL, 'Rivotril (marca, pela CMED) na B'),
                                  (receita.SNCR_NRB, ZOLPIDEM, 'zolpidem na B'),
                                  (receita.SNCR_NRA, METILFENIDATO, 'metilfenidato na A'),
                                  (receita.SNCR_NRB2, SIBUTRAMINA, 'sibutramina na B2'),
                                  (receita.SNCR_NRB, FENOBARBITAL, 'fenobarbital (adendo da B1) na B')):
        erro = recusa(rascunho, p, formato, itens(item))
        conferir(f'{rotulo}: passa', erro is None, erro)
    for formato, item, esperado, rotulo in (
        (receita.SNCR_NRA, CLONAZEPAM, 'Notificação de Receita B', 'clonazepam na A'),
        (receita.SNCR_NRB, METILFENIDATO, 'Notificação de Receita A', 'metilfenidato na B'),
        (receita.SNCR_NRB, SIBUTRAMINA, 'Notificação de Receita B2', 'sibutramina na B'),
        (receita.SNCR_NRB, SERTRALINA, 'Receita de Controle Especial', 'sertralina (C1) na B'),
        (receita.SNCR_NRB, AMOXICILINA, 'confirmação', 'amoxicilina (fora da Portaria 344) na B'),
        (receita.SNCR_NRB, ISOTRETINOINA, 'talonário', 'isotretinoína (C2)'),
        (receita.SNCR_NRB, TALIDOMIDA, 'talonário', 'talidomida'),
    ):
        erro = recusa(rascunho, p, formato, itens(item))
        conferir(f'{rotulo}: recusado, apontando "{esperado}"', erro and esperado in erro, erro)
    erro = recusa(rascunho, p, receita.SNCR_NRB, itens(CLONAZEPAM, SERTRALINA))
    conferir('um documento, um tipo: clonazepam com sertralina é recusado no segundo',
             erro and 'Medicamento 2' in erro, erro)
    erro = recusa(rascunho, p, receita.SNCR_NRB, itens(DESCONHECIDO))
    conferir('nome que a lista não acha: recusado sem a confirmação', erro and 'confirmação' in erro, erro)
    doc = rascunho(p, receita.SNCR_NRB, itens(DESCONHECIDO), confirmada=True)
    conferir('e aceito com ela, gravada', doc.content_snapshot['classificacao_confirmada'] is True)
    erro = recusa(rascunho, p, receita.SNCR_RCE, itens(CLONAZEPAM))
    conferir('a RCE recusa o clonazepam apontando a Notificação B',
             erro and 'Notificação de Receita B' in erro and 'B1' in erro, erro)
    erro = recusa(rascunho, paciente(street='', city='', state=''), receita.SNCR_NRB, itens(CLONAZEPAM))
    conferir('sem endereço do paciente: recusado', erro and 'endereço' in erro, erro)
    erro = recusa(rascunho, paciente(cpf=None), receita.SNCR_NRB, itens(CLONAZEPAM))
    conferir('sem CPF: recusado', erro and 'CPF' in erro, erro)
    doc = rascunho(p, receita.SNCR_NRB, itens(CLONAZEPAM, continuo=(1,)))
    conferir('uso contínuo sai junto da quantidade, com o número por extenso',
             doc.content_snapshot['itens'][0]['quantidade'] == '30 (trinta) comprimidos — uso contínuo',
             doc.content_snapshot['itens'][0]['quantidade'])
    erro = recusa(rascunho, p, receita.SNCR_NRB, dict(itens(CLONAZEPAM, ZOLPIDEM, CLONAZEPAM),
                  item4_nome='Diazepam', item4_concentracao='5 mg', item4_forma='comprimido',
                  item4_quantidade='30 comprimidos', item4_posologia='1 à noite'))
    conferir('o quarto medicamento é recusado', erro and 'No máximo 3' in erro, erro)

    print('=== 7. o PDF do rascunho ===')
    nrb = rascunho(p, receita.SNCR_NRB, itens(CLONAZEPAM, ZOLPIDEM))
    pdf = read_bytes(nrb.pdf_attachment)
    texto = texto_do_pdf(pdf)
    leitor = PdfReader(io.BytesIO(pdf))
    conferir('o título do modelo da Notificação', 'NOTIFICAÇÃO DE RECEITA' in texto and 'CONTROLE ESPECIAL' not in texto)
    conferir('uma folha por medicamento, na página do modelo',
             len(leitor.pages) == 2 and {tuple(round(float(v), 1) for v in pg.mediabox) for pg in leitor.pages}
             == {(0.0, 7.8, 595.5, 850.1)})
    folhas = [pg.extract_text() or '' for pg in leitor.pages]
    conferir('cada folha com o seu medicamento e o paciente',
             'Clonazepam' in folhas[0] and 'Zolpidem' not in folhas[0] and 'Zolpidem' in folhas[1]
             and all(p.full_name in f for f in folhas))
    conferir('rascunho marcado e sem número', all('RASCUNHO' in f and 'atribuído pelo SNCR' in f for f in folhas))
    nomes_da_clinica = [n for n in (tenant_a.legal_name, getattr(tenant_a, 'trade_name', '')) if n]
    conferir('nenhum timbre da clínica', not any(n in texto for n in nomes_da_clinica))
    pos = posicoes(pdf)
    x_nome = x_de(pos, 'Clonazepam')
    leiaute = pdf_oficial.LEIAUTES_NOTIFICACAO['NRB']
    conferir('o medicamento escrito depois do rótulo da Notificação (e não na posição da RCE)',
             x_nome is not None and abs(x_nome - (leiaute.rotulos['nome'][1] + 5)) < 1, x_nome)
    x_paciente = x_de(pos, p.full_name)
    conferir('o paciente dentro do quadro da Notificação',
             x_paciente is not None and abs(x_paciente - leiaute.paciente_x) < 1, x_paciente)
    rce = rascunho(p, receita.SNCR_RCE, itens(SERTRALINA))
    x_rce = x_de(posicoes(read_bytes(rce.pdf_attachment)), 'Sertralina')
    conferir('a RCE continua com as posições dela',
             x_rce is not None and abs(x_rce - (pdf_oficial.ROTULOS_PRESCRICAO_RCE['nome'][1] + 5)) < 1, x_rce)
    for formato, rotulo in ((receita.SNCR_NRA, 'A'), (receita.SNCR_NRB2, 'B2')):
        item = METILFENIDATO if rotulo == 'A' else SIBUTRAMINA
        d = rascunho(p, formato, itens(item))
        guardar(f'nr{rotulo.lower()}_rascunho', read_bytes(d.pdf_attachment))
        t = texto_do_pdf(read_bytes(d.pdf_attachment))
        conferir(f'a Notificação {rotulo} sai no modelo dela', 'NOTIFICAÇÃO DE RECEITA' in t and item[0] in t)
    erro = recusa(issuance.issue_on_paper, nrb, user_a.id)
    conferir('a Notificação eletrônica não é emitida em papel', erro and 'talonário' in erro, erro)
    erro = recusa(issuance.converter_para_impressa, nrb, user_a.id)
    conferir('nem refeita como impressa (o papel é o talonário)', erro and 'talonário' in erro, erro)
    conferir('e o rascunho continua lá', MedicalDocument.objects.filter(id=nrb.id).exists())

    print('=== 8. a assinatura, os números e o QR ===')
    limpar()
    erro = None
    try:
        assinar(nrb)
    except Exception as exc:  # noqa: BLE001 — a recusa é o que se testa
        erro = str(exc)
    nrb.refresh_from_db()
    conferir('sem número livre: recusado, falando do lote e da Vigilância',
             erro and 'lote' in erro and 'Vigilância' in erro, erro)
    conferir('e o documento continua pronto para assinar', nrb.status == MedicalDocumentStatus.READY_TO_SIGN)
    pedido_lote = PedidoNumeracao.objects.create(
        medico=medico_a, solicitado_por=user_a, tenant=tenant_a, tipo='NRB', ambiente='producao',
        uf='SP', documento='123456', estado=EstadoPedido.CONCLUIDO, quantidade=10,
    )
    lote_real = numeros('2611.2-35', 501, 10)
    numeracao.registrar_lote(pedido_lote, {'numeros': lote_real, 'saldo': 0})
    destinos = []
    original_widget = pdf_oficial.qr.QrCodeWidget

    def espiao(valor, *a, **k):
        destinos.append(valor)
        return original_widget(valor, *a, **k)

    with mock.patch.object(pdf_oficial.qr, 'QrCodeWidget', espiao):
        emitido = assinar(nrb)
    emitido.refresh_from_db()
    usados = list(NumeroSncr.objects.filter(documento=emitido).order_by('ordem'))
    conferir('emitida', emitido.status == MedicalDocumentStatus.ISSUED)
    conferir('dois medicamentos, os dois primeiros números do lote, consumidos',
             [n.numero for n in usados] == lote_real[:2] and all(n.estado == EstadoNumero.CONSUMIDO for n in usados),
             [n.numero for n in usados])
    conferir('nos metadados, na ordem das folhas, com o tipo',
             emitido.signature_metadata.get('sncr', {}).get('numeros') == lote_real[:2]
             and emitido.signature_metadata['sncr'].get('tipo') == 'NRB')
    conferir('o QR de cada folha abre a consulta do número dela no SNCR',
             destinos == [pdf_oficial.CONSULTA_SNCR + n for n in lote_real[:2]], destinos)
    assinado = read_bytes(emitido.signed_pdf_attachment)
    guardar('nrb_assinada', assinado)
    folhas = [pg.extract_text() or '' for pg in PdfReader(io.BytesIO(assinado)).pages]
    conferir('cada número na folha do seu medicamento',
             lote_real[0] in folhas[0] and lote_real[1] not in folhas[0] and lote_real[1] in folhas[1])
    conferir('a verificação do NeuroDoc no rodapé de cada folha',
             all(f'/verificar/{emitido.validation_token}/' in f for f in folhas))
    pos_assinado = posicoes(assinado)
    x_numero = x_de(pos_assinado, lote_real[0])
    conferir('o número dentro da caixa "N.º" do modelo', x_numero is not None and abs(x_numero - leiaute.numero_x) < 1,
             x_numero)
    validacao = validate_signed_pdf(assinado, a1x509.Certificate.load(certificado.public_bytes(serialization.Encoding.DER)))
    conferir('a assinatura PAdES é íntegra e válida', validacao.intact and validacao.valid)
    erro = recusa(issuance.create_correction, emitido, user_a.id, {})
    conferir('a Notificação emitida não é retificada', erro and 'não é retificada' in erro, erro)

    config.ambiente = 'homologacao'
    config.save()
    pedido_h = PedidoNumeracao.objects.create(
        medico=medico_a, solicitado_por=user_a, tenant=tenant_a, tipo='NRA', ambiente='homologacao',
        uf='SP', documento='123456', estado=EstadoPedido.CONCLUIDO, quantidade=10,
    )
    numeracao.registrar_lote(pedido_h, {'numeros': numeros('2611.1-00', 1, 10), 'saldo': None})
    destinos.clear()
    with mock.patch.object(pdf_oficial.qr, 'QrCodeWidget', espiao):
        treino = assinar(rascunho(paciente(), receita.SNCR_NRA, itens(METILFENIDATO)))
    guardar('nra_homologacao', read_bytes(treino.signed_pdf_attachment))
    texto = texto_do_pdf(read_bytes(treino.signed_pdf_attachment))
    conferir('homologação: tarja sem validade e o QR do portal de treinamento',
             'HOMOLOGAÇÃO' in texto and destinos == [pdf_oficial.CONSULTA_SNCR_TREINAMENTO + '2611.1-00.0000001'], destinos)
    config.ambiente = 'producao'
    config.save()

    print('=== 9. as telas ===')
    c = entrar()
    detalhe = c.get(f'/app/documents/medical/{emitido.id}/').content.decode()
    conferir('o detalhe mostra o tipo, os números e a validade de 30 dias',
             'Notificação de Receita B' in detalhe and lote_real[0] in detalhe
             and 'data-nd-notificacao-validade' in detalhe and '30 dias' in detalhe)
    novo_rascunho = rascunho(p, receita.SNCR_NRB, itens(ZOLPIDEM))
    tela = c.get(f'/app/documents/medical/{novo_rascunho.id}/').content.decode()
    conferir('o rascunho da Notificação não oferece "Refazer como impressa", e aponta o talonário',
             'Refazer como receita impressa' not in tela and 'data-nd-notificacao-papel' in tela)
    tela_rce = c.get(f'/app/documents/medical/{rce.id}/').content.decode()
    conferir('o da RCE continua oferecendo', 'Refazer como receita impressa' in tela_rce)
    formulario = c.get(f'/app/documents/patients/{p.id}/medical/new/').content.decode()
    conferir('o formulário traz o aviso dos limites da Notificação e os saldos dela',
             'data-nd-rx-notificacao' in formulario and 'Notificação B' in formulario
             and 'value="sncr_nrb"' in formulario)
finally:
    print('=== limpeza ===')
    limpar()
    for d in MedicalDocument.objects.filter(id__in=documentos):
        anexos = [a for a in (d.pdf_attachment_id, d.signed_pdf_attachment_id) if a]
        d.delete()
        Attachment.objects.filter(id__in=anexos).delete()
    Patient.objects.filter(id__in=pacientes).delete()
    medico_a.verification_status, medico_a.crm_number, medico_a.crm_state = original_medico
    medico_a.save(update_fields=['verification_status', 'crm_number', 'crm_state'])
    config.ativo, config.ambiente, config.cnpj_mantenedora = original_config
    config.save()
    print('  rascunhos, notificações, lotes, números e pacientes do roteiro removidos; configuração restaurada')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: Notificação de Receita A, B e B2 — o lote da cota da Vigilância, os desfechos, a regra de cada')
print('    tipo, o modelo oficial nas posições dele, um número por folha e o QR da consulta no SNCR.')
