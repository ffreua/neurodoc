"""Lotes TISS e o arquivo XML: o que vai à operadora (Sprint 3).

Tenta quebrar:

- **XML por versão**: Consulta e SP/SADT nas sete versões (3.04.00 a
  4.03.00) passam no XSD oficial **daquela** versão; o nome do beneficiário
  só nas 3.x; o regime de atendimento só nas 4.x; CNPJ com letra passa na
  4.03.00 e é recusado pelo XSD da 4.02.00; valor que estoura o 8,2 da
  4.01.00 é recusado antes de escrever;
- **casos negativos**: o anexo que originou o módulo, namespace trocado,
  campo obrigatório apagado, DOCTYPE (XXE) — todos recusados;
- **hash do epílogo**: MD5 do conteúdo em ISO-8859-1 (acento conta como
  um byte), recalculado do arquivo e igual ao gravado; um caractere
  trocado muda o hash;
- **lote**: o plano separa tipo, operadora e versão; 101 guias viram 100+1,
  e 30+30+30+11 com o limite da operadora; guia histórica sem aceite,
  guia em rascunho, guia já em lote e guia fechada em versão antiga ficam
  de fora **com o motivo**; seleção que mudou entre ver e confirmar não
  cria nada; o banco recusa a guia em dois lotes ativos e o lote de 101;
- **arquivo**: gerado no worker, 0600, SHA-256 conferido, os mesmos bytes
  ao gerar de novo e ao baixar de novo, hora local (23h30) na transação;
  falha registrada (chave desligada, quem pediu sem vínculo, guia
  substituída) e repetida com o mesmo número;
- **nada vira pagamento**: gerar, enviar e registrar retorno não criam
  pagamento nem cobrança;
- **transições**: envio antes do arquivo, data futura, retorno sem envio,
  recusa sem motivo, cancelar enviado não recusado, reapresentação com
  motivo, guia em lote ativo não se cancela;
- **ciclo**: 15 a 14 na virada do ano, fevereiro bissexto, mês de 30 dias;
- **telas**: fila, plano, lote e download; GET não muda nada; outra
  clínica em 404; plano sem TISS em 404; a página do lote sem indicação
  clínica;
- **concorrência de verdade**: duas conexões confirmando o mesmo plano ao
  mesmo tempo — um lote, não dois.

Quase tudo numa transação desfeita; a seção de concorrência grava e
apaga o que criou.

    docker compose exec -T app python manage.py shell < checks/check_tiss_lotes.py
"""
import copy
import hashlib
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings as dj_settings
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from lxml import etree

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.mfa import RECENT_MFA_SESSION_KEY
from catalogs.models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode
from finance.models import FeeSchedule, Payment, PaymentCategory, Receivable
from patients.models import HealthPlan, Insurer, Patient, PatientCoverage
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.plans import PlanCode
from tiss import guias, lotes, versoes
from tiss import xml as txml
from tiss.models import (
    CicloFechamento, Configuracao, Credenciamento, EstadoGuia, EstadoLote, Guia, Lote, LoteGuia,
    Prestador, ProfissionalTiss, TipoGuia,
)

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


clinica = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=clinica.id).order_by('created_at').first()
vinculos = list(Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE).select_related('user'))
secretaria = next((m for m in vinculos if Role.SECRETARY in (m.roles or [])
                   and not {Role.OWNER, Role.MANAGER, Role.DOCTOR} & set(m.roles or [])), None)
medico = next((m for m in vinculos if Role.DOCTOR in (m.roles or []) and m.can_practice_clinically()), None)
paciente = Patient.objects.filter(tenant=clinica).order_by('created_at').first()
if None in (secretaria, medico, paciente, outra):
    print('  (demonstração incompleta; roteiro pulado)')
    raise SystemExit(0)

# A geração vai para o worker; aqui ela é chamada à mão, e o que seria
# enfileirado é anotado para conferir.
enfileirados = []
lotes._enfileirar = lambda lote_id: enfileirados.append(str(lote_id))


def contexto(quem, tenant=clinica):
    from tenancy.permissions import capabilities_for
    return AccessContext(
        user_id=quem.user_id, tenant_id=tenant.id, membership_id=quem.id,
        permissions=frozenset(quem.roles), request_id=uuid.uuid4(),
        capabilities=capabilities_for(quem.roles, clinically_enabled=quem.can_practice_clinically(),
                                      ai_contracted=False, tiss_contracted=True),
    )


def cliente(quem, tenant=clinica):
    c = Client(SERVER_NAME='localhost')
    c.force_login(quem.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s[RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
    s.save()
    return c


def recusa(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except (lotes.LoteRecusado, guias.GuiaRecusada) as exc:
        return str(exc)


ctx_sec = contexto(secretaria)
hoje = timezone.localdate()
seq = iter(range(900001, 990000))


def preparar_base():
    """Flags, catálogo e cadastros. Devolve um dicionário com o que criou."""
    Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
    Configuracao.objects.filter(id=Configuracao.carregar().id).update(ativo=True)
    CatalogRelease.objects.filter(system=CatalogSystem.TUSS).update(status=CatalogReleaseStatus.SUPERSEDED)
    rel = CatalogRelease.objects.create(system=CatalogSystem.TUSS, version=f'ANS-roteiro-lotes-{uuid.uuid4().hex[:6]}',
                                        status=CatalogReleaseStatus.ACTIVE, imported_at=timezone.now())
    ProcedureCode.objects.create(release=rel, code='10101012', description='CONSULTA EM CONSULTORIO',
                                 starts_on=date(2010, 1, 1), active=True)
    enmg = ProcedureCode.objects.create(release=rel, code='40103323', description='ELETRONEUROMIOGRAFIA DE MMSS',
                                        starts_on=date(2010, 1, 1), active=True)
    op_a = Insurer.objects.create(tenant=clinica, name='OPERADORA ROTEIRO LOTES A', ans_registration='368253')
    op_b = Insurer.objects.create(tenant=clinica, name='OPERADORA ROTEIRO LOTES B', ans_registration='303976')
    plano = HealthPlan.objects.create(tenant=clinica, insurer=op_a, name='PLANO ROTEIRO LOTES')
    cobertura = PatientCoverage.objects.create(tenant=clinica, patient=paciente, plan=plano,
                                               member_number='0182D000430005', starts_on=date(2020, 1, 1))
    prestador = Prestador.objects.create(tenant=clinica, nome='CLÍNICA ROTEIRO LOTES LTDA',
                                         cnpj='69887146000105', cnes='9876543')
    cred_a = Credenciamento.objects.create(tenant=clinica, prestador=prestador, operadora=op_a,
                                           codigo_na_operadora='00012345', versao='4.03.00')
    cred_b = Credenciamento.objects.create(tenant=clinica, prestador=prestador, operadora=op_b,
                                           codigo_na_operadora='77', versao='4.00.00')
    prof = ProfissionalTiss.objects.create(tenant=clinica, nome='DR ROTEIRO LOTES', numero_conselho='11788',
                                           uf='PA', cbo='225112', cpf='52998224725', membership=medico)
    for proc in (enmg,):
        FeeSchedule.objects.create(
            tenant=clinica, physician=None, plan=plano, procedure=proc, appointment_type=None,
            payment_category=PaymentCategory.INSURANCE, gross_amount=Decimal('310.93'),
            doctor_share_amount=Decimal('0'), effective_from=hoje - timedelta(days=400),
        )
    return {'op_a': op_a, 'op_b': op_b, 'cobertura': cobertura, 'prestador': prestador,
            'cred_a': cred_a, 'cred_b': cred_b, 'prof': prof}


def guia_sadt_real(base, dia=None):
    """Uma SP/SADT pelos serviços de verdade, fechada."""
    dia = dia or hoje
    g = guias.criar_guia(ctx_sec, secretaria.user, paciente, TipoGuia.SP_SADT)
    # O paciente da demonstração pode ter outro convênio na ficha: o do
    # roteiro é posto à mão, como a recepção faria na tela.
    Guia.objects.filter(id=g.id).update(
        cobertura=base['cobertura'], credenciamento=base['cred_a'], carteira='0182D000430005',
        tipo_atendimento='23', solicitante=base['prof'], executante=base['prof'],
        indicacao_clinica='Parestesia em mãos — investigar túnel do carpo',
        data_autorizacao=dia, senha='AO6426648',
    )
    g.refresh_from_db()
    guias.gravar_item(ctx_sec, secretaria.user, g, {'data_execucao': dia, 'codigo': '40103323', 'tabela': '22',
                                                     'hora_inicial': None, 'hora_final': None})
    return guias.fechar(ctx_sec, secretaria.user, g)


def copia_fechada(modelo, cred, versao=None, estado=EstadoGuia.FECHADA, salvar=True):
    """Guia fechada com o snapshot de uma guia real — para volume."""
    numero = str(next(seq))
    snap = copy.deepcopy(modelo.snapshot)
    snap['guia']['numero_prestador'] = numero
    snap['versao'] = versao or cred.versao
    snap['operadora']['registro_ans'] = cred.operadora.ans_registration
    g = Guia(tenant=clinica, tipo=modelo.tipo, estado=estado, paciente=paciente, cobertura=modelo.cobertura,
             credenciamento=cred, numero_prestador=numero, data_emissao=hoje, versao=versao or cred.versao,
             snapshot=snap, fechada_em=timezone.now() if estado == EstadoGuia.FECHADA else None,
             data_referencia=modelo.data_referencia, carteira=modelo.carteira)
    if salvar:
        g.save()
    return g


pasta_tiss = Path(dj_settings.MEDIA_ROOT) / str(clinica.id) / 'tiss'
arquivos_antes = set(pasta_tiss.glob('*')) if pasta_tiss.exists() else set()

try:
    with transaction.atomic():
        base = preparar_base()
        pagamentos_antes = Payment.objects.filter(receivable__tenant=clinica).count()
        recebiveis_antes = Receivable.objects.filter(tenant=clinica).count()

        print('=== 1. Guias de verdade, fechadas com o snapshot completo ===')
        sadt = guia_sadt_real(base)
        conferir('o snapshot leva os campos da guia', sadt.snapshot.get('guia', {}).get('senha') == 'AO6426648')
        conferir('data de referência = último procedimento', sadt.data_referencia == hoje)
        consulta = guias.criar_guia(ctx_sec, secretaria.user, paciente, TipoGuia.CONSULTA)
        Guia.objects.filter(id=consulta.id).update(
            tipo_consulta='1', executante=base['prof'], cobertura=base['cobertura'],
            credenciamento=base['cred_a'], carteira='0182D000430005')
        consulta.refresh_from_db()
        guias.gravar_item(ctx_sec, secretaria.user, consulta, {
            'data_execucao': hoje, 'codigo': '10101012', 'tabela': '22', 'valor_unitario': '150.00',
            'preco_motivo': 'contrato sem tabela no roteiro'})
        consulta = guias.fechar(ctx_sec, secretaria.user, consulta)
        conferir('consulta fechada', consulta.estado == EstadoGuia.FECHADA)

        print('=== 2. XML em cada versão, contra o XSD daquela versão ===')
        exame = {'3.04.00': '05', '3.05.00': '05', '4.00.00': '05', '4.00.01': '05'}
        for v in versoes.VERSOES:
            for modelo in (sadt, consulta):
                snap = copy.deepcopy(modelo.snapshot)
                snap['versao'] = v
                if modelo.tipo == TipoGuia.SP_SADT:
                    snap['guia']['tipo_atendimento'] = exame.get(v, '23')
                dados, _ = txml.mensagem_lote(
                    versao=v, tipo=modelo.tipo, numero_lote='1', transacao_em=datetime(2026, 10, 30, 9, 0),
                    prestador_id=('codigo', '00012345'), registro_ans='368253', snapshots=[snap])
                erros = versoes.validar(v, dados)
                conferir(f'{v} {modelo.get_tipo_display()}: passa no XSD', not erros, erros[:3])
                tem_nome = b'nomeBeneficiario' in dados
                conferir(f'{v} {modelo.get_tipo_display()}: nome do beneficiário só na 3.x',
                         tem_nome == v.startswith('3'))
                conferir(f'{v} {modelo.get_tipo_display()}: regime de atendimento só na 4.x',
                         (b'regimeAtendimento' in dados) == v.startswith('4'))

        snap_cnpj = copy.deepcopy(sadt.snapshot)
        snap_cnpj['credenciamento'] = {'identificacao': 'cnpj', 'codigo': ''}
        snap_cnpj['prestador']['documento'] = '12ABC34501DE35'
        for v, deve in (('4.03.00', True), ('4.02.00', False)):
            s = copy.deepcopy(snap_cnpj)
            s['versao'] = v
            dados, _ = txml.mensagem_lote(versao=v, tipo='sp_sadt', numero_lote='1', transacao_em=datetime(2026, 10, 30, 9, 0),
                                          prestador_id=('cnpj', '12ABC34501DE35'), registro_ans='368253', snapshots=[s])
            conferir(f'CNPJ com letra {"aceito" if deve else "recusado"} pelo XSD da {v}',
                     (not versoes.validar(v, dados)) == deve)
        caro = copy.deepcopy(sadt.snapshot)
        caro['versao'] = '4.01.00'
        caro['itens'][0]['valor_unitario'] = caro['itens'][0]['valor_total'] = '1234567.89'
        try:
            txml.mensagem_lote(versao='4.01.00', tipo='sp_sadt', numero_lote='1', transacao_em=datetime(2026, 10, 30),
                               prestador_id=('codigo', '1'), registro_ans='368253', snapshots=[caro])
            conferir('valor acima do 8,2 da 4.01.00 recusado antes de escrever', False)
        except txml.XmlInvalido as exc:
            conferir('valor acima do 8,2 da 4.01.00 recusado antes de escrever', '4.01.00' in str(exc))
        caro['versao'] = '4.02.00'
        dados, _ = txml.mensagem_lote(versao='4.02.00', tipo='sp_sadt', numero_lote='1', transacao_em=datetime(2026, 10, 30),
                                      prestador_id=('codigo', '1'), registro_ans='368253', snapshots=[caro])
        conferir('o mesmo valor cabe no 10,2 da 4.02.00', not versoes.validar('4.02.00', dados))
        misturada = copy.deepcopy(sadt.snapshot)
        try:
            txml.mensagem_lote(versao='4.00.00', tipo='sp_sadt', numero_lote='1', transacao_em=datetime(2026, 10, 30),
                               prestador_id=('codigo', '1'), registro_ans='368253', snapshots=[misturada])
            conferir('guia fechada em 4.03.00 não entra em mensagem 4.00.00', False)
        except txml.XmlInvalido:
            conferir('guia fechada em 4.03.00 não entra em mensagem 4.00.00', True)

        print('=== 3. Casos negativos ===')
        dados, valor_hash = txml.mensagem_lote(
            versao='4.03.00', tipo='sp_sadt', numero_lote='1', transacao_em=datetime(2026, 10, 30, 9, 0),
            prestador_id=('codigo', '00012345'), registro_ans='368253', snapshots=[sadt.snapshot])
        anexo = Path(dj_settings.BASE_DIR, 'tiss', 'exemplos', 'anexo_reprovado_4_01_00.xml').read_bytes()
        conferir('o anexo que originou o módulo é reprovado', bool(versoes.validar('4.01.00', anexo)))
        trocado = dados.replace(versoes.NAMESPACE.encode(), b'http://www.ans.gov.br/padraotiss/schemas')
        conferir('namespace trocado é reprovado', bool(versoes.validar('4.03.00', trocado)))
        sem_carteira = dados.replace(b'<ans:numeroCarteira>0182D000430005</ans:numeroCarteira>', b'')
        conferir('sem a carteira, reprovado', sem_carteira != dados and bool(versoes.validar('4.03.00', sem_carteira)))
        xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>' + dados.split(b'?>', 1)[1]
        try:
            versoes.validar('4.03.00', xxe)
            conferir('DOCTYPE com entidade externa recusado', False)
        except versoes.XmlRecusado:
            conferir('DOCTYPE com entidade externa recusado', True)

        print('=== 4. O hash do epílogo ===')
        conferir('declaração com aspas duplas e ISO-8859-1', dados.startswith(b'<?xml version="1.0" encoding="ISO-8859-1"?>'))
        conferir('acento em um byte (ISO-8859-1)', 'CLÍNICA'.encode('latin-1') in dados and 'CLÍNICA'.encode() not in dados)
        conferir('travessão vira hífen', 'mãos - investigar'.encode('latin-1') in dados)
        arvore = etree.fromstring(dados)
        conferir('recalculado do arquivo = o do epílogo', txml.hash_tiss(arvore) == valor_hash
                 and arvore.findtext(f'.//{{{versoes.NAMESPACE}}}hash') == valor_hash)
        raiz = etree.Element(f'{{{versoes.NAMESPACE}}}m')
        etree.SubElement(raiz, f'{{{versoes.NAMESPACE}}}a').text = 'Ação'
        etree.SubElement(raiz, f'{{{versoes.NAMESPACE}}}b').text = '12'
        ep = etree.SubElement(raiz, f'{{{versoes.NAMESPACE}}}epilogo')
        etree.SubElement(ep, f'{{{versoes.NAMESPACE}}}hash').text = 'qualquer'
        conferir('vetor: MD5("Ação12") em ISO-8859-1, sem o epílogo, minúsculas',
                 txml.hash_tiss(raiz) == hashlib.md5('Ação12'.encode('latin-1')).hexdigest())
        adulterado = etree.fromstring(dados.replace(b'0182D000430005', b'0182D000430006'))
        conferir('um caractere trocado muda o hash', txml.hash_tiss(adulterado) != valor_hash)

        print('=== 5. O plano: separa, divide e diz o que fica de fora ===')
        p = lotes.planejar(clinica.id, [sadt.id, consulta.id])
        conferir('Consulta e SP/SADT em lotes diferentes', len(p.grupos) == 2 and not p.recusadas)
        volume = [copia_fechada(sadt, base['cred_a'], salvar=False) for _ in range(101)]
        Guia.objects.bulk_create(volume)
        ids = [g.id for g in volume]
        p = lotes.planejar(clinica.id, ids)
        conferir('101 guias: 100 + 1', [g.quantidade for g in p.grupos] == [100, 1], [g.quantidade for g in p.grupos])
        Credenciamento.objects.filter(id=base['cred_a'].id).update(limite_guias_por_lote=30)
        p = lotes.planejar(clinica.id, ids)
        conferir('limite da operadora (30): 30+30+30+11', [g.quantidade for g in p.grupos] == [30, 30, 30, 11])
        Credenciamento.objects.filter(id=base['cred_a'].id).update(limite_guias_por_lote=None)
        da_b = copia_fechada(sadt, base['cred_b'])
        p = lotes.planejar(clinica.id, [sadt.id, da_b.id])
        conferir('operadoras diferentes, lotes diferentes', len(p.grupos) == 2)
        Credenciamento.objects.filter(id=base['cred_b'].id).update(versao='3.04.00')
        p = lotes.planejar(clinica.id, [da_b.id])
        conferir('versão histórica sem aceite: fora, com o motivo',
                 not p.grupos and 'aceite' in p.recusadas[0][1])
        Credenciamento.objects.filter(id=base['cred_b'].id).update(
            aceite_versao_em=timezone.now(), aceite_versao_motivo='operadora confirmou por escrito')
        p = lotes.planejar(clinica.id, [da_b.id])
        conferir('fechada em 4.00.00 e o credenciamento agora em 3.04.00: revisão', 'revisão' in p.recusadas[0][1])
        rascunho = guias.criar_guia(ctx_sec, secretaria.user, paciente, TipoGuia.SP_SADT)
        p = lotes.planejar(clinica.id, [rascunho.id])
        conferir('rascunho fica de fora', not p.grupos and p.recusadas)
        sem_snap = copia_fechada(sadt, base['cred_a'])
        Guia.objects.filter(id=sem_snap.id).update(snapshot={k: v for k, v in sadt.snapshot.items() if k != 'guia'})
        p = lotes.planejar(clinica.id, [sem_snap.id])
        conferir('guia fechada antes da geração de XML: revisão', not p.grupos and 'revisão' in p.recusadas[0][1])

        print('=== 6. Confirmar: a seleção que mudou não cria nada ===')
        p = lotes.planejar(clinica.id, [sadt.id])
        conferir('assinatura errada não cria lote',
                 recusa(lotes.criar_lotes, ctx_sec, secretaria.user, [sadt.id], 'outra') is not None
                 and not Lote.objects.filter(tenant=clinica).exists())
        criados = lotes.criar_lotes(ctx_sec, secretaria.user, [sadt.id], p.assinatura)
        lote = criados[0]
        conferir('um lote criado, em geração', len(criados) == 1 and lote.estado == EstadoLote.GERANDO)
        conferir('nada vai para o worker antes do commit', enfileirados == [])
        conferir('a guia agora está fora da fila', not lotes.elegiveis(clinica.id).filter(id=sadt.id).exists())
        conferir('o mesmo plano de novo é recusado',
                 recusa(lotes.criar_lotes, ctx_sec, secretaria.user, [sadt.id], p.assinatura) is not None)
        try:
            with transaction.atomic():
                segundo = Lote.objects.create(tenant=clinica, numero='X1', credenciamento=base['cred_a'],
                                              tipo='sp_sadt', versao='4.03.00', transacao_em=timezone.now(), quantidade=1)
                LoteGuia.objects.create(tenant=clinica, lote=segundo, guia=sadt)
            conferir('o banco recusa a guia em dois lotes ativos', False)
        except IntegrityError:
            conferir('o banco recusa a guia em dois lotes ativos', True)
        try:
            with transaction.atomic():
                Lote.objects.create(tenant=clinica, numero='X2', credenciamento=base['cred_a'], tipo='sp_sadt',
                                    versao='4.03.00', transacao_em=timezone.now(), quantidade=101)
            conferir('o banco recusa lote de 101', False)
        except IntegrityError:
            conferir('o banco recusa lote de 101', True)

        print('=== 7. O arquivo ===')
        lote = lotes.gerar_arquivo(lote.id)
        conferir('pronto', lote.estado == EstadoLote.PRONTO, lote.erros)
        caminho = Path(lote.arquivo)
        conferir('arquivo 0600', caminho.exists() and (os.stat(caminho).st_mode & 0o777) == 0o600)
        bytes1 = lotes.ler_arquivo(lote)
        conferir('SHA-256 confere', hashlib.sha256(bytes1).hexdigest() == lote.sha256)
        conferir('passa no XSD da 4.03.00', not versoes.validar('4.03.00', bytes1))
        conferir('nenhum arquivo parcial sobrando', not list(caminho.parent.glob('*.parcial')))
        gerado_em = lote.gerado_em
        de_novo = lotes.gerar_arquivo(lote.id)
        conferir('repetir a tarefa com o lote pronto não faz nada', de_novo.gerado_em == gerado_em and de_novo.tentativas == 1)
        conferir('baixar de novo: os mesmos bytes', lotes.ler_arquivo(lote) == bytes1)
        Lote.objects.filter(id=lote.id).update(estado=EstadoLote.GERANDO)
        regerado = lotes.gerar_arquivo(lote.id)
        conferir('gerar de novo produz os mesmos bytes (mesmo número, mesma hora)', regerado.sha256 == lote.sha256)
        caminho.write_bytes(bytes1.replace(b'AO6426648', b'AO6426649'))
        try:
            lotes.ler_arquivo(regerado)
            conferir('arquivo alterado no disco é acusado', False)
        except lotes.ArquivoCorrompido:
            conferir('arquivo alterado no disco é acusado', True)
        caminho.write_bytes(bytes1)
        noite = timezone.make_aware(datetime.combine(hoje, datetime.min.time()).replace(hour=23, minute=30))
        Lote.objects.filter(id=lote.id).update(transacao_em=noite, estado=EstadoLote.GERANDO)
        noturno = lotes.gerar_arquivo(lote.id)
        texto = lotes.ler_arquivo(noturno)
        conferir('23h30 local: a data e a hora da transação são as de Brasília',
                 f'<ans:dataRegistroTransacao>{hoje.isoformat()}</ans:dataRegistroTransacao>'.encode() in texto
                 and b'<ans:horaRegistroTransacao>23:30:00</ans:horaRegistroTransacao>' in texto)

        print('=== 8. Falha registrada, repetida com o mesmo número ===')
        p = lotes.planejar(clinica.id, ids[:100])
        cem = lotes.criar_lotes(ctx_sec, secretaria.user, ids[:100], p.assinatura)[0]
        Configuracao.objects.update(ativo=False)
        falhou = lotes.gerar_arquivo(cem.id)
        conferir('chave da instalação desligada: falha registrada, sem arquivo',
                 falhou.estado == EstadoLote.FALHA and not falhou.arquivo and 'desligado' in falhou.erros[0])
        Configuracao.objects.update(ativo=True)
        conferir('tentar de novo só na falha', recusa(lotes.tentar_de_novo, ctx_sec, secretaria.user, lote) is not None)
        lotes.tentar_de_novo(ctx_sec, secretaria.user, falhou)
        t0 = time.monotonic()
        cem = lotes.gerar_arquivo(cem.id)
        duracao = time.monotonic() - t0
        conferir('100 guias: pronto, mesmo número', cem.estado == EstadoLote.PRONTO and cem.numero == falhou.numero, cem.erros)
        dados100 = lotes.ler_arquivo(cem)
        conferir('100 guias SP/SADT no arquivo, e ele passa no XSD',
                 dados100.count(b'<ans:guiaSP-SADT>') == 100 and not versoes.validar('4.03.00', dados100))
        print(f'  (100 guias geradas e validadas em {duracao:.2f}s, {len(dados100) // 1024} KB)')
        p = lotes.planejar(clinica.id, [ids[100]])
        um = lotes.criar_lotes(ctx_sec, secretaria.user, [ids[100]], p.assinatura)[0]
        Lote.objects.filter(id=um.id).update(solicitado_por=None)
        sem_dono = lotes.gerar_arquivo(um.id)
        conferir('quem pediu sem vínculo: falha', sem_dono.estado == EstadoLote.FALHA and 'vínculo' in sem_dono.erros[0])
        Lote.objects.filter(id=um.id).update(solicitado_por=secretaria.user, estado=EstadoLote.GERANDO)
        # Revisão fechada por outra pessoa enquanto o lote esperava o worker.
        Guia.objects.filter(id=ids[100]).update(estado=EstadoGuia.SUBSTITUIDA)
        substituida = lotes.gerar_arquivo(um.id)
        conferir('guia substituída depois de entrar no lote: falha que manda cancelar',
                 substituida.estado == EstadoLote.FALHA and 'Cancele' in substituida.erros[0])

        print('=== 8b. A tarefa do worker e a retomada ===')
        from tiss import tasks as ttasks
        ttasks.gerar_lote.apply(args=[str(uuid.uuid4())])
        conferir('lote inexistente: a tarefa termina sem erro', True)
        original = lotes.gerar_arquivo

        def quebra(_):
            raise RuntimeError('disco cheio')

        Lote.objects.filter(id=um.id).update(estado=EstadoLote.GERANDO)
        lotes.gerar_arquivo = quebra
        try:
            ttasks.gerar_lote.apply(args=[str(um.id)])
        finally:
            lotes.gerar_arquivo = original
        quebrado = Lote.objects.get(id=um.id)
        conferir('falha inesperada vira falha registrada, sem o texto técnico',
                 quebrado.estado == EstadoLote.FALHA and 'disco' not in ' '.join(quebrado.erros))
        reenviados = []
        delay_original = ttasks.gerar_lote.delay
        ttasks.gerar_lote.delay = lambda i: reenviados.append(i)
        try:
            Lote.objects.filter(id=um.id).update(estado=EstadoLote.GERANDO)
            Lote.objects.filter(id=um.id).update(updated_at=timezone.now() - timedelta(minutes=30))
            ttasks.retomar_lotes_parados()
        finally:
            ttasks.gerar_lote.delay = delay_original
        conferir('lote parado há 30 min é reenviado ao worker', str(um.id) in reenviados)
        conferir('e só ele', len(reenviados) == 1, reenviados)
        Lote.objects.filter(id=um.id).update(estado=EstadoLote.FALHA)

        print('=== 9. Envio, retorno, cancelamento, reapresentação ===')
        conferir('envio antes do arquivo é recusado',
                 recusa(lotes.registrar_envio, ctx_sec, secretaria.user, substituida, hoje, '1') is not None)
        conferir('data de envio no futuro é recusada',
                 recusa(lotes.registrar_envio, ctx_sec, secretaria.user, cem, hoje + timedelta(days=1), '1') is not None)
        conferir('retorno antes do envio é recusado',
                 recusa(lotes.registrar_resultado, ctx_sec, secretaria.user, cem, 'aceito', '') is not None)
        lotes.registrar_envio(ctx_sec, secretaria.user, cem, hoje, 'PROT-778899')
        conferir('recusa sem o que a operadora disse é recusada',
                 recusa(lotes.registrar_resultado, ctx_sec, secretaria.user, cem, 'recusado', '') is not None)
        conferir('lote enviado e sem recusa não se cancela',
                 recusa(lotes.cancelar_lote, ctx_sec, secretaria.user, cem, 'engano') is not None)
        guia_do_lote = Guia.objects.get(id=ids[0])
        conferir('guia em lote ativo não se cancela',
                 recusa(guias.cancelar, ctx_sec, secretaria.user, guia_do_lote, 'teste') is not None)
        conferir('reapresentar exige motivo',
                 recusa(lotes.liberar_guia, ctx_sec, secretaria.user, cem, guia_do_lote, '') is not None)
        lotes.liberar_guia(ctx_sec, secretaria.user, cem, guia_do_lote, 'glosa 1705 corrigida')
        conferir('a guia liberada volta para a fila', lotes.elegiveis(clinica.id).filter(id=guia_do_lote.id).exists())
        lotes.registrar_resultado(ctx_sec, secretaria.user, cem, 'recusado', 'arquivo fora do padrão da operadora')
        lotes.cancelar_lote(ctx_sec, secretaria.user, cem, 'recusado pela operadora; reenviar')
        cem.refresh_from_db()
        conferir('recusado: cancela, as guias voltam, o arquivo fica',
                 cem.estado == EstadoLote.CANCELADO and Path(cem.arquivo).exists()
                 and lotes.elegiveis(clinica.id).filter(id__in=ids[1:100]).count() == 99)
        conferir('nada virou pagamento nem cobrança',
                 Payment.objects.filter(receivable__tenant=clinica).count() == pagamentos_antes
                 and Receivable.objects.filter(tenant=clinica).count() == recebiveis_antes)

        print('=== 10. Ciclos ===')
        Q = CicloFechamento.QUINZE
        conferir('15 a 14 na virada do ano', lotes.periodo_do_ciclo(Q, date(2026, 1, 10)) == (date(2025, 12, 15), date(2026, 1, 14)))
        conferir('15 a 14 com fevereiro', lotes.periodo_do_ciclo(Q, date(2026, 2, 20)) == (date(2026, 2, 15), date(2026, 3, 14)))
        conferir('dia 14 é o último do ciclo', lotes.periodo_do_ciclo(Q, date(2026, 3, 14)) == (date(2026, 2, 15), date(2026, 3, 14)))
        M = CicloFechamento.MENSAL
        conferir('fevereiro bissexto', lotes.periodo_do_ciclo(M, date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29)))
        conferir('mês de 30 dias', lotes.periodo_do_ciclo(M, date(2026, 4, 30)) == (date(2026, 4, 1), date(2026, 4, 30)))
        conferir('período anterior do 15 a 14', lotes.periodo_anterior(Q, date(2026, 1, 20)) == (date(2025, 12, 15), date(2026, 1, 14)))

        print('=== 11. As telas ===')
        c = cliente(secretaria)
        r = c.get('/app/tiss/faturar/')
        conferir('fila abre', r.status_code == 200 and 'Faturar guias' in r.content.decode())
        with CaptureQueriesContext(connection) as q:
            c.get('/app/tiss/faturar/')
        conferir('fila com 50 linhas em número fixo de consultas', len(q.captured_queries) < 40, len(q.captured_queries))
        conferir('GET no plano não cria nada', c.get('/app/tiss/faturar/plano/').status_code == 405)
        livres = list(lotes.elegiveis(clinica.id).filter(id__in=ids[1:4]).values_list('id', flat=True))
        r = c.post('/app/tiss/faturar/plano/', {'acao': 'ver', 'guia': [str(i) for i in livres]})
        html = r.content.decode()
        conferir('o plano aparece antes de criar', r.status_code == 200 and 'Confirmar e gerar' in html)
        antes = Lote.objects.filter(tenant=clinica).count()
        assinatura = lotes.planejar(clinica.id, livres).assinatura
        r = c.post('/app/tiss/faturar/plano/', {'acao': 'confirmar', 'guia': [str(i) for i in livres],
                                                'assinatura': assinatura})
        conferir('confirmar cria um lote', Lote.objects.filter(tenant=clinica).count() == antes + 1 and r.status_code == 302)
        novo = Lote.objects.filter(tenant=clinica).order_by('-created_at').first()
        lotes.gerar_arquivo(novo.id)
        r = c.get(f'/app/tiss/lotes/{novo.id}/')
        html = r.content.decode()
        conferir('a página do lote abre, sem a indicação clínica', r.status_code == 200 and 'túnel do carpo' not in html)
        r = c.get(f'/app/tiss/lotes/{novo.id}/arquivo/')
        baixado = b''.join(r.streaming_content) if r.streaming else r.content
        conferir('download: o arquivo gravado, como anexo',
                 r.status_code == 200 and baixado == lotes.ler_arquivo(Lote.objects.get(id=novo.id))
                 and 'attachment' in r['Content-Disposition'])
        r = c.get(f'/app/tiss/guias/{sadt.id}/')
        conferir('a guia mostra o lote em que está', f'lote {lote.numero}' in r.content.decode())
        r = c.get(f'/app/tiss/guias/{ids[5]}/')
        conferir('guia fechada fora de lote oferece "Gerar XML desta guia"', 'Gerar XML desta guia' in r.content.decode())
        estado = Lote.objects.get(id=novo.id).estado
        c.get(f'/app/tiss/lotes/{novo.id}/')
        conferir('GET no lote não muda o estado', Lote.objects.get(id=novo.id).estado == estado)
        vinculo_b = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE).first()
        if vinculo_b is not None:
            Tenant.objects.filter(id=outra.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
            cb = cliente(vinculo_b, tenant=outra)
            conferir('outra clínica: lote em 404', cb.get(f'/app/tiss/lotes/{novo.id}/').status_code == 404)
            conferir('outra clínica: arquivo em 404', cb.get(f'/app/tiss/lotes/{novo.id}/arquivo/').status_code == 404)
            r = cb.post('/app/tiss/faturar/plano/', {'acao': 'confirmar', 'guia': [str(i) for i in livres],
                                                     'assinatura': assinatura})
            conferir('outra clínica não monta lote com guia daqui',
                     Lote.objects.filter(tenant=outra).count() == 0)
        Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.BASIC)
        conferir('plano sem TISS: fila em 404', cliente(secretaria).get('/app/tiss/faturar/').status_code == 404)
        Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.COMPLETE)

        raise Desfazer
except Desfazer:
    pass
finally:
    # O banco volta atrás; o disco, não. Os arquivos dos lotes desfeitos
    # saem daqui, e só eles.
    if pasta_tiss.exists():
        for sobra in set(pasta_tiss.glob('*')) - arquivos_antes:
            sobra.unlink(missing_ok=True)

# ----------------------------------------------------------------- concorrência
print('=== 12. Duas pessoas confirmando o mesmo plano ao mesmo tempo ===')
originais = Tenant.objects.filter(id=clinica.id).values('plan', 'tiss_liberado').first()
tuss_ativas = list(CatalogRelease.objects.filter(system=CatalogSystem.TUSS, status=CatalogReleaseStatus.ACTIVE)
                   .values_list('id', flat=True))
enfileirados.clear()
config = Configuracao.carregar()
config_ativo = config.ativo
criados_aqui = {}
arquivos = []
try:
    base = preparar_base()
    criados_aqui = base
    modelo = Guia(tipo=TipoGuia.SP_SADT, cobertura=base['cobertura'], carteira='0182D000430005', data_referencia=hoje,
                  snapshot={'guia': {'numero_prestador': '0'}, 'versao': '4.03.00', 'operadora': {'registro_ans': '368253'},
                            'total': '10.00', 'itens': []})
    alvo = [copia_fechada(modelo, base['cred_a']) for _ in range(3)]
    ids_c = [g.id for g in alvo]
    assinatura = lotes.planejar(clinica.id, ids_c).assinatura
    resultado, barreira = {}, threading.Barrier(2)

    def confirmar(i):
        barreira.wait()
        try:
            resultado[i] = [x.id for x in lotes.criar_lotes(ctx_sec, secretaria.user, ids_c, assinatura)]
        except lotes.LoteRecusado:
            resultado[i] = None
        finally:
            connection.close()

    linhas = [threading.Thread(target=confirmar, args=(i,)) for i in range(2)]
    [t.start() for t in linhas]
    [t.join() for t in linhas]
    sucesso = [v for v in resultado.values() if v]
    conferir('um confirma, o outro recebe a recusa', len(sucesso) == 1 and list(resultado.values()).count(None) == 1, resultado)
    conferir('depois do commit, a geração vai para o worker uma vez', len(enfileirados) == 1, enfileirados)
    conferir('um lote só, com as três guias',
             LoteGuia.objects.filter(guia_id__in=ids_c, ativo=True).count() == 3
             and Lote.objects.filter(participacoes__guia_id__in=ids_c).distinct().count() == 1)
finally:
    lotes_criados = Lote.objects.filter(tenant=clinica, credenciamento__in=[
        criados_aqui.get('cred_a'), criados_aqui.get('cred_b')]) if criados_aqui else Lote.objects.none()
    for l in lotes_criados:
        if l.arquivo:
            Path(l.arquivo).unlink(missing_ok=True)
    LoteGuia.objects.filter(lote__in=lotes_criados).delete()
    lotes_criados.delete()
    if criados_aqui:
        guias_criadas = Guia.objects.filter(credenciamento__in=[criados_aqui['cred_a'], criados_aqui['cred_b']])
        Guia.objects.filter(revisa__in=guias_criadas).delete()
        guias_criadas.delete()
        FeeSchedule.objects.filter(plan__insurer__in=[criados_aqui['op_a'], criados_aqui['op_b']]).delete()
        Credenciamento.objects.filter(id__in=[criados_aqui['cred_a'].id, criados_aqui['cred_b'].id]).delete()
        criados_aqui['prof'].delete()
        criados_aqui['prestador'].delete()
        criados_aqui['cobertura'].delete()
        HealthPlan.objects.filter(insurer__in=[criados_aqui['op_a'], criados_aqui['op_b']]).delete()
        Insurer.objects.filter(id__in=[criados_aqui['op_a'].id, criados_aqui['op_b'].id]).delete()
        rel = CatalogRelease.objects.filter(version__startswith='ANS-roteiro-lotes-')
        ProcedureCode.objects.filter(release__in=rel).delete()
        rel.delete()
        CatalogRelease.objects.filter(id__in=tuss_ativas).update(status=CatalogReleaseStatus.ACTIVE)
    if originais:
        Tenant.objects.filter(id=clinica.id).update(**originais)
    Configuracao.objects.filter(id=config.id).update(ativo=config_ativo)

if falhas:
    raise SystemExit(f'FALHA: {len(falhas)} verificação(ões): ' + '; '.join(falhas))
print('OK: o XML de cada versão passa no XSD dela, o hash confere, os lotes não repetem guia nem\n'
      '    numeração, o arquivo é o mesmo a cada download, e nada disso vira pagamento.')
