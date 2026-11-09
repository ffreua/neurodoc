"""O pedido do portal entra pelos caminhos do resto do sistema (2026-11-09).

O médico pediu uma receita de controle especial a si mesmo pelo portal e não
conseguiu emiti-la: a tela de atender desenhava só o formato e um texto
livre, ele escolheu o formato eletrônico do SNCR, e o servidor exigia os
itens estruturados que a tela não tinha — a recusa voltava como "Confira o
conteúdo do documento" sem campo marcado nenhum. O relatório pedido pelo
portal, por sua vez, não chegava ao relatório com apoio de IA. E a recusa sem
motivo devolvia a mesma tela, com o pedido ainda na fila, sem dizer por quê.

O que o roteiro cobra, e o defeito que cada parte impede:

1. a receita do pedido abre **no mesmo bloco** da tela de emissão, com os
   itens do SNCR preenchidos pelo que o paciente escreveu e no formato que a
   lista oficial indica (clonazepam na Notificação B, e não na RCE que o
   recusaria);
2. o envio incompleto **marca o campo** e não cria nada;
3. a recusa da lista oficial volta ao formulário **com o que foi digitado**;
4. o envio completo vira a receita eletrônica, com a marca de uso contínuo
   (booleana) inteira — ela derrubava a comparação da trilha com um 500 —,
   e dá o pedido como atendido;
5. com o SNCR desligado, nada muda: a impressa de controle especial;
6. a recusa **exige motivo**, dito antes do clique e marcado no campo;
7. a coluna "Por" da fila mostra quem respondeu (lia um campo inexistente);
8. o relatório do pedido abre na IA com o texto do paciente, o pedido vai
   **desidentificado** ao provedor, e aprovar o rascunho dá o pedido como
   atendido — o pedido que teve outro desfecho no meio fica como estava;
9. a tela de emissão de sempre continua com o bloco inteiro;
10. a fronteira: outra clínica e outro paciente não entram pelo id.

Tudo dentro de uma transação desfeita no fim: o provedor de IA nunca é
chamado (a tarefa sai em `on_commit`), e o banco volta como estava.
"""
import re
import secrets
from datetime import date

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from ai import services as ai_services
from ai.context import AIAuthorization
from ai.models import AIArtifact, AIJob, AIJobKind
from audit.models import AuditEvent
from documents import pedidos_do_portal
from documents.models import (
    DocumentRequest, DocumentRequestKind, DocumentRequestStatus, MedicalDocument,
)
from patients.models import Patient
from sncr import receita
from sncr.models import Configuracao
from tenancy.models import Membership, Tenant

falhas = []
CHR = chr(10)


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


tenant = Tenant.objects.get(slug='demo-clinica-a')
outro_tenant = Tenant.objects.get(slug='demo-clinica-b')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant, user=medico)


def cliente_de(usuario, dono=tenant):
    c = Client()
    c.force_login(usuario)
    s = c.session
    s['tenant_id'] = str(dono.id)
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


def paciente(dono=tenant):
    return Patient.objects.create(
        tenant=dono, full_name=f'PACIENTE PORTAL UNISSONO {secrets.token_hex(3).upper()}',
        birth_date=date(1980, 5, 1), cpf=cpf_valido(), street='Rua das Acácias', number='120',
        district='Jardim Paulista', city='São Paulo', state='SP', postal_code='01415000',
        sex_at_registration='female',
    )


def pedido(p, kind, payload):
    return DocumentRequest.objects.create(
        tenant=p.tenant, patient=p, kind=kind, requester_name=p.full_name,
        requester_is_patient=True, payload=payload, status=DocumentRequestStatus.RECEIVED,
        privacy_ack_at=timezone.now(), privacy_notice_version='2026-10-v2',
    )


def receita_pedida(p, *meds, kind=DocumentRequestKind.PRESCRIPTION_SPECIAL):
    return pedido(p, kind, {'medicacoes': [
        {'nome': nome, 'dose': dose, 'uso': uso} for nome, dose, uso in meds
    ]})


def selecionado(html):
    """A opção escolhida no seletor do formato da receita (e não noutro da página)."""
    bloco = re.search(r'<select[^>]*name="prescription_format".*?</select>', html, re.S)
    if bloco is None:
        return None
    m = re.search(r'<option value="([^"]+)"\s+selected', bloco.group(0))
    return m.group(1) if m else None


def detalhe(c, req):
    return c.get(reverse('documents:request-detail', args=[req.id]))


def acao(c, req, nome, dados):
    return c.post(reverse('documents:request-action', args=[req.id, nome]), dados)


def itens_post(formato, *linhas, **extra):
    dados = {'conteudo_revisado': '1', 'prescription_format': formato}
    for n, linha in enumerate(linhas, 1):
        for campo, valor in zip(receita.CAMPOS_DO_ITEM, linha):
            dados[f'item{n}_{campo}'] = valor
    dados.update(extra)
    return dados


def documentos_de(p):
    return MedicalDocument.objects.filter(tenant=tenant, patient=p)


class _Desfaz(Exception):
    pass


try:
    with transaction.atomic():
        config = Configuracao.carregar()
        config.ativo = True
        config.save()
        c = cliente_de(medico)

        print(CHR + '1. A receita do pedido abre no bloco da tela de emissão, com os itens do SNCR')
        p1 = paciente()
        r1 = receita_pedida(p1, ('Sertralina', '50 mg', '1 comprimido pela manhã'))
        html = detalhe(c, r1).content.decode()
        conferir('o formulário é o da tela de emissão (o JavaScript o acha)',
                 'id="medical-document-form"' in html and 'documents/medical_form.js' in html)
        conferir('os itens do SNCR estão na tela', 'name="item1_forma"' in html and 'data-nd-rx="sncr"' in html)
        conferir('o nome do paciente vira o medicamento 1', 'value="Sertralina"' in html)
        conferir('a dose vira a concentração', re.search(r'name="item1_concentracao"[^>]*value="50 mg"', html) is not None)
        conferir('o modo de usar vira a posologia', '1 comprimido pela manhã</textarea>' in html)
        conferir('controle especial com o SNCR ligado abre na receita eletrônica',
                 selecionado(html) == receita.SNCR_RCE, selecionado(html))
        conferir('o texto livre das impressas continua lá', 'name="prescription_text"' in html)

        lista_carregada = any(
            s['lista'] == 'B1' for s in receita.classificar_item('Clonazepam')['substancias']
        )
        conferir('a lista oficial da Portaria 344 está importada', lista_carregada)
        if lista_carregada:
            p_clona = paciente()
            r_clona = receita_pedida(p_clona, ('Clonazepam', '2 mg', '1 comprimido à noite'))
            sel = selecionado(detalhe(c, r_clona).content.decode())
            conferir('clonazepam (B1) abre na Notificação B, e não na RCE que o recusaria',
                     sel == receita.SNCR_NRB, sel)
            conferir('nomes de receituários diferentes não são resolvidos sozinhos',
                     receita.formato_sugerido(['Clonazepam', 'Sertralina']) is None)
        conferir('o que não é controlado não sugere formato',
                 receita.formato_sugerido(['Dipirona']) is None)
        r_simples = receita_pedida(p1, ('Dipirona', '500 mg', 'se dor'), kind=DocumentRequestKind.PRESCRIPTION_SIMPLE)
        sel = selecionado(detalhe(c, r_simples).content.decode())
        conferir('receita simples de algo livre continua simples', sel == 'simple', sel)
        if lista_carregada:
            # Levetiracetam é da C1: pedido como "simples", abre na RCE —
            # controlado nunca vai em receita simples (FAQ de Integração, P48).
            r_c1 = receita_pedida(p1, ('Keppra', '250 mg', '2x/dia'), kind=DocumentRequestKind.PRESCRIPTION_SIMPLE)
            sel = selecionado(detalhe(c, r_c1).content.decode())
            conferir('"simples" de um controlado (Keppra, C1) abre na RCE', sel == receita.SNCR_RCE, sel)
        muitos = receita_pedida(p1, *[(f'Remedio {n}', '1 mg', 'x') for n in range(5)])
        html_m = detalhe(c, muitos).content.decode()
        conferir('mais de 3 medicamentos: o aviso diz quantos ficaram de fora',
                 'Os 2 a mais estão' in html_m and 'name="item3_nome"' in html_m
                 and 'value="Remedio 3"' not in html_m)

        print(CHR + '2. Envio incompleto marca o campo e não cria nada')
        resp = acao(c, r1, 'rascunho', itens_post(
            receita.SNCR_RCE, ('Sertralina', '50 mg', '', '', '1 comprimido pela manhã')))
        html = resp.content.decode()
        conferir('volta 400 com a tela', resp.status_code == 400, resp.status_code)
        conferir('o erro está no campo do medicamento',
                 'Preencha o primeiro medicamento por inteiro' in html and 'is-invalid' in html)
        conferir('o que foi digitado continua na tela', 'value="Sertralina"' in html)
        r1.refresh_from_db()
        conferir('o pedido segue aberto', r1.is_open)
        conferir('nenhum documento foi criado', not documentos_de(p1).exists())

        if lista_carregada:
            print(CHR + '3. A recusa da lista oficial volta ao formulário com o que foi digitado')
            resp = acao(c, r_clona, 'rascunho', itens_post(
                receita.SNCR_RCE, ('Clonazepam', '2 mg', 'comprimido', '30 comprimidos', '1 comprimido à noite')))
            html = resp.content.decode()
            conferir('volta 400, sem redirecionar', resp.status_code == 400, resp.status_code)
            conferir('com a explicação da lista oficial', 'Notificação' in html)
            conferir('e o clonazepam ainda na tela', 'value="Clonazepam"' in html)
            r_clona.refresh_from_db()
            conferir('o pedido segue aberto', r_clona.is_open)
            conferir('nenhum documento', not documentos_de(p_clona).exists())

        print(CHR + '4. O envio completo vira a receita eletrônica e atende o pedido')
        resp = acao(c, r1, 'rascunho', itens_post(
            receita.SNCR_RCE,
            ('Sertralina', '50 mg', 'comprimido revestido', '60', '1 comprimido pela manhã'),
            ('Pregabalina', '75 mg', 'cápsula dura', '', '1 cápsula de 12 em 12 horas'),
            item2_uso_continuo='on',
        ))
        conferir('redireciona ao documento', resp.status_code == 302, resp.status_code)
        r1.refresh_from_db()
        doc = r1.resulting_document
        conferir('o pedido foi atendido com o documento',
                 r1.status == DocumentRequestStatus.FULFILLED and doc is not None)
        if doc is not None:
            snap = doc.content_snapshot or {}
            conferir('no formato eletrônico do SNCR', snap.get('prescription_format') == receita.SNCR_RCE,
                     snap.get('prescription_format'))
            itens = snap.get('itens') or []
            conferir('com os dois medicamentos estruturados',
                     [i.get('nome') for i in itens] == ['Sertralina', 'Pregabalina'])
            conferir('a quantidade por extenso', 'sessenta' in (itens[0].get('quantidade') or '') if itens else False)
            conferir('o uso contínuo chegou inteiro (booleano)',
                     len(itens) > 1 and itens[1].get('uso_continuo') is True
                     and itens[1].get('quantidade') == receita.MARCA_USO_CONTINUO)
            conferir('quem respondeu é o médico', r1.reviewed_by_id == vinculo.id)
            evento = AuditEvent.objects.filter(
                action='documents.portal_request_drafted', object_id=r1.id,
            ).first()
            conferir('a trilha diz que o médico revisou',
                     evento is not None and evento.integrity_metadata.get('edited_by_physician') is True)
        resp = acao(c, r1, 'rascunho', itens_post(
            receita.SNCR_RCE, ('Sertralina', '50 mg', 'comprimido', '60', '1 cp')))
        conferir('o segundo envio não cria outro documento', documentos_de(p1).count() == 1,
                 documentos_de(p1).count())

        print(CHR + '5. Com o SNCR desligado, a impressa de controle especial, como antes')
        config.ativo = False
        config.save()
        p5 = paciente()
        r5 = receita_pedida(p5, ('Sertralina', '50 mg', '1 comprimido pela manhã'))
        html = detalhe(c, r5).content.decode()
        conferir('abre na impressa de controle especial', selecionado(html) == 'special_control',
                 selecionado(html))
        conferir('sem o formato eletrônico no seletor', 'value="sncr_rce"' not in html)
        resp = acao(c, r5, 'rascunho', {
            'conteudo_revisado': '1', 'prescription_format': 'special_control',
            'prescription_text': 'Sertralina 50 mg — 1 comprimido pela manhã.',
        })
        r5.refresh_from_db()
        conferir('e o rascunho impresso nasce',
                 resp.status_code == 302 and r5.resulting_document is not None
                 and r5.resulting_document.content_snapshot.get('prescription_format') == 'special_control')
        config.ativo = True
        config.save()

        print(CHR + '6. A recusa exige motivo, dito antes e marcado no campo')
        p6 = paciente()
        r6 = receita_pedida(p6, ('Sertralina', '50 mg', '1 comprimido'))
        html = detalhe(c, r6).content.decode()
        conferir('o campo diz que é obrigatório', 'Motivo da recusa' in html and '(obrigatório)' in html)
        conferir('e o navegador barra o vazio',
                 re.search(r'<textarea[^>]*name="note"[^>]*required', html) is not None)
        for vazio in ('', '   '):
            resp = acao(c, r6, 'recusar', {'note': vazio})
            html = resp.content.decode()
            conferir(f'recusa com motivo {vazio!r}: 400 e a explicação no campo',
                     resp.status_code == 400 and 'Toda recusa precisa de um motivo' in html
                     and 'is-invalid' in html, resp.status_code)
        r6.refresh_from_db()
        conferir('o pedido segue na fila', r6.status == DocumentRequestStatus.RECEIVED)
        resp = acao(c, r6, 'recusar', {'note': 'Precisa de consulta para reavaliar a dose.'})
        r6.refresh_from_db()
        conferir('com motivo, recusa e volta à fila',
                 resp.status_code == 302 and r6.status == DocumentRequestStatus.DECLINED
                 and r6.review_note.startswith('Precisa de consulta'))

        print(CHR + '7. A fila diz quem respondeu')
        fila = c.get(reverse('documents:request-queue')).content.decode()
        nome = medico.get_full_name()
        conferir('a coluna "Por" traz o nome do médico',
                 f'<td class="fs-12 text-muted">{nome}</td>' in fila, nome)

        print(CHR + '8. O relatório do pedido vai à IA, desidentificado, e a aprovação o atende')
        p8 = paciente()
        r8 = pedido(p8, DocumentRequestKind.REPORT, {
            'finalidade': 'INSS / benefício / perícia',
            'conteudo': f'Desde quando tenho epilepsia. Sou {p8.full_name}, telefone 11 98888-7777.',
        })
        html = detalhe(c, r8).content.decode()
        url_ia = reverse('ai:relatorio-novo', args=[p8.id]) + f'?pedido_portal={r8.id}'
        conferir('a tela do pedido oferece redigir com IA', url_ia in html and 'Redigir com IA' in html)
        conferir('e mantém o caminho de escrever à mão', 'name="report_text"' in html)
        html = c.get(url_ia).content.decode()
        conferir('a tela da IA abre com o pedido vinculado',
                 f'name="pedido_portal" value="{r8.id}"' in html)
        conferir('com o texto do paciente na caixa', 'Desde quando tenho epilepsia' in html)
        conferir('e a finalidade do INSS escolhida',
                 re.search(r'value="inss"\s+checked', html) is not None)

        p_outro = paciente()
        r_outro = pedido(p_outro, DocumentRequestKind.REPORT, {'finalidade': 'Outro', 'conteudo': 'x'})
        html = c.get(reverse('ai:relatorio-novo', args=[p8.id]) + f'?pedido_portal={r_outro.id}').content.decode()
        conferir('o pedido de outro paciente não se vincula', 'name="pedido_portal"' not in html)
        html = c.get(reverse('ai:relatorio-novo', args=[p8.id]) + '?pedido_portal=nao-e-uuid').content.decode()
        conferir('id mal formado também não (e não quebra)', 'name="pedido_portal"' not in html)

        resp = c.post(reverse('ai:relatorio-novo', args=[p8.id]), {
            'finalidade': 'inss', 'pedido_portal': str(r8.id),
            'pedido': f'Data do diagnóstico. Paciente {p8.full_name}, fone 11 98888-7777.',
        })
        job = AIJob.objects.filter(tenant=tenant, patient=p8, kind=AIJobKind.PATIENT_REPORT).first()
        conferir('o pedido de relatório vira o job da IA', resp.status_code == 302 and job is not None)
        r8.refresh_from_db()
        conferir('o job sabe qual pedido atende',
                 job is not None and (job.target_ref or {}).get('pedido_portal') == str(r8.id))
        conferir('o pedido fica em revisão, ainda aberto',
                 r8.status == DocumentRequestStatus.IN_REVIEW and r8.is_open)
        conferir('a fila diz que a IA está nele',
                 'rascunho com IA em andamento' in c.get(reverse('documents:request-queue')).content.decode())
        if job is not None:
            conferir('a tela do pedido aponta o rascunho',
                     reverse('ai:relatorio-detalhe', args=[job.id]) in detalhe(c, r8).content.decode())
            autorizacao = AIAuthorization(
                tenant_id=tenant.id, user_id=vinculo.user_id, membership_id=vinculo.id,
                patient_id=p8.id, encounter_id=None,
            )
            _, _, extras, _ = ai_services._gather_patient_report_context(autorizacao, p8, job)
            ultimo = p8.full_name.split()[-1]
            conferir('o pedido vai ao provedor sem o nome do paciente',
                     ultimo not in extras['pedido'] and '[PACIENTE]' in extras['pedido'], extras['pedido'])
            conferir('nem o telefone', '98888' not in extras['pedido'])

            artefato = AIArtifact.objects.create(
                tenant=tenant, job=job, schema_version='v1', provider='roteiro', model='roteiro',
                prompt_version='v3',
                result={'titulo': 'Relatório médico',
                        'secoes': [{'titulo': '', 'texto': 'Epilepsia diagnosticada em 2019.'}],
                        'limitations': 'Baseado no prontuário.'},
            )
            html = c.get(reverse('ai:relatorio-detalhe', args=[job.id])).content.decode()
            conferir('o rascunho diz que atende ao pedido do portal', 'pedido do portal' in html)
            resp = c.post(reverse('ai:relatorio-aprovar', args=[artefato.id]),
                          {'texto': 'Epilepsia diagnosticada em 2019, revisado.'})
            r8.refresh_from_db()
            doc8 = r8.resulting_document
            conferir('aprovar dá o pedido como atendido com o relatório',
                     resp.status_code == 302 and r8.status == DocumentRequestStatus.FULFILLED
                     and doc8 is not None and doc8.content_snapshot.get('ai_artifact_id') == str(artefato.id))
            evento = AuditEvent.objects.filter(
                action='documents.portal_request_drafted', object_id=r8.id,
            ).first()
            conferir('a trilha diz que veio da IA',
                     evento is not None and evento.integrity_metadata.get('via_ia') is True)

        # O pedido que teve outro desfecho enquanto a IA escrevia.
        r9 = pedido(p8, DocumentRequestKind.REPORT, {'finalidade': 'Outro', 'conteudo': 'Relatório geral.'})
        c.post(reverse('ai:relatorio-novo', args=[p8.id]),
               {'finalidade': 'livre', 'pedido': 'Relatório geral.', 'pedido_portal': str(r9.id)})
        job9 = AIJob.objects.filter(tenant=tenant, target_ref__pedido_portal=str(r9.id)).first()
        acao(c, r9, 'recusar', {'note': 'Será feito em consulta.'})
        if job9 is not None:
            art9 = AIArtifact.objects.create(
                tenant=tenant, job=job9, schema_version='v1', provider='roteiro', model='roteiro',
                prompt_version='v3',
                result={'titulo': 'R', 'secoes': [{'titulo': '', 'texto': 'Texto.'}], 'limitations': 'x'},
            )
            resp = c.post(reverse('ai:relatorio-aprovar', args=[art9.id]), {'texto': 'Texto revisado.'})
            r9.refresh_from_db()
            conferir('o relatório sai, e o pedido recusado no meio continua recusado',
                     resp.status_code == 302 and r9.status == DocumentRequestStatus.DECLINED
                     and r9.resulting_document is None)
        conferir('marcar atendido recusa pedido já respondido',
                 pedidos_do_portal.marcar_atendido(r9, doc8, vinculo, medico.id, True) is False
                 if job is not None else True)

        print(CHR + '9. A tela de emissão de sempre continua com o bloco inteiro')
        html = c.get(f'/app/documents/patients/{p1.id}/medical/new/').content.decode()
        conferir('itens, confirmação e texto livre',
                 'item3_posologia' in html and 'classificacao_confirmada' in html
                 and 'data-nd-rx="sncr"' in html and 'name="prescription_text"' in html
                 and 'data-nd-doc-kind="report"' in html)

        print(CHR + '10. A fronteira')
        p_b = paciente(dono=outro_tenant)
        r_b = receita_pedida(p_b, ('Sertralina', '50 mg', '1 cp'))
        conferir('o pedido de outra clínica não abre', detalhe(c, r_b).status_code == 404,
                 detalhe(c, r_b).status_code)
        html = c.get(reverse('ai:relatorio-novo', args=[p8.id]) + f'?pedido_portal={r_b.id}').content.decode()
        conferir('nem se vincula ao relatório', 'name="pedido_portal"' not in html)
        secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
        sec = cliente_de(secretaria)
        p_sec = paciente()
        r_sec = receita_pedida(p_sec, ('Sertralina', '50 mg', '1 cp'))
        resp = acao(sec, r_sec, 'rascunho', itens_post(
            receita.SNCR_RCE, ('Sertralina', '50 mg', 'comprimido', '30', '1 cp')))
        r_sec.refresh_from_db()
        conferir('a secretária não atende pedido', resp.status_code in (403, 404) and r_sec.is_open,
                 resp.status_code)

        raise _Desfaz
except _Desfaz:
    print(CHR + '  (transação desfeita: nada do roteiro ficou no banco)')

if falhas:
    print()
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print(CHR + 'OK: o pedido do portal entra pela receita do SNCR e pelo relatório com IA, e a recusa pede motivo.')
