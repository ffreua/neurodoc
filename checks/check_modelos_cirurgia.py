"""Os modelos de solicitação de cirurgia do sistema (2026-11-12).

Os cinquenta modelos vieram dos arquivos do Dr. Fernando Freua — o guia de
como deve ser uma solicitação de cirurgia e as tabelas de codificação de
crânio e de coluna. O que se tenta quebrar:

1. **o catálogo**: os cinquenta na forma, todo código TUSS e todo CID
   existindo nos catálogos do sistema, os dois códigos errados dos arquivos
   fora (2.02.02.03-2 é monitorização *hemodinâmica*; 3.07.15.35-9 não
   existe), e a justificativa com o roteiro do guia;
2. **a tela de emissão**: as listas marcadas para as linhas com caixa de
   setas, os três fornecedores com as sugestões, e os CIDs do modelo na
   escolha, separados das hipóteses do atendimento;
3. **a recusa**: justificativa que ainda tem `[completar]` não emite nada;
4. **a emissão completa**: CID do modelo, quantidade mudada, fornecedores,
   monitorização, materiais hospitalares, hemocomponentes, equipe de
   anestesia, tempo de sala e UTI no documento, no PDF e na conduta;
5. **o editor**: o modelo copiado abre e salva sem perder nada — os três
   fornecedores, os CIDs, a quantidade —, e a mudança fica só na cópia;
6. **o documento antigo**: o conteúdo gravado antes dos campos novos
   continua na forma.
"""
import io
import re

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from catalogs.models import DiagnosisCode, ProcedureCode
from clinical.models import Encounter, EncounterKind, EncounterStatus
from documents.models import Attachment, MedicalDocument
from documents.storage import read_bytes
from modelos import estrutura, padrao
from modelos.forms import ModeloForm, valores_iniciais_do_editor
from modelos.models import ModeloDocumento
from modelos.padrao_cirurgia import MODELOS as CIRURGIAS
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
medico = (Membership.objects.filter(tenant=tenant, status=MembershipStatus.ACTIVE,
                                    user__email='doctor-a@demo.neurodoc.local')
          .select_related('user').first())
c = Client()
c.force_login(medico.user)
sessao = c.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

criados = {'pacientes': [], 'atendimentos': [], 'modelos': []}

try:
    print('=== 1. o catalogo ===')
    conferir('cinquenta modelos de cirurgia', len(CIRURGIAS), 50)
    conferir('todos estao na lista do sistema',
             all(padrao.POR_SLUG.get(m['slug']) is m for m in CIRURGIAS), True)
    fora, codigos, cids = [], set(), set()
    for m in CIRURGIAS:
        try:
            conteudo = estrutura.normalizar(m['tipo'], m['conteudo'])
        except estrutura.ConteudoInvalido as exc:
            fora.append(f"{m['slug']}: {exc}")
            continue
        codigos |= {p['codigo'] for p in conteudo['procedimentos']}
        cids |= {cid.split(' — ')[0] for cid in conteudo['cids']}
    conferir('todos na forma', fora, [])
    tuss = set(ProcedureCode.objects.filter(release__status='active', code__in=codigos)
               .values_list('code', flat=True))
    conferir('todo codigo TUSS existe na tabela ativa', sorted(codigos - tuss), [])
    cid_ok = set(DiagnosisCode.objects.filter(release__status='active', code__in=cids)
                 .values_list('code', flat=True))
    conferir('todo CID existe no catalogo', sorted(cids - cid_ok), [])
    conferir('o codigo de monitorizacao hemodinamica nao aparece', '20202032' in codigos, False)
    conferir('o codigo inexistente do tumor intradural nao aparece', '30715359' in codigos, False)
    conferir('a monitorizacao neurofisiologica certa aparece', '20202040' in codigos, True)
    conferir('toda justificativa traz o roteiro a completar',
             all(estrutura.A_COMPLETAR in m['conteudo']['indicacao'] for m in CIRURGIAS), True)

    print('=== 2. a tela de emissao ===')
    pac = Patient.objects.create(
        tenant=tenant, full_name='PACIENTE ROTEIRO CIRURGIA', registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['pacientes'].append(pac.id)
    enc = Encounter.objects.create(
        tenant=tenant, patient=pac, physician_membership=medico, occurred_at=timezone.now(),
        status=EncounterStatus.IN_PROGRESS, kind=EncounterKind.STRUCTURED, plan_text='',
    )
    criados['atendimentos'].append(enc.id)
    url = reverse('modelos:emitir', args=[enc.id])
    chave = 's:cirurgia-artrodese-lombar-com-tlif'
    r = c.get(url, {'modelo': chave})
    html = r.content.decode()
    conferir('a tela abre', r.status_code, 200)
    conferir('codigos, OPME e hospitalares viram linhas',
             tuple(f'data-nd-linhas="{f}"' in html for f in ('procedimento', 'material', 'lista')),
             (True, True, True))
    conferir('o script das linhas entra na tela', 'modelos/linhas.js' in html, True)
    conferir('tres fornecedores com sugestoes',
             (html.count('name="s0-fornecedor_'), '<datalist' in html, 'Orthoneuro' in html), (3, True, True))
    conferir('os CIDs do modelo na escolha', 'label="CIDs compatíveis do modelo"' in html, True)
    conferir('a monitorizacao ja marcada', bool(re.search(r'name="s0-monitorizacao"[^>]*checked', html)), True)

    print('=== 3. a recusa ===')
    base = {
        'modelo': chave, 's0-emitir': 'on',
        's0-procedimentos': '30715016 Artrodese da coluna com instrumentação por segmento x2\n'
                            '20202040 Monitorização neurofisiológica intra-operatória',
        's0-materiais': '6 x Parafusos pediculares\n1 x Broca cortante 5mm',
        's0-carater': 'eletiva', 's0-regime': 'internacao', 'acao': 'papel',
    }
    r = c.post(url, {**base, 's0-indicacao': 'História: [completar]'})
    conferir('com [completar] a tela volta com o aviso', (r.status_code, '[completar]' in r.content.decode()),
             (400, True) if r.status_code == 400 else (200, True))
    conferir('  e nada foi emitido', MedicalDocument.objects.filter(encounter=enc).count(), 0)

    print('=== 4. a emissao completa ===')
    cid = 'M51.1 — Transtornos de discos lombares e de outros discos intervertebrais com radiculopatia'
    r = c.post(url, {
        **base,
        's0-indicacao': 'Lombociatalgia refratária com déficit motor em L5; RM com hérnia L4-L5.',
        's0-cid': cid,
        's0-fornecedor_1': 'Orthoneuro', 's0-fornecedor_2': 'SPI', 's0-fornecedor_3': 'Fornecedor Novo',
        's0-monitorizacao': 'on',
        's0-materiais_hospitalares': 'Caixa de laminectomia\nRadioscopia',
        's0-hemo_ch': '2', 's0-hemo_plasma': '0', 's0-hemo_plaquetas': '',
        's0-anestesia': 'geral', 's0-equipe_anestesia': 'particular', 's0-tempo_sala': '240',
        's0-uti': 'on', 's0-dias_uti': '1', 's0-dias_internacao': '4', 's0-local': 'Hospital Roteiro',
    })
    conferir('a solicitacao e emitida', r.status_code, 302)
    doc = MedicalDocument.objects.filter(encounter=enc).first()
    if doc:
        s = doc.content_snapshot
        conferir('  o CID escolhido do modelo', s.get('cid'), cid)
        conferir('  a quantidade mudada', s['procedimentos'][0]['quantidade'], 2)
        conferir('  os tres fornecedores', s.get('fornecedores'), ['Orthoneuro', 'SPI', 'Fornecedor Novo'])
        conferir('  monitorizacao, hospitalares e hemocomponentes',
                 (s.get('monitorizacao'), s.get('materiais_hospitalares'), s.get('hemo_ch'),
                  s.get('reserva_sangue')),
                 (True, ['Caixa de laminectomia', 'Radioscopia'], '2', True))
        conferir('  logistica', (s.get('equipe_anestesia'), s.get('tempo_sala'), s.get('dias_uti')),
                 ('particular', '240', '1'))
        conferir('  a lista de CIDs do modelo nao vai para o documento', 'cids' in s, False)
        pdf = texto_do_pdf(read_bytes(doc.pdf_attachment))
        conferir('  o PDF diz fornecedores, monitorizacao, hospitalares e hemocomponentes',
                 tuple(t in pdf for t in ('Orthoneuro', 'Monitorização neurofisiológica', 'Caixa de laminectomia',
                                          '2 CH', 'Particular', 'Sim, 1 dia(s)', '240')),
                 (True,) * 7)
        enc.refresh_from_db()
        conferir('  a conduta registra fornecedores e hemocomponentes',
                 ('Orthoneuro' in enc.plan_text, '2 CH' in enc.plan_text), (True, True))

    print('=== 5. o editor ===')
    r = c.post(reverse('modelos:copiar'), {'chave': chave})
    copia = ModeloDocumento.objects.filter(autor=medico.user).order_by('-created_at').first()
    if copia:
        criados['modelos'].append(copia.id)
    conferir('copiar cria o modelo do medico', copia is not None and copia.tipo == 'cirurgia', True)
    if copia:
        r = c.get(reverse('modelos:editar', args=[copia.id]))
        conferir('o editor abre com as linhas e os CIDs',
                 (r.status_code, 'data-nd-linhas="procedimento"' in r.content.decode(),
                  'name="cids"' in r.content.decode()), (200, True, True))
        iniciais = valores_iniciais_do_editor(copia.tipo, copia.conteudo, copia.nome)
        dados = {k: ('on' if v is True else v) for k, v in iniciais.items()
                 if v not in (None, False, '') and not isinstance(v, list)}
        dados.update(fornecedor_1='HMS', fornecedor_2='SPI', fornecedor_3='X-SAFE',
                     procedimentos=iniciais['procedimentos'].replace(
                         '30715016 Artrodese da coluna com instrumentação por segmento',
                         '30715016 Artrodese da coluna com instrumentação por segmento x3', 1))
        form = ModeloForm(dados, tipo='cirurgia')
        conferir('salvar sem mexer no resto e valido', form.is_valid(), True)
        r = c.post(reverse('modelos:editar', args=[copia.id]), dados)
        copia.refresh_from_db()
        conferir('a copia guarda os fornecedores', copia.conteudo.get('fornecedores'), ['HMS', 'SPI', 'X-SAFE'])
        conferir('  e a quantidade', copia.conteudo['procedimentos'][0]['quantidade'], 3)
        conferir('  e os CIDs e os hospitalares do modelo',
                 (len(copia.conteudo.get('cids') or []), copia.conteudo.get('materiais_hospitalares')),
                 (len(padrao.POR_SLUG['cirurgia-artrodese-lombar-com-tlif']['conteudo']['cids']),
                  padrao.POR_SLUG['cirurgia-artrodese-lombar-com-tlif']['conteudo']['materiais_hospitalares']))
        conferir('o do sistema continua igual',
                 padrao.POR_SLUG['cirurgia-artrodese-lombar-com-tlif']['conteudo']['procedimentos'][0]['quantidade'], 1)

    print('=== 6. o documento antigo ===')
    antigo = estrutura.normalizar('cirurgia', {
        'procedimentos': [{'codigo': '30715016', 'descricao': 'ARTRODESE', 'quantidade': 1}],
        'indicacao': 'x', 'reserva_sangue': True,
    })
    conferir('o conteudo sem os campos novos continua na forma',
             (antigo['fornecedores'], antigo['monitorizacao'], antigo['hemo_ch'], antigo['reserva_sangue']),
             ([], False, '', True))
finally:
    from pathlib import Path
    # Os PDFs (o emitido e o do rascunho) estão ligados ao paciente.
    anexos = Attachment.objects.filter(patient_id__in=criados['pacientes'])
    chaves = list(anexos.values_list('storage_key', flat=True))
    MedicalDocument.objects.filter(patient_id__in=criados['pacientes']).delete()
    anexos.delete()
    for chave_do_arquivo in chaves:
        if chave_do_arquivo and not Attachment.objects.filter(storage_key=chave_do_arquivo).exists():
            Path(chave_do_arquivo).unlink(missing_ok=True)
    Encounter.objects.filter(id__in=criados['atendimentos']).delete()
    Patient.objects.filter(id__in=criados['pacientes']).delete()
    ModeloDocumento.objects.filter(id__in=criados['modelos']).delete()

print()
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: os modelos de solicitacao de cirurgia, a emissao com o guia inteiro e o editor.')
