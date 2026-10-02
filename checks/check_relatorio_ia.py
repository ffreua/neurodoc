"""Relatorio do paciente escrito pela IA: o que nao pode dar errado.

Este e o unico recurso de IA do sistema cujo produto sai pela porta: vira
um documento assinado que o paciente entrega numa pericia. Tudo o que os
outros erram na tela, este erra em papel timbrado.

O que o roteiro cobra, e o defeito que cada assercao impede:

- **marcador de desidentificacao nao sobrevive.** O contexto vai ao modelo
  com o nome trocado por `[PACIENTE]`. Um rascunho que repita o marcador
  viraria um relatorio dizendo "[PACIENTE] evoluiu com hemiparesia". A
  guarda esta em dois lugares -- o esquema, para o que vem do modelo, e a
  aprovacao, para o que passou por um editor humano -- e as duas sao
  cobradas aqui;
- **a identificacao nao entra no contexto.** `montar_contexto` nao poe
  nome nem CPF: eles sao impressos pelo sistema no cabecalho do PDF;
- **vale a ultima palavra sobre o diagnostico.** Codigo refutado nao e
  doenca do paciente, e um relatorio que o liste afirma doenca que o
  proprio medico ja excluiu. A data que o relatorio precisa e a do
  registro **mais antigo**, nao a do mais recente;
- **dois relatorios do mesmo paciente nao colidem.** A chave de
  idempotencia para tarefa sem atendimento era so o paciente: o segundo
  pedido reaproveitaria a linha do primeiro e nao rodaria, e a tela
  mostraria o relatorio antigo como resposta ao pedido novo;
- **a trava de privacidade segue fechada por padrao**, e so se abre com a
  confirmacao explicita -- que nenhuma outra tarefa tem como passar;
- **o recorte e declarado.** Paciente com mais atendimentos que o teto
  gera relatorio parcial, e quem assina precisa saber disso;
- **a ponte cria rascunho, nunca documento emitido**, e so a partir de
  rascunho aprovado;
- **o texto editado na tela e o que vai para o documento.** Gravar o
  original e descartar a edicao do medico seria a pior falha possivel,
  porque e silenciosa;
- **a fronteira**: quem nao emite documento nao gera relatorio;
- **descartar apaga de verdade.** A primeira versao marcava o artefato
  como rejeitado e redirecionava de volta para a mesma tela, que seguia
  mostrando o rascunho inteiro; o segundo clique devolvia "Artifact
  already rejected" numa pagina em branco, em ingles. Agora o texto e o
  pedido somem, a trilha fica, e a tela volta ao prontuario -- inclusive
  no segundo clique, quando ja nao ha o que apagar.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pydantic import ValidationError

from ai import relatorio, services
from ai.context import AIAuthorization
from ai.deidentification import deidentify_text
from ai.models import AIArtifact, AIJob, AIJobKind, AIReviewState
from ai.privacy_policy import evaluate_privacy_policy
from ai.schemas import PatientReportArtifact
from clinical.models import (
    DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus,
)
from documents.models import Attachment, MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.models import Patient, RegistrationStage
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'pacientes': [], 'encontros': [], 'diagnosticos': [], 'jobs': [], 'documentos': []}


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:62} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()
ctx = AccessContext(
    user_id=vinculo.user_id, tenant_id=tenant.id, membership_id=vinculo.id,
    permissions=frozenset(vinculo.roles or []), request_id=None,
    tenant_status=tenant.status, capabilities=frozenset(),
)
agora = timezone.now()


def novo_paciente(nome, dono=None):
    p = Patient.objects.create(
        tenant=dono or tenant, full_name=nome,
        registration_stage=RegistrationStage.COMPLETE,
    )
    criados['pacientes'].append(p.id)
    return p


def atendimento(paciente, dias_atras, texto='Consulta do roteiro.', dono=None):
    e = Encounter.objects.create(
        tenant=dono or tenant, patient=paciente, physician_membership=vinculo,
        occurred_at=agora - timedelta(days=dias_atras), status=EncounterStatus.FINALIZED,
        kind=EncounterKind.FREE_TEXT, free_text=texto, plan_text='Manter conduta.',
    )
    criados['encontros'].append(e.id)
    return e


def diagnostico(encontro, codigo, certeza, descricao='Doenca do roteiro'):
    d = EncounterDiagnosis.objects.create(
        tenant=encontro.tenant, encounter=encontro, code_snapshot=codigo,
        description_snapshot=descricao, certainty=certeza, rank=1,
    )
    criados['diagnosticos'].append(d.id)
    return d


def autorizacao(paciente):
    return AIAuthorization(
        tenant_id=tenant.id, user_id=vinculo.user_id, membership_id=vinculo.id,
        patient_id=paciente.id, encounter_id=None,
    )


CHR = chr(10)

try:
    print(CHR + '1. O marcador de desidentificacao nao chega ao papel')
    # A saida do modelo passa pelo esquema antes de o artefato existir. Um
    # rascunho gravado e um rascunho que alguem pode aprovar sem reparar.
    base_valida = {
        'titulo': 'Relatorio medico',
        'secoes': [{'titulo': 'Quadro', 'texto': 'O paciente evoluiu com hemiparesia.'}],
        'limitations': 'Baseado no prontuario.',
        'requires_physician_review': True,
    }
    ok = PatientReportArtifact(**base_valida)
    conferir('o rascunho limpo e aceito', ok.secoes[0].texto.startswith('O paciente'), True)

    for marcador in ('[PACIENTE]', '[CPF]', '[NOME_MAE]'):
        ruim = dict(base_valida)
        ruim['secoes'] = [{'titulo': 'Quadro', 'texto': f'{marcador} evoluiu com hemiparesia.'}]
        recusou = False
        try:
            PatientReportArtifact(**ruim)
        except ValidationError:
            recusou = True
        conferir(f'  {marcador} no corpo e recusado', recusou, True)

    ruim_titulo = dict(base_valida)
    ruim_titulo['titulo'] = 'Relatorio de [PACIENTE]'
    recusou = False
    try:
        PatientReportArtifact(**ruim_titulo)
    except ValidationError:
        recusou = True
    conferir('  e no titulo tambem', recusou, True)

    conferir('a funcao que a guarda usa encontra o marcador',
             relatorio.marcadores_residuais('texto com [TELEFONE] no meio'), ['[TELEFONE]'])
    conferir('e nao inventa marcador em texto limpo',
             relatorio.marcadores_residuais('O paciente esta bem.'), [])

    print(CHR + '2. A identificacao nao entra no contexto que vai ao modelo')
    paciente = novo_paciente('ZEFERINO QUADROS DE ALMEIDA')
    paciente.cpf = '52998224725'
    paciente.save(update_fields=['cpf'])
    atendimento(paciente, 40, texto='Paciente relata cefaleia ha tres meses.')
    atendimento(paciente, 10, texto='Mantem queixa; iniciado tratamento.')

    contexto, refs, recorte = relatorio.montar_contexto(autorizacao(paciente), paciente)
    import json as _json

    bruto = _json.dumps(contexto, ensure_ascii=False)
    conferir('o nome do paciente nao esta no contexto', 'ZEFERINO' in bruto.upper(), False)
    conferir('nem o CPF', '52998224725' in bruto, False)
    conferir('mas a idade/sexo entram quando ha', isinstance(contexto['paciente'], dict), True)
    conferir('e cada atendimento vira uma fonte rastreavel', len(refs), 2)

    # E se o nome estiver escrito dentro do texto do atendimento, que e o
    # caso real, a desidentificacao o remove antes do envio.
    sujo = 'ZEFERINO QUADROS compareceu acompanhado.'
    conferir('nome escrito no texto e removido antes do envio',
             'ZEFERINO' in deidentify_text(sujo, paciente).upper(), False)

    print(CHR + '3. Vale a ultima palavra sobre cada diagnostico')
    # Confirmado em marco, refutado em agosto: nao e doenca do paciente.
    antigo = atendimento(paciente, 300)
    recente = atendimento(paciente, 5)
    diagnostico(antigo, 'G40.9', DiagnosisCertainty.CONFIRMED, 'Epilepsia')
    diagnostico(recente, 'G40.9', DiagnosisCertainty.REFUTED, 'Epilepsia')
    diagnostico(antigo, 'G43.0', DiagnosisCertainty.CONFIRMED, 'Enxaqueca')

    from ai.tools.clinical import get_patient_diagnoses

    vigentes, refutados = get_patient_diagnoses(autorizacao(paciente))
    codigos_vigentes = sorted(d['codigo'] for d in vigentes)
    conferir('o refutado sai dos vigentes', codigos_vigentes, ['G43.0'])
    conferir('e aparece a parte, como investigado e afastado',
             [d['codigo'] for d in refutados], ['G40.9'])
    enxaqueca = vigentes[0]
    conferir('a data e a do registro mais antigo, nao a do ultimo',
             enxaqueca['registrado_desde'],
             (agora - timedelta(days=300)).date().isoformat())

    print(CHR + '4. Dois relatorios do mesmo paciente nao colidem')
    job_a = services.create_job(
        ctx, AIJobKind.PATIENT_REPORT, 'INSS', patient_id=paciente.id,
        target_ref={'finalidade': 'inss', 'pedido': 'data do diagnostico',
                    'ref': relatorio.referencia_do_pedido('inss', 'data do diagnostico')},
    )
    job_b = services.create_job(
        ctx, AIJobKind.PATIENT_REPORT, 'Escola', patient_id=paciente.id,
        target_ref={'finalidade': 'escola_trabalho', 'pedido': 'limitacoes',
                    'ref': relatorio.referencia_do_pedido('escola_trabalho', 'limitacoes')},
    )
    criados['jobs'] += [job_a.id, job_b.id]
    conferir('pedidos diferentes geram jobs diferentes', job_a.id != job_b.id, True)

    job_a2 = services.create_job(
        ctx, AIJobKind.PATIENT_REPORT, 'INSS', patient_id=paciente.id,
        target_ref={'finalidade': 'inss', 'pedido': 'data do diagnostico',
                    'ref': relatorio.referencia_do_pedido('inss', 'data do diagnostico')},
    )
    conferir('o mesmo pedido reaproveita (duplo clique nao duplica)', job_a2.id, job_a.id)
    conferir('a confirmacao de risco muda a chave',
             relatorio.referencia_do_pedido('inss', 'x')
             != relatorio.referencia_do_pedido('inss', 'x|confirmado'), True)

    print(CHR + '5. A trava de privacidade segue fechada por padrao')
    texto_de_risco = 'historia de consanguinidade na familia'
    conferir('marcador de risco bloqueia',
             evaluate_privacy_policy(None, texto_de_risco).allowed, False)
    conferir('e o motivo diz qual marcador foi encontrado',
             'consanguinidade' in evaluate_privacy_policy(None, texto_de_risco).reason, True)
    conferir('a confirmacao do medico atravessa',
             evaluate_privacy_policy(None, texto_de_risco, risco_confirmado=True).allowed, True)
    conferir('texto sem marcador passa normalmente',
             evaluate_privacy_policy(None, 'cefaleia tensional').allowed, True)

    print(CHR + '6. O recorte do prontuario e declarado')
    conferir('paciente curto: o relatorio cobre tudo', recorte['completo'], True)
    conferir('  e diz quantos leu', recorte['atendimentos_lidos'] >= 2, True)

    muitos = novo_paciente('ANASTACIO LONGO DE ACOMPANHAMENTO')
    for dias in range(relatorio.TETO_DE_ATENDIMENTOS + 4):
        atendimento(muitos, dias + 1)
    _, _, recorte_longo = relatorio.montar_contexto(autorizacao(muitos), muitos)
    conferir('paciente longo: o relatorio e parcial', recorte_longo['completo'], False)
    conferir('  le ate o teto', recorte_longo['atendimentos_lidos'],
             relatorio.TETO_DE_ATENDIMENTOS)
    conferir('  e diz quantos existem', recorte_longo['atendimentos_totais'],
             relatorio.TETO_DE_ATENDIMENTOS + 4)

    print(CHR + '7. A ponte cria rascunho, e so a partir de rascunho aprovado')
    artefato = AIArtifact.objects.create(
        tenant=tenant, job=job_a, schema_version='v1', provider='roteiro', model='roteiro',
        prompt_version='v3',
        result={
            'titulo': 'Relatorio medico',
            'secoes': [{'titulo': 'Quadro', 'texto': 'O paciente tem enxaqueca desde 2024.'}],
            'limitations': 'Baseado no prontuario.',
            'disclaimer': 'Conteudo gerado por IA.',
        },
    )
    recusou = False
    try:
        relatorio.criar_rascunho_de_documento(artefato, vinculo, vinculo.user_id)
    except relatorio.RelatorioNaoAprovado:
        recusou = True
    conferir('rascunho pendente nao vira documento', recusou, True)

    artefato.review_state = AIReviewState.ACCEPTED
    artefato.save(update_fields=['review_state'])
    documento = relatorio.criar_rascunho_de_documento(artefato, vinculo, vinculo.user_id)
    criados['documentos'].append(documento.id)
    conferir('aprovado vira documento do tipo relatorio',
             documento.kind, MedicalDocumentKind.REPORT)
    conferir('e nasce como RASCUNHO, nao emitido',
             documento.status, MedicalDocumentStatus.DRAFT)
    conferir('sem numero, porque numero so sai na emissao', documento.document_number, '')
    conferir('sem atendimento: o relatorio e do historico', documento.encounter_id, None)
    conferir('com a etiqueta que liga ao rascunho da IA',
             documento.content_snapshot.get('ai_artifact_id'), str(artefato.id))
    conferir('e a finalidade fica registrada',
             documento.content_snapshot.get('ai_finalidade'), 'inss')
    conferir('o texto do relatorio e o das secoes',
             'enxaqueca desde 2024' in documento.content_snapshot['report_text'], True)

    print(CHR + '8. O texto editado na tela e o que vai para o documento')
    cliente = Client()
    cliente.force_login(vinculo.user)
    sessao = cliente.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()

    artefato2 = AIArtifact.objects.create(
        tenant=tenant, job=job_b, schema_version='v1', provider='roteiro', model='roteiro',
        prompt_version='v3',
        result={
            'titulo': 'Relatorio medico',
            'secoes': [{'titulo': '', 'texto': 'TEXTO ORIGINAL DA IA.'}],
            'limitations': 'Baseado no prontuario.',
        },
    )
    url_aprovar = reverse('ai:relatorio-aprovar', args=[artefato2.id])
    corrigido = 'TEXTO CORRIGIDO PELO MEDICO, que e o que vale.'
    resposta = cliente.post(url_aprovar, {'texto': corrigido})
    conferir('a aprovacao leva ao documento', resposta.status_code, 302)
    novo_doc = MedicalDocument.objects.filter(
        tenant=tenant, content_snapshot__ai_artifact_id=str(artefato2.id),
    ).first()
    conferir('o documento existe', novo_doc is not None, True)
    if novo_doc:
        criados['documentos'].append(novo_doc.id)
        conferir('e traz o texto do MEDICO',
                 'CORRIGIDO PELO MEDICO' in novo_doc.content_snapshot['report_text'], True)
        conferir('e nao o original da IA',
                 'TEXTO ORIGINAL DA IA' in novo_doc.content_snapshot['report_text'], False)
    artefato2.refresh_from_db()
    conferir('o artefato fica como editado, e nao como aceito',
             artefato2.review_state, AIReviewState.EDITED)

    print(CHR + '9. A guarda do marcador vale tambem para o que o medico cola')
    artefato3 = AIArtifact.objects.create(
        tenant=tenant, job=job_a, schema_version='v1', provider='roteiro', model='roteiro',
        prompt_version='v3',
        result={'titulo': 'Relatorio', 'secoes': [{'titulo': '', 'texto': 'ok'}],
                'limitations': 'x'},
    )
    resposta = cliente.post(
        reverse('ai:relatorio-aprovar', args=[artefato3.id]),
        {'texto': '[PACIENTE] evoluiu com hemiparesia.'},
    )
    conferir('texto colado com marcador e recusado', resposta.status_code, 403)
    conferir('e nenhum documento foi criado',
             MedicalDocument.objects.filter(
                 tenant=tenant, content_snapshot__ai_artifact_id=str(artefato3.id),
             ).exists(), False)
    resposta_vazia = cliente.post(reverse('ai:relatorio-aprovar', args=[artefato3.id]), {'texto': '  '})
    conferir('relatorio vazio tambem', resposta_vazia.status_code, 403)

    print(CHR + '10. A fronteira: quem nao emite documento nao gera relatorio')
    url_nova = reverse('ai:relatorio-novo', args=[paciente.id])
    conferir('o medico abre a tela', cliente.get(url_nova).status_code, 200)

    secretaria = Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['secretary'],
    ).select_related('user').first()
    if secretaria:
        outro = Client()
        outro.force_login(secretaria.user)
        s = outro.session
        s['tenant_id'] = str(tenant.id)
        s.save()
        conferir('a secretaria nao abre', outro.get(url_nova).status_code in (403, 404), True)
        conferir('nem o rascunho de outro',
                 outro.get(reverse('ai:relatorio-detalhe', args=[job_a.id])).status_code
                 in (403, 404), True)

    outro_tenant = Tenant.objects.exclude(id=tenant.id).first()
    if outro_tenant:
        alheio = novo_paciente('PACIENTE DE OUTRA CLINICA', dono=outro_tenant)
        conferir('paciente de outra clinica nao abre',
                 cliente.get(reverse('ai:relatorio-novo', args=[alheio.id])).status_code, 404)

    print(CHR + '11. O pedido vazio nao vira job')
    antes = AIJob.objects.filter(tenant=tenant, kind=AIJobKind.PATIENT_REPORT).count()
    resposta = cliente.post(url_nova, {'finalidade': 'inss', 'pedido': '   '})
    conferir('a tela recusa e explica', resposta.status_code, 400)
    conferir('e nenhum job foi criado',
             AIJob.objects.filter(tenant=tenant, kind=AIJobKind.PATIENT_REPORT).count(), antes)

    print(CHR + '12. As finalidades estao completas e em portugues')
    for f in relatorio.FINALIDADES:
        conferir(f'  {f.codigo}: tem destinatario e orientacao',
                 bool(f.destinatario and f.orientacao and f.rotulo), True)
    conferir('codigo desconhecido cai na livre',
             relatorio.finalidade('nao-existe').codigo, 'livre')
    conferir('e o prompt do relatorio proibe o marcador',
             '[PACIENTE]' in __import__('ai.graphs', fromlist=['x']).REPORT_PROMPT, True)

    print(CHR + '13. Descartar apaga de verdade, e volta ao prontuario')
    # O defeito que o medico encontrou no primeiro uso: rejeitar marcava o
    # artefato e **redirecionava de volta para a mesma tela**, que
    # continuava mostrando o rascunho inteiro. O segundo clique devolvia
    # "Artifact already rejected" numa pagina em branco.
    job_d = services.create_job(
        ctx, AIJobKind.PATIENT_REPORT, 'INSS', patient_id=paciente.id,
        target_ref={'finalidade': 'inss', 'pedido': 'para descartar',
                    'ref': relatorio.referencia_do_pedido('inss', 'para descartar')},
    )
    artefato_d = AIArtifact.objects.create(
        tenant=tenant, job=job_d, schema_version='v1', provider='roteiro', model='roteiro',
        prompt_version='v3',
        result={'titulo': 'Relatorio', 'secoes': [{'titulo': '', 'texto': 'Para descartar.'}],
                'limitations': 'x'},
    )
    url_descartar = reverse('ai:relatorio-descartar', args=[artefato_d.id])
    resposta = cliente.post(url_descartar, {'patient_id': str(paciente.id)})
    conferir('o descarte redireciona', resposta.status_code, 302)
    conferir('e volta ao prontuario do paciente',
             reverse('clinical:timeline', args=[paciente.id]) in resposta['Location'], True)
    conferir('o rascunho foi apagado',
             AIArtifact.objects.filter(id=artefato_d.id).exists(), False)
    conferir('e o pedido que o originou tambem',
             AIJob.objects.filter(id=job_d.id).exists(), False)

    # A trilha fica. O fato permanece; o texto clinico, nao.
    from audit.models import AuditEvent

    conferir('mas a trilha registra quem descartou',
             AuditEvent.objects.filter(
                 tenant_id=tenant.id, action='ai.artifact_discarded',
                 object_id=job_d.id,
             ).exists(), True)

    print(CHR + '14. O segundo clique nao da tela branca')
    repetido = cliente.post(url_descartar, {'patient_id': str(paciente.id)})
    conferir('clicar de novo redireciona, nao erra', repetido.status_code, 302)
    conferir('e vai para o mesmo lugar',
             reverse('clinical:timeline', args=[paciente.id]) in repetido['Location'], True)
    conferir('paciente ausente no formulario da 404, nao 500',
             cliente.post(url_descartar, {}).status_code, 404)
    conferir('e paciente mal formado tambem',
             cliente.post(url_descartar, {'patient_id': 'nao-e-uuid'}).status_code, 404)

    print(CHR + '15. O que ja virou documento nao se apaga')
    # Ali o `ai_artifact_id` e a trilha que liga o relatorio assinado ao
    # rascunho que o originou; apagar a outra ponta a romperia.
    recusou = False
    try:
        relatorio.descartar_rascunho(job_a, vinculo.user_id)
    except relatorio.RascunhoJaVirouDocumento:
        recusou = True
    conferir('o rascunho que virou relatorio e preservado', recusou, True)
    conferir('  e continua existindo', AIJob.objects.filter(id=job_a.id).exists(), True)

    print(CHR + '16. As mensagens de recusa falam portugues')
    from ai.review import AlreadyReviewed, _guard

    artefato_r = AIArtifact.objects.create(
        tenant=tenant, job=job_b, schema_version='v1', provider='roteiro', model='roteiro',
        prompt_version='v3', review_state=AIReviewState.REJECTED,
        result={'titulo': 'x', 'secoes': [], 'limitations': 'x'},
    )
    mensagem = ''
    try:
        _guard(artefato_r)
    except AlreadyReviewed as exc:
        mensagem = str(exc)
    conferir('a recusa do ja revisado esta em portugues',
             'já foi revisado' in mensagem, True)
    conferir('e nao em ingles', 'Artifact already' in mensagem, False)

finally:
    MedicalDocument.objects.filter(id__in=criados['documentos']).update(
        pdf_attachment=None, signed_pdf_attachment=None,
    )
    MedicalDocument.objects.filter(id__in=criados['documentos']).delete()
    Attachment.objects.filter(
        tenant=tenant, patient_id__in=criados['pacientes'],
    ).delete()
    AIArtifact.objects.filter(job_id__in=criados['jobs']).delete()
    AIJob.objects.filter(id__in=criados['jobs']).delete()
    EncounterDiagnosis.objects.filter(id__in=criados['diagnosticos']).delete()
    Encounter.objects.filter(id__in=criados['encontros']).delete()
    n = Patient.objects.filter(id__in=criados['pacientes']).delete()[0]
    print(f'{CHR}  limpeza: {n} objeto(s) removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print(CHR + 'OK: o marcador nao chega ao papel, o refutado nao vira doenca,')
print('    o recorte e declarado, e o que o medico edita e o que ele assina.')
