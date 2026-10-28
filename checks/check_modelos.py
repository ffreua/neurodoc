"""Modelos de documento e a emissão por modelo, de dentro da Conduta (1.28).

O que se tenta quebrar:

1. **o catálogo do sistema** está na forma, nenhum pedido tem exame
   repetido, e **nenhum exame de imagem está num grupo de laboratório**;
2. **a tela de Modelos** abre para o médico e não para a secretária, com o
   link no menu de quem pode abrir, e as abas separam categoria de
   conjunto;
3. **o modelo do médico**: criar (com o código TUSS lido da linha), editar,
   copiar o do sistema, excluir (só POST) — e o de um médico não abre para
   outro, mas abre para o mesmo médico na outra clínica;
4. **a emissão no estruturado**: o conjunto "Queixa cognitiva" abre **dois**
   pedidos (imagem e laboratório); a imagem sem indicação é recusada sem
   gravar nada; em papel, sai um documento por categoria, com número, PDF
   sem tarja e com o paciente e os exames, nos Anexos (e o rascunho
   substituído fora da lista); o texto entra na **conduta**, depois do que
   já estava, e a versão do atendimento sobe;
5. **assinatura digital**: o documento fica pronto para assinar;
6. **texto livre**: a mesma emissão, na conduta do texto livre;
7. **finalizado**: o texto vai para **adendo**, e corpo e `content_hash`
   não mudam;
8. **cirurgia**: procedimento com TUSS, material com quantidade, convênio
   e condições no PDF; e relatório e receita pelo modelo;
9. **as recusas**: conduta que passaria do limite (nada emitido), POST
   forjado sem categoria do modelo, secretária, outra clínica, modelo
   alheio, `GET` que não emite;
10. **o resto do sistema**: o formulário genérico de documento não oferece
    os tipos novos, a retificação não aparece para eles, e a Conduta tem o
    seletor nos dois tipos de atendimento, fora de qualquer outro
    formulário.
"""
import io
import re
import uuid

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from clinical.models import (
    ClinicalAmendment, DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterKind,
    EncounterStatus,
)
from documents.models import Attachment, MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from documents.storage import read_bytes
from modelos import estrutura, padrao, servicos
from modelos.models import ModeloDocumento
from patients.models import Patient, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {obtido if len(str(obtido)) < 90 else str(obtido)[:87] + "..."}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


def texto_do_pdf(conteudo):
    from pypdf import PdfReader

    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(conteudo)).pages)


tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo(t, email=None, papel=None):
    q = Membership.objects.filter(tenant=t, status=MembershipStatus.ACTIVE).select_related('user')
    if email:
        q = q.filter(user__email=email)
    if papel:
        q = q.filter(roles__contains=[papel])
    return q.order_by('user__email').first()


medico = vinculo(tenant, 'doctor-a@demo.neurodoc.local')
outro_medico = vinculo(tenant, 'doctor-b@demo.neurodoc.local')
secretaria = vinculo(tenant, papel='secretary')
medico_em_b = vinculo(tenant_b, 'doctor-a@demo.neurodoc.local')
de_fora = vinculo(tenant_b, papel='secretary') or vinculo(tenant_b, papel='owner')


def cliente(m):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(m.tenant_id)
    s.save()
    return c


criados = {'pacientes': [], 'atendimentos': [], 'modelos': []}


def paciente(nome):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['pacientes'].append(p.id)
    return p


def atendimento(pac, kind=EncounterKind.STRUCTURED, conduta='Conduta escrita antes.'):
    e = Encounter.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico, occurred_at=timezone.now(),
        status=EncounterStatus.IN_PROGRESS, kind=kind, chief_complaint='Esquecimento.',
        free_text='Texto livre.' if kind == EncounterKind.FREE_TEXT else '', plan_text=conduta,
    )
    criados['atendimentos'].append(e.id)
    return e


def documentos_de(enc):
    return list(MedicalDocument.objects.filter(encounter=enc).order_by('created_at'))


def campos_da_tela(html):
    """Os valores que a tela de emissão já trouxe preenchidos, para reenviar."""
    dados = {}
    for nome, valor in re.findall(r'<textarea[^>]*name="([^"]+)"[^>]*>(.*?)</textarea>', html, re.S):
        import html as _html
        dados[nome] = _html.unescape(valor).lstrip('\n')
    for tag in re.findall(r'<input[^>]*>', html):
        nome = re.search(r'name="([^"]+)"', tag)
        if not nome or 'type="submit"' in tag or 'csrfmiddlewaretoken' in tag:
            continue
        valor = re.search(r'value="([^"]*)"', tag)
        if 'type="checkbox"' in tag:
            if 'checked' in tag:
                dados[nome.group(1)] = 'on'
            continue
        dados[nome.group(1)] = valor.group(1) if valor else ''
    for nome, corpo in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
        escolhido = re.search(r'<option value="([^"]*)"[^>]*selected', corpo)
        dados[nome] = escolhido.group(1) if escolhido else ''
    return dados


try:
    medico_c = cliente(medico)

    print('=== 1. o catalogo do sistema ===')
    IMAGEM = re.compile(r'\b(TOMOGRAFIA|RESSON|ANGIOTOMO|US -|MAMOGRAFIA|PET-CT|TC -|RX|RAIO)')
    conferir('o catalogo tem modelos', len(padrao.MODELOS) >= 10, True)
    slugs = [m['slug'] for m in padrao.MODELOS]
    conferir('nenhum slug repetido', len(slugs), len(set(slugs)))
    imagem_no_lab, repetidos, invalidos = [], [], []
    for m in padrao.MODELOS:
        try:
            normal = estrutura.normalizar(m['tipo'], m['conteudo'])
        except estrutura.ConteudoInvalido as exc:
            invalidos.append(f"{m['slug']}: {exc}")
            continue
        for cat, itens in normal['grupos'].items():
            nomes = [i['descricao'].casefold() for i in itens]
            if len(nomes) != len(set(nomes)):
                repetidos.append(f"{m['slug']}/{cat}")
            if cat == 'laboratorio':
                imagem_no_lab += [f"{m['slug']}: {i['descricao']}" for i in itens if IMAGEM.search(i['descricao'])]
    conferir('todos na forma do tipo', invalidos, [])
    conferir('nenhum exame repetido num pedido', repetidos, [])
    conferir('nenhum exame de imagem num grupo de laboratorio', imagem_no_lab, [])
    qc = servicos.por_chave('s:queixa-cognitiva', medico.user)
    conferir('Queixa cognitiva e conjunto de imagem + laboratorio',
             sorted(c.codigo for c in qc.categorias), ['imagem', 'laboratorio'])
    conferir('a imagem exige indicacao', estrutura.categoria('imagem').exige_indicacao, True)

    print('=== 2. a tela de Modelos ===')
    r = medico_c.get(reverse('modelos:lista'))
    conferir('o medico abre a lista', r.status_code, 200)
    html = r.content.decode()
    conferir('  e ve "Exames gerais" na aba de laboratorio', 'Exames gerais' in html, True)
    conjuntos = medico_c.get(reverse('modelos:lista') + '?tipo=exames&aba=conjuntos').content.decode()
    conferir('a aba de conjuntos tem Queixa cognitiva', 'Queixa cognitiva' in conjuntos, True)
    conferir('  e nao tem Exames gerais', 'Exames gerais' in conjuntos, False)
    conferir('a lista do laboratorio nao tem Queixa cognitiva', 'Queixa cognitiva' in html, False)
    painel = medico_c.get(reverse('reporting:dashboard')).content.decode()
    conferir('o menu do medico tem Modelos', reverse('modelos:lista') in painel, True)
    sec_c = cliente(secretaria)
    conferir('a secretaria recebe 404', sec_c.get(reverse('modelos:lista')).status_code, 404)
    sec_painel = sec_c.get(reverse('patients:list')).content.decode()
    conferir('  e nao ve o link no menu', reverse('modelos:lista') in sec_painel, False)
    conferir('ver um modelo do sistema',
             medico_c.get(reverse('modelos:ver', args=['s:queixa-cognitiva'])).status_code, 200)

    print('=== 3. o modelo do medico ===')
    nome = f'Roteiro modelos {uuid.uuid4().hex[:6]}'
    r = medico_c.post(reverse('modelos:novo', args=['exames']), {
        'nome': nome, 'grupo_imagem': '41001040 RM DE CRANIO\nTC DE CRANIO',
        'grupo_laboratorio': 'HEMOGRAMA COMPLETO', 'indicacao': 'Cefaleia.',
    })
    conferir('criar redireciona', r.status_code, 302)
    meu = ModeloDocumento.objects.filter(autor=medico.user, nome=nome).first()
    conferir('o modelo foi gravado', meu is not None, True)
    if meu:
        criados['modelos'].append(meu.id)
        conferir('  o codigo TUSS separado da descricao',
                 meu.conteudo['grupos']['imagem'][0], {'codigo': '41001040', 'descricao': 'RM DE CRANIO'})
        conferir('  como conjunto, vai para a aba de conjuntos', '&aba=conjuntos' in r['Location'], True)
        r = medico_c.post(reverse('modelos:editar', args=[meu.id]), {
            'nome': nome, 'grupo_laboratorio': 'HEMOGRAMA COMPLETO\nTSH',
        })
        meu.refresh_from_db()
        conferir('editar troca o conteudo', list(meu.conteudo['grupos']), ['laboratorio'])
        outro_c = cliente(outro_medico)
        conferir('outro medico nao edita', outro_c.get(reverse('modelos:editar', args=[meu.id])).status_code, 404)
        conferir('  nem ve', outro_c.get(reverse('modelos:ver', args=[f'u:{meu.id}'])).status_code, 404)
        conferir('  nem exclui', outro_c.post(reverse('modelos:excluir', args=[meu.id])).status_code, 404)
        conferir('o mesmo medico ve o modelo na outra clinica',
                 cliente(medico_em_b).get(reverse('modelos:ver', args=[f'u:{meu.id}'])).status_code, 200)
        conferir('excluir por GET nao existe',
                 medico_c.get(reverse('modelos:excluir', args=[meu.id])).status_code in (404, 405), True)
        conferir('  e o modelo continua', ModeloDocumento.objects.filter(id=meu.id).exists(), True)
        lista = medico_c.get(reverse('modelos:lista') + '?tipo=exames&aba=laboratorio').content.decode()
        conferir('excluir pede confirmacao', f'data-nd-confirm="Excluir o modelo {nome}?' in lista, True)
        medico_c.post(reverse('modelos:excluir', args=[meu.id]))
        conferir('excluir apaga', ModeloDocumento.objects.filter(id=meu.id).exists(), False)
    r = medico_c.post(reverse('modelos:copiar'), {'chave': 's:exames-gerais'})
    copia = ModeloDocumento.objects.filter(autor=medico.user, origem='exames-gerais').order_by('-created_at').first()
    conferir('copiar o do sistema cria um do medico', copia is not None, True)
    if copia:
        criados['modelos'].append(copia.id)
        conferir('  com os mesmos exames', len(copia.conteudo['grupos']['laboratorio']), 25)
        conferir('  e abre no editor', r['Location'], reverse('modelos:editar', args=[copia.id]))

    print('=== 4. emissao no estruturado: conjunto, papel ===')
    pac = paciente('PACIENTE ROTEIRO MODELOS')
    enc = atendimento(pac)
    EncounterDiagnosis.objects.create(
        tenant=tenant, encounter=enc, code_snapshot='G31.8',
        description_snapshot='Outras doencas degenerativas', certainty=DiagnosisCertainty.SUSPECTED,
    )
    EncounterDiagnosis.objects.create(
        tenant=tenant, encounter=enc, code_snapshot='F03',
        description_snapshot='Demencia nao especificada', certainty=DiagnosisCertainty.REFUTED, rank=2,
    )
    url = reverse('modelos:emitir', args=[enc.id])
    detalhe = medico_c.get(reverse('clinical:detail', args=[enc.id])).content.decode()
    conferir('a Conduta tem o seletor de modelos', 'id="nd-modelo-escolha"' in detalhe, True)
    conduta = detalhe[detalhe.index('id="tab-conduta"'):]
    conferir('  dentro da aba Conduta', 'id="nd-modelos"' in conduta[:conduta.find('tab-adendos') if 'tab-adendos' in conduta else None], True)
    conferir('  com o salvamento antes de sair', 'data-nd-preservar-atendimento=' in detalhe, True)
    conferir('  e o select tem rotulo', '<label class="visually-hidden" for="nd-modelo-escolha">' in detalhe, True)

    r = medico_c.get(url, {'modelo': 's:queixa-cognitiva'})
    conferir('a tela de emissao abre', r.status_code, 200)
    tela = r.content.decode()
    conferir('  com um pedido de imagem e um de laboratorio',
             ('Pedido de exames — Imagem' in tela, 'Pedido de exames — Laboratório' in tela), (True, True))
    conferir('  com a hipotese no CID e sem a refutada', ('G31.8' in tela, 'F03' in tela), (True, False))
    conferir('GET nao emite nada', len(documentos_de(enc)), 0)

    dados = campos_da_tela(tela)
    imagem = next(p for p in ('s0', 's1') if dados.get(f'{p}-categoria') == 'imagem')
    lab = 's1' if imagem == 's0' else 's0'
    versao = Encounter.objects.get(id=enc.id).row_version
    sem_indicacao = dict(dados, **{f'{imagem}-indicacao': '', 'acao': 'papel'})
    r = medico_c.post(url, sem_indicacao)
    conferir('imagem sem indicacao e recusada', r.status_code, 400)
    conferir('  e nada foi emitido', len(documentos_de(enc)), 0)
    conferir('  e a conduta nao mudou', Encounter.objects.get(id=enc.id).plan_text, 'Conduta escrita antes.')

    envio = dict(dados, **{f'{imagem}-cid': 'G31.8 — Outras doencas degenerativas', 'acao': 'papel'})
    r = medico_c.post(url, envio)
    conferir('emitir em papel volta para a aba Conduta',
             (r.status_code, r.get('Location', '').endswith('#tab-conduta')), (302, True))
    docs = documentos_de(enc)
    conferir('um documento por categoria', len(docs), 2)
    conferir('  do tipo pedido de exames', {d.kind for d in docs}, {MedicalDocumentKind.EXAM_REQUEST})
    conferir('  emitidos em papel, com numero PEX',
             all(d.status == MedicalDocumentStatus.ISSUED_ON_PAPER and d.document_number.startswith('PEX-')
                 for d in docs), True)
    d_img = next((d for d in docs if d.content_snapshot.get('categoria') == 'imagem'), None)
    if d_img:
        pdf = texto_do_pdf(read_bytes(d_img.pdf_attachment))
        conferir('o PDF de imagem tem o paciente', 'PACIENTE ROTEIRO MODELOS' in pdf, True)
        conferir('  o exame e a indicacao', ('RESSONÂNCIA MAGNÉTICA DE CRÂNIO' in pdf, 'queixa cognitiva' in pdf),
                 (True, True))
        conferir('  o CID escolhido', 'G31.8' in pdf, True)
        conferir('  e nao tem hemograma', 'HEMOGRAMA' in pdf, False)
        conferir('  e sem tarja de rascunho', 'RASCUNHO' in pdf, False)
        # A data no dia de Brasília. O PDF formatava o instante em UTC, e
        # entre 21h e meia-noite o documento saía com a data de amanhã —
        # achado nesta homologação, numa emissão às 22h50.
        hoje = timezone.localdate().strftime('%d/%m/%Y')
        conferir('  com a data de hoje no dia de Brasilia', f'Data do documento: {hoje}' in pdf, True)
    anexos = Attachment.objects.filter(patient=pac, deleted_at__isnull=True)
    conferir('nos Anexos: um PDF por documento (o rascunho saiu)', anexos.count(), 2)
    conferir('  e o rascunho substituido nao foi apagado do banco',
             Attachment.objects.filter(patient=pac, deleted_at__isnull=False).count(), 2)
    lista_anexos = medico_c.get(reverse('documents:list', args=[pac.id])).content.decode()
    conferir('a tela de Anexos lista os PDFs', lista_anexos.count('exam_request_'), 2)
    enc.refresh_from_db()
    conferir('a conduta mantem o texto anterior', enc.plan_text.startswith('Conduta escrita antes.'), True)
    conferir('  e recebe os dois pedidos',
             ('[Pedido de exames — Imagem' in enc.plan_text, '[Pedido de exames — Laboratório' in enc.plan_text),
             (True, True))
    conferir('  com os exames', 'RESSONÂNCIA MAGNÉTICA DE CRÂNIO' in enc.plan_text, True)
    conferir('a versao do atendimento subiu', enc.row_version, versao + 1)
    ev = AuditEvent.objects.filter(action='modelos.documentos_emitidos', object_id=enc.id).first()
    conferir('a trilha registra, sem o texto',
             (ev is not None, 'RESSON' in str(ev.integrity_metadata) if ev else None), (True, False))
    tela_enc = medico_c.get(reverse('clinical:detail', args=[enc.id])).content.decode()
    conferir('a Conduta lista os documentos do atendimento, com o numero',
             all(d.document_number in tela_enc for d in docs), True)

    print('=== 5. assinatura digital ===')
    r = medico_c.get(url, {'modelo': 's:exames-gerais'})
    r = medico_c.post(url, dict(campos_da_tela(r.content.decode()), acao='assinatura'))
    novo = documentos_de(enc)[-1]
    conferir('fica pronto para assinar', novo.status, MedicalDocumentStatus.READY_TO_SIGN)
    conferir('  sem numero ainda', novo.document_number, '')
    conferir('  com o rascunho nos Anexos', novo.pdf_attachment.deleted_at is None, True)

    print('=== 6. texto livre ===')
    livre = atendimento(paciente('PACIENTE ROTEIRO MODELOS LIVRE'), kind=EncounterKind.FREE_TEXT, conduta='')
    tela_livre = medico_c.get(reverse('clinical:detail', args=[livre.id])).content.decode()
    conferir('o texto livre tem o seletor', 'id="nd-modelo-escolha"' in tela_livre, True)
    conferir('  e nenhum formulario aninhado',
             all('<form' not in bloco.split('</form>')[0] for bloco in tela_livre.split('<form')[1:]), True)
    url_livre = reverse('modelos:emitir', args=[livre.id])
    r = medico_c.get(url_livre, {'modelo': 'b:relatorio'})
    r = medico_c.post(url_livre, {'modelo': 'b:relatorio', 's0-emitir': 'on',
                                  's0-texto': 'Paciente em acompanhamento neurologico.', 'acao': 'papel'})
    conferir('volta para o bloco de modelos', r.get('Location', '').endswith('#nd-modelos'), True)
    livre.refresh_from_db()
    conferir('o relatorio entra na conduta do texto livre',
             livre.plan_text.startswith('[Relatório · emitido em papel'), True)
    conferir('  e o documento e um relatorio emitido',
             [(d.kind, d.status) for d in documentos_de(livre)],
             [(MedicalDocumentKind.REPORT, MedicalDocumentStatus.ISSUED_ON_PAPER)])

    print('=== 7. finalizado: adendo ===')
    fin = atendimento(paciente('PACIENTE ROTEIRO MODELOS FINAL'))
    Encounter.objects.filter(id=fin.id).update(status=EncounterStatus.FINALIZED, finalized_at=timezone.now())
    fin.refresh_from_db()
    fin.content_hash = fin.compute_content_hash()
    fin.save(update_fields=['content_hash'])
    antes = (fin.plan_text, fin.content_hash)
    url_fin = reverse('modelos:emitir', args=[fin.id])
    r = medico_c.post(url_fin, {'modelo': 'b:exames:laboratorio', 's0-emitir': 'on',
                                's0-categoria': 'laboratorio', 's0-itens': 'TSH', 'acao': 'papel'})
    fin.refresh_from_db()
    conferir('emitir depois de finalizar funciona', len(documentos_de(fin)), 1)
    conferir('  o corpo e o hash nao mudam', (fin.plan_text, fin.content_hash), antes)
    adendo = ClinicalAmendment.objects.filter(encounter=fin).first()
    conferir('  e o texto vira adendo', adendo is not None and 'TSH' in adendo.text, True)

    print('=== 8. cirurgia, receita ===')
    cir = atendimento(paciente('PACIENTE ROTEIRO MODELOS CIRURGIA'), conduta='')
    url_cir = reverse('modelos:emitir', args=[cir.id])
    r = medico_c.post(url_cir, {
        'modelo': 'b:cirurgia', 's0-emitir': 'on',
        's0-procedimentos': '30715016 ARTRODESE DE COLUNA x2',
        's0-materiais': '4 x PARAFUSO PEDICULAR 6,5 x 45 mm', 's0-indicacao': 'Estenose com instabilidade.',
        's0-carater': 'eletiva', 's0-regime': 'internacao', 's0-dias_internacao': '3',
        's0-anestesia': 'geral', 's0-lateralidade': '', 's0-uti': 'on', 's0-local': 'Hospital Roteiro',
        'acao': 'papel',
    })
    conferir('a solicitacao de cirurgia e emitida', r.status_code, 302)
    dc = documentos_de(cir)
    if dc:
        conteudo = dc[0].content_snapshot
        conferir('  o procedimento com TUSS e quantidade', conteudo['procedimentos'][0],
                 {'codigo': '30715016', 'descricao': 'ARTRODESE DE COLUNA', 'quantidade': 2})
        conferir('  o material com quantidade', conteudo['materiais'][0],
                 {'descricao': 'PARAFUSO PEDICULAR 6,5 x 45 mm', 'quantidade': 4})
        pdf = texto_do_pdf(read_bytes(dc[0].pdf_attachment))
        conferir('  o PDF com codigo, material e UTI',
                 ('30715016' in pdf, 'PARAFUSO PEDICULAR' in pdf, 'UTI no pós-operatório: Sim' in pdf),
                 (True, True, True))
        conferir('  numero CIR', dc[0].document_number.startswith('CIR-'), True)
    r = medico_c.post(url_cir, {'modelo': 'b:receita', 's0-emitir': 'on', 's0-formato': 'simple',
                                's0-texto': 'Paracetamol 750 mg', 'acao': 'papel'})
    conferir('a receita pelo modelo e uma receita',
             documentos_de(cir)[-1].kind if len(documentos_de(cir)) > 1 else None, MedicalDocumentKind.PRESCRIPTION)

    print('=== 9. recusas ===')
    grande = atendimento(paciente('PACIENTE ROTEIRO MODELOS LIMITE'), conduta='x' * 19990)
    r = medico_c.post(reverse('modelos:emitir', args=[grande.id]), {
        'modelo': 'b:exames:laboratorio', 's0-emitir': 'on', 's0-categoria': 'laboratorio',
        's0-itens': 'HEMOGRAMA COMPLETO', 'acao': 'papel'})
    conferir('conduta acima do limite e recusada', r.status_code, 400)
    conferir('  e nada foi emitido', len(documentos_de(grande)), 0)
    r = medico_c.post(url, {'modelo': 'b:exames:laboratorio', 's0-emitir': 'on',
                            's0-categoria': 'imagem', 's0-itens': 'TC DE CRANIO', 'acao': 'papel'})
    ultimo = documentos_de(enc)[-1]
    conferir('POST forjado nao troca a categoria do modelo',
             ultimo.content_snapshot.get('categoria'), 'laboratorio')
    conferir('sem escolher papel ou assinatura e recusado',
             medico_c.post(url, {'modelo': 'b:relatorio', 's0-emitir': 'on', 's0-texto': 'x'}).status_code, 400)
    conferir('a secretaria nao abre a emissao', sec_c.get(url, {'modelo': 's:exames-gerais'}).status_code, 404)
    conferir('  nem emite', sec_c.post(url, {'modelo': 'b:relatorio', 's0-emitir': 'on',
                                             's0-texto': 'x', 'acao': 'papel'}).status_code, 404)
    if de_fora is not None:
        conferir('outra clinica nao abre', cliente(de_fora).get(url, {'modelo': 'b:relatorio'}).status_code, 404)
    conferir('o medico na outra clinica nao abre o atendimento daqui',
             cliente(medico_em_b).get(url, {'modelo': 'b:relatorio'}).status_code, 404)
    alheio = ModeloDocumento.objects.create(autor=outro_medico.user, tipo='relatorio', nome='Alheio',
                                            conteudo={'texto': 'segredo'})
    criados['modelos'].append(alheio.id)
    conferir('modelo de outro medico nao abre na emissao',
             medico_c.post(url, {'modelo': f'u:{alheio.id}', 's0-emitir': 'on', 's0-texto': 'x',
                                 'acao': 'papel'}).status_code, 404)

    print('=== 10. o resto do sistema ===')
    from documents.forms import MedicalDocumentForm

    escolhas = dict(MedicalDocumentForm().fields['kind'].choices)
    conferir('o formulario generico nao oferece os tipos novos',
             ('exam_request' in escolhas, 'surgery_request' in escolhas), (False, False))
    generico = medico_c.post(reverse('documents:medical-new', args=[enc.id]),
                             {'kind': 'exam_request'})
    conferir('  nem aceita por POST', generico.status_code != 302, True)
finally:
    from documents.models import MedicalDocument as _Doc

    ids = list(_Doc.objects.filter(encounter_id__in=criados['atendimentos']).values_list('id', flat=True))
    anexos = list(Attachment.objects.filter(patient_id__in=criados['pacientes']).values_list('id', 'storage_key'))
    _Doc.objects.filter(id__in=ids).delete()
    from pathlib import Path

    for _, chave in anexos:
        if chave:
            Path(chave).unlink(missing_ok=True)
    Attachment.objects.filter(id__in=[a for a, _ in anexos]).delete()
    ClinicalAmendment.objects.filter(encounter_id__in=criados['atendimentos']).delete()
    EncounterDiagnosis.objects.filter(encounter_id__in=criados['atendimentos']).delete()
    Encounter.objects.filter(id__in=criados['atendimentos']).delete()
    Patient.objects.filter(id__in=criados['pacientes']).delete()
    ModeloDocumento.objects.filter(id__in=criados['modelos']).delete()

print()
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: modelos, emissao por modelo na Conduta, documento nos Anexos e texto no prontuario.')
