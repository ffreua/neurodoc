"""Receita com catalogo CMED, emissao em papel e QR so quando assinado.

Tenta quebrar. As perguntas sao:

- o catalogo da CMED esta importado e a busca acha por substancia e por
  nome comercial?
- a busca devolve a tarja, e a sugestao de controle especial bate com ela?
- a busca ignora termo curto demais e nao estoura com termo estranho?
- da para emitir documento SEM atendimento, a partir da ficha do paciente?
- o documento sem atendimento continua pertencendo ao paciente e ao
  inquilino certos?
- o rascunho sai SEM QR?
- o emitido em PAPEL sai sem QR, sem a tarja de rascunho, e COM numero?
- o endpoint publico do portal responde, e so para portal publicado?
- o endpoint autenticado recusa quem nao tem vinculo?
- a receita de controle especial continua exigindo endereco?
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

import json

from accounts.models import User
from catalogs.models import CatalogReleaseStatus, CatalogSystem, CatalogRelease, MedicationProduct
from catalogs.selectors import search_medications
from documents import issuance
from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from documents.pdf import render_medical_document_pdf
from patients.models import Patient
from tenancy.models import ClinicProfile, Membership, Tenant

failures = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
vinculo_medico = Membership.objects.get(tenant=tenant_a, user=medico)
paciente = Patient.objects.filter(tenant=tenant_a).first()
criados = []


def entrar(user, tenant=None):
    tenant = tenant or tenant_a
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


print('=== 1. o catalogo da CMED esta no ar ===')
release = CatalogRelease.objects.filter(
    system=CatalogSystem.CMED, status=CatalogReleaseStatus.ACTIVE,
).first()
total = MedicationProduct.objects.filter(release=release).count() if release else 0
print(f'  release ativa                 -> {release.version if release else "NENHUMA"}')
print(f'  apresentacoes                 -> {total}')
if release is None:
    failures.append('nao ha release CMED ativa — rode manage.py import_cmed')
elif total < 10000:
    failures.append(f'so {total} apresentacoes na release ativa; esperado mais de 10 mil')

print('=== 2. a busca acha por substancia e por nome comercial ===')
for termo, esperado in [('clonazepam', 'substancia'), ('rivotril', 'nome comercial')]:
    r = search_medications(termo)
    print(f'  {termo:<14} ({esperado:<14}) -> {len(r)} resultados | 1o: {r[0]["rotulo"][:44] if r else "NADA"}')
    if not r:
        failures.append(f'a busca nao achou nada para {termo!r}')

print('=== 3. a tarja e a sugestao andam juntas ===')
amostra = search_medications('clonazepam')
if amostra:
    preta = [x for x in amostra if x['tarja'] == 'preta']
    print(f'  clonazepam com tarja preta    -> {len(preta)} de {len(amostra)}')
    incoerentes = [x for x in amostra if x['controle_especial'] != (x['tarja'] in ('preta', 'vermelha_restrita'))]
    print(f'  sugestao incoerente com tarja -> {len(incoerentes)} (0 esperado)')
    if incoerentes:
        failures.append('a sugestao de controle especial nao bate com a tarja')
    if not preta:
        failures.append('nenhum clonazepam com tarja preta — a importacao perdeu a coluna TARJA?')
sem_tarja = [x for x in search_medications('dipirona') if x['controle_especial']]
print(f'  dipirona sugerindo especial   -> {len(sem_tarja)} (0 esperado)')

print('=== 4. termo curto e termo estranho ===')
print(f'  termo de 1 letra              -> {search_medications("a")} (vazio esperado)')
if search_medications('a'):
    failures.append('termo de uma letra devolveu resultado')
for esquisito in ("'; DROP TABLE --", 'áçãõ' * 20, '%%%'):
    try:
        r = search_medications(esquisito)
        print(f'  {esquisito[:22]!r:<26} -> {len(r)} resultados, sem erro')
    except Exception as e:
        failures.append(f'a busca estourou com {esquisito[:20]!r}: {e}')

print('=== 5. documento SEM atendimento ===')
doc = issuance.create_draft(
    tenant_a, paciente, None, vinculo_medico, medico.id,
    MedicalDocumentKind.PRESCRIPTION, {'prescription_text': 'Dipirona 500 mg — 1 cp de 6/6h se dor'},
)
criados.append(doc)
print(f'  criado                        -> {doc.id}')
print(f'  atendimento vinculado         -> {doc.encounter_id} (None esperado)')
print(f'  paciente                      -> {doc.patient_id == paciente.id}')
print(f'  inquilino                     -> {doc.tenant_id == tenant_a.id}')
if doc.encounter_id is not None:
    failures.append('o documento sem atendimento nasceu com atendimento')
if doc.patient_id != paciente.id or doc.tenant_id != tenant_a.id:
    failures.append('documento sem atendimento com paciente ou inquilino errado')

def texto_do_pdf(conteudo):
    """O texto do PDF, de verdade.

    Procurar a palavra nos bytes crus nao funciona: o ReportLab comprime os
    fluxos de texto, e `b"RASCUNHO" in pdf` da False mesmo com a tarja
    impressa na pagina. Foi o que a primeira versao deste roteiro fazia --
    e ela passava dizendo que tinha conferido.
    """
    import io
    from pypdf import PdfReader
    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(conteudo)).pages)


print('=== 6. o rascunho: tarja de rascunho, sem QR ===')
pdf_rascunho = render_medical_document_pdf(doc)
texto = texto_do_pdf(pdf_rascunho)
tem_aviso = 'RASCUNHO SEM VALIDADE' in texto
tem_codigo = 'Confira este documento em' in texto
print(f'  tamanho do PDF                -> {len(pdf_rascunho)} bytes')
print(f'  traz a tarja de rascunho      -> {tem_aviso} (True esperado)')
print(f'  traz o bloco de verificacao   -> {tem_codigo} (False esperado)')
from documents.pdf.common import _qr_flowable
print(f'  _qr_flowable no rascunho      -> {_qr_flowable(doc)} (None esperado)')
if not tem_aviso:
    failures.append('o rascunho saiu sem a tarja de rascunho')
if tem_codigo or _qr_flowable(doc) is not None:
    failures.append('o rascunho saiu com QR — o QR so vale com assinatura digital')

print('=== 7. emissao em PAPEL ===')
issuance.mark_reviewed(doc, medico.id)
papel = issuance.issue_on_paper(doc, medico.id)
print(f'  status                        -> {papel.status} (issued_on_paper esperado)')
print(f'  numero do documento           -> {papel.document_number}')
print(f'  data de emissao               -> {papel.issued_at is not None}')
print(f'  _qr_flowable no papel         -> {_qr_flowable(papel)} (None esperado)')
if papel.status != MedicalDocumentStatus.ISSUED_ON_PAPER:
    failures.append(f'emissao em papel deixou o estado em {papel.status}')
if not papel.document_number:
    failures.append('emitido em papel sem numero de documento')
if _qr_flowable(papel) is not None:
    failures.append('o documento de papel saiu com QR')
pdf_papel = render_medical_document_pdf(papel)
texto_papel = texto_do_pdf(pdf_papel)
sem_rascunho = 'RASCUNHO SEM VALIDADE' not in texto_papel
tem_frase = 'assinatura de próprio punho' in texto_papel
sem_qr = 'Confira este documento em' not in texto_papel
tem_numero_no_papel = papel.document_number in texto_papel
print(f'  PDF do papel                  -> {len(pdf_papel)} bytes')
print(f'  SEM a tarja de rascunho       -> {sem_rascunho} (True esperado)')
print(f'  diz que e para assinar a mao  -> {tem_frase} (True esperado)')
print(f'  SEM bloco de verificacao/QR   -> {sem_qr} (True esperado)')
print(f'  numero impresso na pagina     -> {tem_numero_no_papel} (True esperado)')
for condicao, erro in [
    (sem_rascunho, 'o documento de papel saiu com a tarja de rascunho'),
    (tem_frase, 'o documento de papel nao diz que vale pela assinatura de proprio punho'),
    (sem_qr, 'o documento de papel saiu com o bloco de verificacao/QR'),
    (tem_numero_no_papel, 'o numero do documento nao saiu impresso no papel'),
]:
    if not condicao:
        failures.append(erro)

print('=== 7b. a identidade visual da clinica sai no PDF ===')
perfil_clinica = ClinicProfile.objects.filter(tenant=tenant_a).first()
nome_clinica = tenant_a.trade_name or tenant_a.legal_name
print(f'  nome da clinica no papel      -> {nome_clinica[:28] in texto_papel}')
if nome_clinica[:28] not in texto_papel:
    failures.append('o timbre nao traz o nome da clinica')
from documents.pdf.common import _logo_flowable
tem_logo = perfil_clinica is not None and perfil_clinica.has_logo
print(f'  clinica tem logotipo          -> {tem_logo}')
if tem_logo:
    print(f'  logotipo entra no timbre      -> {_logo_flowable(perfil_clinica) is not None}')
    if _logo_flowable(perfil_clinica) is None:
        failures.append('a clinica tem logotipo mas ele nao entra no PDF')
else:
    print('  (sem logotipo cadastrado — o timbre sai so com o texto, como previsto)')

print('=== 8. emitir em papel duas vezes ===')
try:
    issuance.issue_on_paper(papel, medico.id)
    failures.append('emitiu em papel duas vezes — gastaria dois numeros para a mesma receita')
    print('  segunda emissao               -> ACEITOU (falha)')
except ValueError as e:
    print(f'  segunda emissao               -> recusou: {str(e)[:60]}')

print('=== 9. os endpoints de busca ===')
cliente_med = entrar(medico)
r = cliente_med.get('/app/codigos/medicamentos/buscar/?q=clonazepam')
dados = json.loads(r.content.decode())
print(f'  autenticado                   -> {r.status_code}, {len(dados["results"])} resultados')
if r.status_code != 200 or not dados['results']:
    failures.append(f'endpoint autenticado falhou ({r.status_code})')

anonimo = Client()
r = anonimo.get('/app/codigos/medicamentos/buscar/?q=clonazepam')
print(f'  sem sessao                    -> {r.status_code} (302 para login esperado)')
if r.status_code == 200:
    failures.append('o endpoint autenticado respondeu sem sessao')

perfil = ClinicProfile.objects.filter(tenant=tenant_a).first()
if perfil is None:
    perfil = ClinicProfile.objects.create(tenant=tenant_a)
portal_antes = perfil.patient_portal_enabled
perfil.patient_portal_enabled = True
perfil.save(update_fields=['patient_portal_enabled'])
r = anonimo.get(f'/solicitacoes/{tenant_a.slug}/medicamentos/?q=clonazepam')
print(f'  portal publicado              -> {r.status_code} (200 esperado)')
if r.status_code != 200:
    failures.append(f'o endpoint do portal nao respondeu com o portal publicado ({r.status_code})')
perfil.patient_portal_enabled = False
perfil.save(update_fields=['patient_portal_enabled'])
r = anonimo.get(f'/solicitacoes/{tenant_a.slug}/medicamentos/?q=clonazepam')
print(f'  portal despublicado           -> {r.status_code} (404 esperado)')
if r.status_code != 404:
    failures.append(f'o endpoint do portal respondeu com o portal desligado ({r.status_code})')
perfil.patient_portal_enabled = portal_antes
perfil.save(update_fields=['patient_portal_enabled'])

print('=== 10. controle especial continua exigindo endereco ===')
sem_endereco = Patient.objects.filter(tenant=tenant_a).exclude(street='').exclude(city='').first()
alvo = sem_endereco or paciente
rua, cidade, uf = alvo.street, alvo.city, alvo.state
alvo.street, alvo.city, alvo.state = '', '', ''
alvo.save(update_fields=['street', 'city', 'state'])
try:
    d = issuance.create_draft(
        tenant_a, alvo, None, vinculo_medico, medico.id, MedicalDocumentKind.PRESCRIPTION,
        {'prescription_text': 'Clonazepam 2 mg', 'prescription_format': 'special_control'},
    )
    criados.append(d)
    failures.append('controle especial aceito sem endereco do paciente')
    print('  sem endereco                  -> ACEITOU (falha)')
except ValueError as e:
    print(f'  sem endereco                  -> recusou: {str(e)[:56]}')
alvo.street, alvo.city, alvo.state = rua, cidade, uf
alvo.save(update_fields=['street', 'city', 'state'])

print('=== 10b. o controle especial sai no formato do Anexo XVII ===')
# Duas vias, e em cada uma a assinatura do medico ACIMA dos quadros de
# comprador e fornecedor.
#
# A ordem ja foi a inversa aqui, com o argumento de que a assinatura
# fecha o documento e nao deve ter campo em branco embaixo. O formulario
# oficial faz o contrario: os dois quadros ficam no rodape, abaixo da
# assinatura do prescritor, e e la que o balconista aprendeu a procurar.
especial = issuance.create_draft(
    tenant_a, paciente, None, vinculo_medico, medico.id,
    MedicalDocumentKind.PRESCRIPTION,
    {'prescription_text': 'Clonazepam 2 mg — 1 comprimido a noite',
     'prescription_format': 'special_control'},
)
criados.append(especial)

import io as _io
from pypdf import PdfReader as _PdfReader

_pdf = render_medical_document_pdf(especial)
_paginas = _PdfReader(_io.BytesIO(_pdf)).pages
print(f'  vias (uma pagina cada)        -> {len(_paginas)} (2 esperado)')
if len(_paginas) != 2:
    failures.append(f'o controle especial saiu com {len(_paginas)} via(s), e nao 2')

for _n, _pagina in enumerate(_paginas, start=1):
    _linhas = [l.strip() for l in (_pagina.extract_text() or '').splitlines() if l.strip()]

    def _onde(alvo, linhas=_linhas):
        for i, linha in enumerate(linhas):
            if alvo.lower() in linha.lower():
                return i
        return None

    # A ancora e a **linha de assinatura**, e nao a palavra "CRM": o CRM
    # aparece antes no cabecalho do emitente, e ancorar nele fazia esta
    # conferencia passar mesmo com os quadros acima da assinatura. Foi o
    # que a primeira versao desta secao fazia.
    import re as _re

    _assinatura = next(
        (i for i, l in enumerate(_linhas) if _re.fullmatch(r'_{20,}', l)), None,
    )
    _comprador = _onde('COMPRADOR')
    _fornecedor = _onde('FORNECEDOR')
    _via = _onde('VIA —') if _onde('VIA —') is not None else _onde('VIA')
    print(f'  via {_n}: rotulo={_linhas[_via][:30] if _via is not None else None!r}  '
          f'linha de assinatura={_assinatura}  comprador={_comprador}  '
          f'fornecedor={_fornecedor}')
    if None in (_assinatura, _comprador, _fornecedor):
        failures.append(f'via {_n} do controle especial sem assinatura ou sem os quadros')
        continue
    # E o nome e o CRM acompanham a linha, logo abaixo dela.
    _bloco = ' '.join(_linhas[_assinatura:_comprador])
    if 'CRM' not in _bloco:
        failures.append(f'via {_n}: a linha de assinatura saiu sem o CRM abaixo dela')
    if not _assinatura < _comprador:
        failures.append(f'via {_n}: os quadros vieram ACIMA da assinatura do medico')
    if not _comprador < _fornecedor:
        failures.append(f'via {_n}: o quadro do fornecedor veio antes do comprador')

# Os rotulos de via dizem qual folha fica retida.
_texto_especial = texto_do_pdf(_pdf)
for _rotulo in ['RETENÇÃO DA FARMÁCIA', 'ORIENTAÇÃO AO PACIENTE']:
    if _rotulo not in _texto_especial:
        failures.append(f'o controle especial saiu sem o rotulo "{_rotulo}"')
print(f'  rotulos das duas vias         -> '
      f'{all(r in _texto_especial for r in ["RETENÇÃO DA FARMÁCIA", "ORIENTAÇÃO AO PACIENTE"])}')

print('=== 11. a tela do paciente oferece emitir documento ===')
pagina = cliente_med.get(f'/app/patients/{paciente.id}/')
tem_botao = b'documents/patients/' in pagina.content or b'Emitir documento' in pagina.content
print(f'  botao na ficha                -> {tem_botao}')
if pagina.status_code == 200 and not tem_botao:
    failures.append('a ficha do paciente nao oferece emitir documento')
r = cliente_med.get(f'/app/documents/patients/{paciente.id}/medical/new/')
print(f'  formulario sem atendimento    -> {r.status_code} (200 esperado)')
if r.status_code != 200:
    failures.append(f'o formulario sem atendimento nao abriu ({r.status_code})')
tem_busca = b'nd-med-busca' in r.content and b'medicamentos/buscar' in r.content
print(f'  com a busca de medicamento    -> {tem_busca}')
if r.status_code == 200 and not tem_busca:
    failures.append('o formulario nao traz a busca de medicamento')

print('=== 12. fronteira: paciente de outra clinica ===')
paciente_b = Patient.objects.filter(tenant=tenant_b).first()
if paciente_b:
    r = cliente_med.get(f'/app/documents/patients/{paciente_b.id}/medical/new/')
    print(f'  paciente da clinica B         -> {r.status_code} (404 esperado)')
    if r.status_code != 404:
        failures.append(f'abriu formulario para paciente de outra clinica ({r.status_code})')

print('=== limpeza ===')
def _remover_anexos_dos_documentos(ids):
    """Tira do banco e do disco os PDFs dos documentos que o roteiro criou.

    Apagar so o `MedicalDocument` deixava o `Attachment` do rascunho (e o
    do assinado, quando havia) orfao no banco e o arquivo no volume de
    midia. Somados os cinco roteiros que emitem documento, eram vinte e
    dois anexos por rodada acumulando na clinica de demonstracao.

    A segunda varredura, por PDF **sem dono**, existe porque nem todo
    documento chega aqui pela lista: um que o proprio roteiro ja apagou,
    ou que foi substituido no meio do caminho, sai da lista e levaria o
    anexo junto para o esquecimento. O nome do arquivo de documento carrega
    o id dele (`<tipo>_<uuid>_draft.pdf`), e um desses que nenhum
    `MedicalDocument` reivindica nao e de ninguem.
    """
    import re
    from pathlib import Path

    from documents.models import Attachment, MedicalDocument

    anexos = []
    for atual in MedicalDocument.objects.filter(id__in=ids).values(
        'pdf_attachment_id', 'signed_pdf_attachment_id',
    ):
        anexos += [v for v in atual.values() if v]
    MedicalDocument.objects.filter(id__in=ids).delete()

    padrao = re.compile(r'^[a-z_]+_[0-9a-f-]{36}_(draft|signed|papel)\.pdf$')
    com_dono = set(
        MedicalDocument.objects.values_list('pdf_attachment_id', flat=True)
    ) | set(
        MedicalDocument.objects.values_list('signed_pdf_attachment_id', flat=True)
    )
    for att in Attachment.objects.exclude(id__in=[i for i in com_dono if i]):
        if padrao.match(att.original_name or ''):
            anexos.append(att.id)

    if not anexos:
        return 0
    for att in Attachment.objects.filter(id__in=anexos):
        if att.storage_key:
            Path(att.storage_key).unlink(missing_ok=True)
    apagados, _ = Attachment.objects.filter(id__in=anexos).delete()
    return apagados


_anexos = _remover_anexos_dos_documentos([d.id for d in criados])
print(f'  {len(criados)} documento(s) e {_anexos} anexo(s) removido(s)')

print()
print('=== a busca de medicamento nao engole o que foi digitado ===')
# Defeito relatado em 2026-09-25, com o PDF na mao: saiu um Receituario de
# Controle Especial assinado com "1 cp VO a noite" e **sem o medicamento**.
#
# A causa nao estava no gerador do PDF. A caixa "Buscar medicamento na
# tabela da Anvisa" fica DENTRO do formulario e **nao tem `name`**: o que se
# digita nela nunca e enviado. Quem procurava um remedio que a CMED nao tem
# via a frase "pode escrever a mao, o campo aceita", entendia que aquele
# campo aceitava, escrevia a posologia no campo de baixo e enviava.
#
# O conserto nao foi por o `name` -- a caixa e busca, nao dado da receita --
# e sim transformar o estado vazio numa ACAO: um botao que leva o termo
# digitado para a prescricao, que e o campo que existe de verdade.
from django.conf import settings as _dj

_RAIZ = _dj.BASE_DIR
_js = (_RAIZ / 'static' / 'catalogs' / 'medicamentos.js').read_text(encoding='utf-8')
_form = (_RAIZ / 'templates' / 'documents' / 'medical_form.html').read_text(encoding='utf-8')

_i = _form.index('id="nd-med-busca"')
_tag = _form[_form.rfind('<input', 0, _i):_form.index('>', _i) + 1]
_tem_name = 'name=' in _tag
print(f'  a caixa de busca e enviada com o formulario: {_tem_name} (False esperado)')

# Se um dia ganhar `name`, o que se digita passa a ser enviado e esta secao
# perde o sentido -- mas ai o campo vira dado da receita sem ninguem ter
# decidido isso, e e melhor o roteiro avisar.
if _tem_name:
    failures.append(
        'a caixa de busca de medicamento ganhou `name` e passou a ser enviada — '
        'ela e busca, nao dado da receita; se a mudanca foi de proposito, refaca '
        'esta secao'
    )

_saida = 'assim mesmo' in _js
print(f'  ha saida para o que a CMED nao tem (botao "assim mesmo"): {_saida}')
if not _saida:
    failures.append(
        'o estado "nada na lista" voltou a ser um beco sem saida: o medico digita '
        'o remedio, nada acontece, e a receita sai com a posologia e sem o medicamento'
    )

_leva = 'acrescentarNaReceita' in _js and _js.count('acrescentarNaReceita(') >= 3
print(f'  o botao leva o termo para a prescricao: {_leva}')
if not _leva:
    failures.append(
        'o botao do estado vazio nao usa o mesmo caminho que o item escolhido da '
        'lista — os dois tem de acrescentar linha na prescricao'
    )

# A tela precisa dizer que a caixa nao vale como prescricao. O texto antigo
# ("voce continua escrevendo a vontade -- inclusive o que nao esta na
# tabela") era verdadeiro e foi lido ao contrario.
_avisa = 'só para buscar' in _form or 'so para buscar' in _form
print(f'  a tela avisa que a caixa e so para buscar: {_avisa}')
if not _avisa:
    failures.append(
        'a ajuda da caixa de busca nao diz que o que se digita nela nao vai para '
        'a receita sozinho'
    )

# E o gerador do PDF nao pode comer nada do que foi escrito -- foi o outro
# lado do mesmo sintoma, corrigido na auditoria pre-deploy.
from documents.pdf.common import paragrafo_de_texto, texto_seguro

_amostra = 'Melatonina <3mg> & cia'
_saiu = texto_seguro(_amostra)
print(f'  texto com < > & sobrevive ao escape: {_amostra!r} -> {_saiu!r}')
if 'Melatonina' not in _saiu or '3mg' not in _saiu:
    failures.append('o escape do PDF esta comendo parte do texto da prescricao')

if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: catalogo CMED no ar, busca coerente com a tarja, documento sem atendimento,')
print('    emissao em papel com numero e sem QR, e QR so com assinatura digital.')
