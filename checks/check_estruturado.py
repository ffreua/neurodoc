"""A tela do prontuario estruturado: impressoes, trazer tudo, e ficar na aba.

Tres defeitos que tinham a mesma assinatura -- o servidor fazia a coisa
certa e a tela nao mostrava, ou mostrava e depois perdia o lugar:

1. **As impressoes nao eram desenhadas.** O campo existe no modelo e
   sempre esteve em `EncounterForm`, mas nenhuma aba do estruturado o
   renderizava. Pior que a ausencia: a conduta e as impressoes de uma
   consulta de texto livre sao oferecidas na consulta seguinte, e aceitar
   "Impressoes da consulta anterior" num atendimento estruturado **gravava
   o texto num campo que a tela nao mostrava**. O item saia da lista de
   pendencias, o banco guardava o texto, e o medico nao via nada. So
   reaparecia no resumo impresso -- que ja imprimia as impressoes do
   estruturado logo depois das hipoteses. O papel estava certo; a tela e
   que nao existia.

2. **Nao havia como trazer tudo.** O retorno de um paciente em uso de
   seis medicamentos chega com dez itens para revisar, e revisar quase
   sempre quer dizer aceitar. Dez cliques, dez recarregamentos e dez
   voltas para a primeira aba nao produzem cuidado: produzem um medico
   que para de usar o recurso.

3. **Salvar devolvia para a primeira aba.** `app.js::tabFromHash` reabre
   a aba cujo id esta no endereco, e varios redirecionamentos de sucesso
   saiam **sem** ancora -- "Salvar historia", "Salvar conduta",
   "Adicionar hipotese" e a revisao da consulta anterior. Em quatro das
   sete abas o trabalho aparecia salvo; nas outras, parecia ter sumido.
   O `#carry-forward` das recusas era pior: a ancora nao existia em
   template nenhum.

O que este roteiro cobra, e onde da errado:

- o campo de impressoes esta na pagina e **dentro da aba de hipoteses**,
  entre ela e a aba de conduta -- a posicao e a mesma do resumo impresso;
- o que se grava em impressoes volta na tela, e sai no resumo;
- o item "Impressoes da consulta anterior" aceito num estruturado
  **aparece**: e a assercao que teria pego o defeito 1;
- "Trazer tudo" aceita todos os pendentes de uma vez, aplica o efeito de
  cada tipo (texto, medicacao, hipotese), e **nao traz nada pela metade**
  -- a transacao e uma so;
- clicar de novo sem nada pendente nao e erro;
- atendimento finalizado recusa, e os itens continuam pendentes;
- cada envio volta para a aba de onde saiu, e um valor forjado no campo
  `aba` nao vira ancora nenhuma;
- **varredura do template**: todo formulario de `autosave` dentro de uma
  aba carrega o `aba` com o id **daquela** aba. Escrito como lista de
  tres nomes, a quarta aba nasceria sem -- que foi exatamente como as
  tres de hoje nasceram.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import re
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinical import carry_forward as cf
from clinical.models import (
    CarryForwardItem, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus,
    Medication, MedicationStatus, ReviewAction,
)
from patients.models import Patient
from tenancy.models import Membership, Tenant

falhas = []
criados = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:62} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant, user=medico)
paciente = (
    Patient.objects.filter(tenant=tenant).order_by('record_number').first()
)

cliente = Client()
cliente.force_login(medico)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

class Contexto:
    """O minimo que `carry_forward` le do contexto de acesso."""

    tenant_id = tenant.id
    user_id = medico.id
    membership_id = vinculo.id


contexto = Contexto()


def abrir(kind, **campos):
    e = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=vinculo,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT, kind=kind, **campos,
    )
    criados.append(e)
    return e


def tela(encounter):
    return cliente.get(f'/app/clinical/{encounter.id}/').content.decode()


def salvar(encounter, **dados):
    encounter.refresh_from_db()
    corpo = {'row_version': str(encounter.row_version)}
    corpo.update(dados)
    return cliente.post(f'/app/clinical/{encounter.id}/autosave/', corpo)


print('\n1. As impressoes existem na tela, e ficam na aba de hipoteses')
estruturado = abrir(EncounterKind.STRUCTURED, chief_complaint='Cefaleia ha 3 meses')
pagina = tela(estruturado)
conferir('o campo esta na pagina', 'id_impressions' in pagina, True)
posicoes = {
    'hipoteses': pagina.find('id="tab-hipoteses"'),
    'campo': pagina.find('id_impressions'),
    'conduta': pagina.find('id="tab-conduta"'),
}
print(f'  posicoes: {posicoes}')
conferir('e fica DENTRO da aba de hipoteses, antes da de conduta',
         posicoes['hipoteses'] < posicoes['campo'] < posicoes['conduta'], True)
conferir('com o rotulo escrito uma vez so na caixa',
         pagina.count('Salvar impressoes') + pagina.count('Salvar impressões'), 1)

resposta = salvar(estruturado, impressions='Enxaqueca sem aura, em bom controle.',
                  aba='tab-hipoteses')
estruturado.refresh_from_db()
conferir('o que se digita e gravado', estruturado.impressions,
         'Enxaqueca sem aura, em bom controle.')
conferir('e volta na tela', 'Enxaqueca sem aura, em bom controle.' in tela(estruturado), True)
impresso = cliente.get(f'/app/clinical/{estruturado.id}/resumo/').content.decode()
conferir('e sai no resumo impresso', 'Enxaqueca sem aura, em bom controle.' in impresso, True)
# Salvar impressoes nao pode tocar na historia: o autosave grava so o que
# chega, e esta e a propriedade que faz sete abas num formulario cada.
conferir('e salvar impressoes nao apaga a historia',
         estruturado.chief_complaint, 'Cefaleia ha 3 meses')

print('\n2. O que vem da consulta anterior chega a TELA, e nao so ao banco')
anterior = abrir(
    EncounterKind.FREE_TEXT,
    free_text='Retorno de rotina, sem queixas novas.',
    impressions='Quadro estavel em uso de topiramato.',
    plan_text='Manter topiramato 50 mg. Retorno em 6 meses.',
)
Medication.objects.create(
    tenant=tenant, encounter=anterior, name='Topiramato', dose='50 mg',
    frequency='1x a noite', status=MedicationStatus.IN_USE,
)
EncounterDiagnosis.objects.create(
    tenant=tenant, encounter=anterior, code_snapshot='G43.0',
    description_snapshot='Enxaqueca sem aura', rank=1,
)
anterior.status = EncounterStatus.FINALIZED
anterior.finalized_at = timezone.now()
anterior.finalized_by = vinculo
anterior.content_hash = anterior.compute_content_hash()
anterior.save()

destino = abrir(EncounterKind.STRUCTURED)
itens = cf.carry_forward(contexto, destino, anterior)
rotulos = sorted(cf.describe_item(i)['label'] for i in itens)
print(f'  oferecidos: {rotulos}')
conferir('as impressoes estao entre os itens oferecidos',
         'Impressões da consulta anterior' in rotulos, True)

impressoes = next(i for i in itens if i.field_path == 'impressions')
resposta = cliente.post(
    f'/app/clinical/{destino.id}/carry-forward/{impressoes.id}/review/',
    {'action': 'accepted'},
)
destino.refresh_from_db()
conferir('aceitar grava no atendimento', destino.impressions,
         'Quadro estavel em uso de topiramato.')
# A assercao que teria pego o defeito: estava gravado e invisivel.
conferir('E APARECE NA TELA do estruturado',
         'Quadro estavel em uso de topiramato.' in tela(destino), True)
conferir('a revisao volta para o cartao da consulta anterior',
         resposta.headers.get('Location', '').endswith('#carry-forward'), True)

print('\n3. Trazer tudo de uma vez')
pendentes = destino.carry_forward_items.filter(review_action=ReviewAction.PENDING).count()
print(f'  aguardando revisao: {pendentes}')
conferir('ha mais de um item pendente para o botao fazer sentido', pendentes > 1, True)
conferir('e o botao esta na tela', 'carry-forward/aceitar-tudo' in tela(destino), True)

resposta = cliente.post(f'/app/clinical/{destino.id}/carry-forward/aceitar-tudo/')
destino.refresh_from_db()
restantes = destino.carry_forward_items.filter(review_action=ReviewAction.PENDING).count()
conferir('nao sobrou nada pendente', restantes, 0)
conferir('a conduta veio', destino.plan_text, 'Manter topiramato 50 mg. Retorno em 6 meses.')
conferir('a medicacao veio',
         list(destino.medications.values_list('name', 'dose')), [('Topiramato', '50 mg')])
conferir('a hipotese veio',
         list(destino.diagnoses.values_list('code_snapshot', flat=True)), ['G43.0'])
conferir('e a trilha registrou',
         AuditEvent.objects.filter(
             action='clinical.carry_forward_accepted_all', object_id=destino.id,
         ).exists(), True)
conferir('o cartao sai da tela quando nao ha mais pendencia',
         'carry-forward/aceitar-tudo' in tela(destino), False)

# Clicar de novo nao e erro: quem recarregou a aba velha nao fez nada errado.
resposta = cliente.post(f'/app/clinical/{destino.id}/carry-forward/aceitar-tudo/')
conferir('clicar de novo sem pendencia nao quebra', resposta.status_code, 302)

print('\n4. Atendimento finalizado recusa, e os itens continuam pendentes')
fechado = abrir(EncounterKind.STRUCTURED)
cf.carry_forward(contexto, fechado, anterior)
antes = fechado.carry_forward_items.filter(review_action=ReviewAction.PENDING).count()
Encounter.objects.filter(id=fechado.id).update(
    status=EncounterStatus.FINALIZED, finalized_at=timezone.now(), finalized_by=vinculo,
)
fechado.refresh_from_db()
resposta = cliente.post(f'/app/clinical/{fechado.id}/carry-forward/aceitar-tudo/', follow=True)
depois = fechado.carry_forward_items.filter(review_action=ReviewAction.PENDING).count()
texto = resposta.content.decode()
conferir('recusa com a mensagem do adendo', 'Use um adendo' in texto, True)
conferir('e nenhum item foi consumido', (antes, depois), (antes, antes))
fechado.refresh_from_db()
conferir('e o atendimento fechado nao foi alterado', fechado.plan_text, '')

print('\n5. Cada envio volta para a aba de onde saiu')
for aba in ('tab-historia', 'tab-conduta', 'tab-hipoteses', 'tab-exame'):
    campo = {'tab-historia': {'chief_complaint': 'Cefaleia'},
             'tab-conduta': {'plan_text': 'Manter'},
             'tab-hipoteses': {'impressions': 'Estavel'},
             'tab-exame': {'neurological_exam_text': 'Sem alteracoes'}}[aba]
    resposta = salvar(estruturado, aba=aba, **campo)
    destino_url = resposta.headers.get('Location', '')
    conferir(f'salvar em {aba} volta para la', destino_url.endswith('#' + aba), True)

# Valor forjado nao vira ancora. O destino vai para o fragmento de uma URL
# de redirecionamento, e o que nao for identificador de painel e descartado
# em silencio -- a pessoa cai no topo, que e o comportamento de antes.
for forjado in ('tab-<script>', '../../evil', 'https://exemplo.ru', 'tab-' + 'a' * 80, ''):
    resposta = salvar(estruturado, aba=forjado, plan_text='Manter')
    destino_url = resposta.headers.get('Location', '')
    ok = destino_url.endswith(f'/app/clinical/{estruturado.id}/')
    print(f'  {"ok " if ok else "FALHA"}  aba={forjado[:24]!r:<28} -> {destino_url[-30:]!r}')
    if not ok:
        falhas.append(f'aba forjada {forjado!r} virou ancora: {destino_url}')

resposta = cliente.post(f'/app/clinical/{estruturado.id}/diagnoses/', {
    'code_snapshot': 'G43.0', 'description_snapshot': 'Enxaqueca sem aura',
    'certainty': 'suspected', 'rank': '1', 'physician_note': '',
})
conferir('acrescentar hipotese volta para a aba de hipoteses',
         resposta.headers.get('Location', '').endswith('#tab-hipoteses'), True)

print('\n6. A varredura: nenhum formulario de aba pode nascer sem dizer qual e')
caminho = Path(settings.BASE_DIR) / 'templates' / 'clinical' / 'detail.html'
html = caminho.read_text(encoding='utf-8')
# Cada painel comeca em `id="tab-X"` e termina onde o proximo comeca. Varrer
# o template, e nao a pagina renderizada, porque o que se quer impedir e a
# **aba nova** escrita sem o campo -- e uma aba nova com `{% if %}` pode nem
# aparecer na renderizacao do atendimento usado aqui.
paineis = [(m.group(1), m.start()) for m in re.finditer(r'id="(tab-[a-z-]+)"', html)]
paineis = [(nome, inicio) for nome, inicio in paineis
           if 'tab-pane' in html[max(0, inicio - 120):inicio]]
limites = [(nome, inicio, paineis[i + 1][1] if i + 1 < len(paineis) else len(html))
           for i, (nome, inicio) in enumerate(paineis)]
print(f'  paineis encontrados: {[nome for nome, _, _ in limites]}')
conferir('as sete abas foram encontradas', len(limites), 7)
sem_aba = []
for nome, inicio, fim in limites:
    trecho = html[inicio:fim]
    for forma in re.finditer(r'<form[^>]*>', trecho):
        resto = trecho[forma.start():]
        fecha = resto.find('</form>')
        corpo = resto[:fecha if fecha > 0 else len(resto)]
        if 'clinical:autosave' not in forma.group(0):
            continue
        if f'name="aba" value="{nome}"' not in corpo:
            sem_aba.append(nome)
conferir('todo formulario de autosave diz em que aba esta', sorted(set(sem_aba)), [])

parcial = (Path(settings.BASE_DIR) / 'templates' / 'clinical' / '_carry_forward.html'
           ).read_text(encoding='utf-8')
conferir('a ancora #carry-forward existe no template', 'id="carry-forward"' in parcial, True)
app_js = (Path(settings.BASE_DIR) / 'static' / 'duralux' / 'app.js').read_text(encoding='utf-8')
conferir('e quem reabre a aba pelo endereco continua existindo',
         'tabFromHash' in app_js, True)

print('\n=== limpeza ===')
ids = [e.id for e in criados]
CarryForwardItem.objects.filter(target_encounter_id__in=ids).delete()
CarryForwardItem.objects.filter(source_encounter_id__in=ids).delete()
Medication.objects.filter(encounter_id__in=ids).delete()
EncounterDiagnosis.objects.filter(encounter_id__in=ids).delete()
# `ClinicalAmendment.encounter` e PROTECT; nenhum adendo nasce aqui, mas a
# linha custa nada e o proximo que acrescentar uma secao nao descobre isso
# com um ProtectedError no fim da bateria.
from clinical.models import ClinicalAmendment
ClinicalAmendment.objects.filter(encounter_id__in=ids).delete()
# O recebivel: finalizar atendimento emite evento, e `finance.handlers` cria
# o recebivel daquele atendimento -- com FK PROTECT. Aqui a finalizacao e
# por `update()`, que nao emite evento, mas a secao 2 finaliza `anterior`
# pelo `save()`, pelo mesmo motivo.
from finance.models import FinancialAdjustment, Payment, Receivable
FinancialAdjustment.objects.filter(receivable__encounter_id__in=ids).delete()
Payment.objects.filter(receivable__encounter_id__in=ids).delete()
Receivable.objects.filter(encounter_id__in=ids).delete()
print(f'  {Encounter.objects.filter(id__in=ids).delete()[0]} objeto(s) removido(s)')

print()
if falhas:
    print(f'FALHAS ({len(falhas)}):')
    for falha in falhas:
        print('  -', falha)
    raise SystemExit(1)
print('OK: impressoes na aba de hipoteses e visiveis quando vem da consulta anterior,')
print('    "trazer tudo" em uma transacao, e cada envio voltando para a sua aba.')
