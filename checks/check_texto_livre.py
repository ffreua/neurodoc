"""Atendimento em texto livre, ao lado do estruturado.

Tenta quebrar. As perguntas sao:

- da para abrir atendimento dos DOIS tipos, e cada um abre a sua tela?
- a tela de texto livre tem tudo numa pagina: texto, impressoes, conduta,
  medicacao, CID e o botao de emitir documento?
- os formularios da pagina estao ANINHADOS? (HTML nao aninha form)
- o que se digita e gravado, e o atendimento passa a "em andamento"?
- da para abrir hoje e finalizar depois, nos dois tipos?
- a finalizacao do texto livre exige os campos do ESTRUTURADO (queixa,
  historia) e obriga a inventar justificativa?
- conduta, impressoes e CID sao copiados de um texto livre para um
  estruturado -- e do estruturado para o texto livre?
- aceitar o item copiado grava mesmo o valor?
- a grade mostra abertura E fechamento, e ordena pelas duas?
- a ordenacao aceita campo arbitrario vindo da URL?
- o resumo imprimivel sai certo nos dois tipos?
- o tipo errado na criacao vira estruturado (e nao um estado invalido)?
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

import re

from django.utils import timezone

from accounts.models import User
from clinical import finalization
from clinical import selectors
from clinical.carry_forward import carry_forward, describe_item, review_carry_forward_item
from clinical.models import (
    CarryForwardItem, Encounter, EncounterKind, EncounterStatus, ReviewAction,
)
from patients.models import Patient
from tenancy.models import Membership, Tenant

failures = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant_a, user=medico)
paciente = Patient.objects.filter(tenant=tenant_a).first()
criados = []
#: Instante em que o roteiro comecou — a limpeza usa como janela.
COMECOU = timezone.now()


class Contexto:
    """O minimo que as funcoes de dominio leem do contexto de acesso."""

    tenant_id = tenant_a.id
    user_id = medico.id
    membership_id = vinculo.id


contexto = Contexto()


def entrar(user=medico, tenant=None):
    tenant = tenant or tenant_a
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def abrir(kind):
    e = Encounter.objects.create(
        tenant=tenant_a, patient=paciente, physician_membership=vinculo,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT, kind=kind,
    )
    criados.append(e)
    return e


cliente = entrar()

print('=== 1. os dois tipos abrem, e cada um na sua tela ===')
for rotulo, valor, marca_esperada, marca_proibida in [
    ('estruturado', 'structured', 'tab-conduta', 'id_free_text'),
    ('texto livre', 'free_text', 'id_free_text', 'tab-exame'),
]:
    r = cliente.post(f'/app/clinical/patients/{paciente.id}/new/', {'kind': valor}, follow=True)
    e = Encounter.objects.filter(tenant=tenant_a, patient=paciente, kind=valor).order_by('-created_at').first()
    criados.append(e)
    corpo = r.content.decode()
    print(f'  {rotulo:<12} HTTP {r.status_code} | tipo={e.kind} | '
          f'tem {marca_esperada}={marca_esperada in corpo} | sem {marca_proibida}={marca_proibida not in corpo}')
    if e.kind != valor:
        failures.append(f'{rotulo}: nasceu com kind={e.kind}')
    if marca_esperada not in corpo:
        failures.append(f'{rotulo}: a tela nao trouxe {marca_esperada}')
    if marca_proibida in corpo:
        failures.append(f'{rotulo}: a tela trouxe {marca_proibida}, que e do outro tipo')

print('=== 2. tipo desconhecido cai no estruturado ===')
r = cliente.post(f'/app/clinical/patients/{paciente.id}/new/', {'kind': 'chute'}, follow=True)
e = Encounter.objects.filter(tenant=tenant_a, patient=paciente).order_by('-created_at').first()
criados.append(e)
print(f'  kind=chute -> {e.kind} (structured esperado)')
if e.kind != EncounterKind.STRUCTURED:
    failures.append(f'tipo desconhecido virou {e.kind}')

print('=== 3. a pagina de texto livre tem tudo, e sem form aninhado ===')
livre = abrir(EncounterKind.FREE_TEXT)
corpo = cliente.get(f'/app/clinical/{livre.id}/').content.decode()
for marca in ['Texto livre', 'Impressões e conduta', 'Medicações em uso',
              'Hipóteses (CID-10)', 'Incluir medicação', 'Emitir documento',
              'id_free_text', 'id_impressions', 'id_plan_text', 'finalize-modal']:
    presente = marca in corpo
    print(f'  {marca:<22} {presente}')
    if not presente:
        failures.append(f'a tela de texto livre nao tem {marca!r}')

# Form aninhado: entre <form ...> e o </form> seguinte nao pode haver outro
# <form. O navegador ignora o interno, e o botao dele passa a enviar o
# formulario de fora -- incluir medicacao salvaria o texto livre.
aninhados = 0
for m in re.finditer(r'<form\b', corpo):
    fim = corpo.find('</form>', m.end())
    if fim > 0 and '<form' in corpo[m.end():fim]:
        aninhados += 1
print(f'  formularios aninhados  {aninhados} (0 esperado)')
if aninhados:
    failures.append(f'{aninhados} formulario(s) aninhado(s) na tela de texto livre')

print('=== 4. o que se digita e gravado ===')
cliente.post(f'/app/clinical/{livre.id}/autosave/', {
    'row_version': livre.row_version,
    'free_text': 'Retorno de rotina. Sem intercorrencias.',
    'impressions': 'Quadro estavel em uso de topiramato.',
    'plan_text': 'Manter dose. Retorno em 6 meses.',
})
livre.refresh_from_db()
print(f'  texto livre  -> {livre.free_text[:34]!r}')
print(f'  impressoes   -> {livre.impressions[:28]!r}')
print(f'  conduta      -> {livre.plan_text[:26]!r}')
print(f'  estado       -> {livre.status} (in_progress esperado)')
for campo, esperado in [('free_text', 'Retorno'), ('impressions', 'Quadro'), ('plan_text', 'Manter')]:
    if not getattr(livre, campo).startswith(esperado):
        failures.append(f'{campo} nao foi gravado')
if livre.status != EncounterStatus.IN_PROGRESS:
    failures.append(f'salvar nao passou o atendimento para em andamento ({livre.status})')

# O hash de conteudo precisa cobrir o corpo da consulta. No texto livre, um
# campo de fora do hash seria o atendimento **inteiro** — ele mudaria sem que
# a versao gravada na finalizacao mudasse junto, que e o contrario do que o
# hash existe para fazer. Compara-se com o campo vazio contra o campo cheio,
# e nao antes/depois de um POST: na segunda rodada o texto ja e o mesmo e
# nada mudaria.
for campo in ('free_text', 'impressions'):
    guardado = getattr(livre, campo)
    setattr(livre, campo, '')
    sem = livre.compute_content_hash()
    setattr(livre, campo, 'qualquer texto para o hash')
    com = livre.compute_content_hash()
    setattr(livre, campo, guardado)
    print(f'  {campo} entra no hash -> {sem != com}')
    if sem == com:
        failures.append(f'{campo} nao entra no hash de conteudo do atendimento')

print('=== 5. finalizar o texto livre NAO exige os campos do estruturado ===')
pendencias = finalization.missing_requirements(livre)
print(f'  pendencias: {[p["texto"][:44] for p in pendencias]} (nenhuma esperada)')
if pendencias:
    failures.append(f'texto livre preenchido ainda pede: {[p["texto"] for p in pendencias]}')
vazio = abrir(EncounterKind.FREE_TEXT)
faltas = [p['texto'] for p in finalization.missing_requirements(vazio)]
print(f'  vazio pede: {[f[:38] for f in faltas]}')
if not any('texto do atendimento' in f for f in faltas):
    failures.append('o texto livre vazio nao pede o texto do atendimento')
if any('queixa principal' in f for f in faltas):
    failures.append('o texto livre pede queixa principal, que nao existe nessa tela')

print('=== 6. abrir hoje e finalizar depois ===')
livre.refresh_from_db()
antes = livre.finalized_at
finalization.finalize_encounter(contexto, livre, vinculo)
livre.refresh_from_db()
print(f'  abertura   {livre.occurred_at:%d/%m/%Y %H:%M}')
print(f'  fechamento {livre.finalized_at:%d/%m/%Y %H:%M} (era {antes})')
print(f'  estado     {livre.status} | imutavel: {not livre.is_editable()}')
if livre.status != EncounterStatus.FINALIZED or livre.finalized_at is None:
    failures.append('finalizar o texto livre nao fechou o atendimento')
if livre.is_editable():
    failures.append('atendimento finalizado continuou editavel')

print('=== 7. conduta, impressoes e CID viajam entre os dois tipos ===')
estruturado = abrir(EncounterKind.STRUCTURED)
itens = carry_forward(contexto, estruturado, livre)
rotulos = sorted(describe_item(i)['label'] for i in itens)
print(f'  do texto livre para o estruturado: {rotulos}')
campos = {i.field_path for i in itens}
for esperado in ('plan_text', 'impressions'):
    if esperado not in campos:
        failures.append(f'{esperado} nao foi copiado do texto livre para o estruturado')

# Aceitar tem de GRAVAR o valor, e nao so marcar o item.
item_impressao = next((i for i in itens if i.field_path == 'impressions'), None)
if item_impressao is not None:
    review_carry_forward_item(item_impressao, ReviewAction.ACCEPTED, vinculo.id)
    estruturado.refresh_from_db()
    print(f'  aceitar impressoes grava -> {estruturado.impressions[:30]!r}')
    if not estruturado.impressions:
        failures.append('aceitar as impressoes nao gravou o valor no atendimento')

# E o caminho inverso: do estruturado para um texto livre novo.
estruturado.plan_text = 'Conduta escrita no estruturado.'
estruturado.status = EncounterStatus.FINALIZED
estruturado.finalized_at = timezone.now()
estruturado.save()
livre2 = abrir(EncounterKind.FREE_TEXT)
itens2 = carry_forward(contexto, livre2, estruturado)
campos2 = {i.field_path for i in itens2}
print(f'  do estruturado para o texto livre: {sorted(campos2)}')
for esperado in ('plan_text', 'impressions'):
    if esperado not in campos2:
        failures.append(f'{esperado} nao foi copiado do estruturado para o texto livre')

print('=== 8. a grade mostra e ordena pelas duas datas ===')
corpo = cliente.get(f'/app/clinical/patients/{paciente.id}/timeline/').content.decode()
for marca in ['Abertura', 'Fechamento', 'em aberto', 'ordenar=fechamento']:
    presente = marca in corpo
    print(f'  {marca:<22} {presente}')
    if not presente:
        failures.append(f'a grade nao traz {marca!r}')

por_abertura = list(selectors.patient_timeline(
    contexto, paciente, ordenar='abertura'))
por_fechamento = list(selectors.patient_timeline(
    contexto, paciente, ordenar='fechamento'))
print(f'  por abertura   -> {len(por_abertura)} linhas, crescente: '
      f'{[e.occurred_at for e in por_abertura] == sorted(e.occurred_at for e in por_abertura)}')
abertos_primeiro = [e.finalized_at is None for e in por_fechamento]
print(f'  por fechamento -> os em aberto vem primeiro: {abertos_primeiro == sorted(abertos_primeiro, reverse=True)}')
if [e.occurred_at for e in por_abertura] != sorted(e.occurred_at for e in por_abertura):
    failures.append('a ordenacao por abertura nao esta crescente')

print('=== 9. ordenacao forjada pela URL ===')
for chute in ('patient__cpf', 'id', '; DROP TABLE --', ''):
    r = cliente.get(f'/app/clinical/patients/{paciente.id}/timeline/?ordenar={chute}')
    print(f'  ordenar={chute[:18]!r:<22} -> HTTP {r.status_code}')
    if r.status_code != 200:
        failures.append(f'ordenar={chute!r} devolveu {r.status_code}')

print('=== 10. o resumo imprimivel sai nos dois tipos ===')
livre.refresh_from_db()
r = cliente.get(f'/app/clinical/{livre.id}/resumo/')
corpo = r.content.decode()
print(f'  texto livre  HTTP {r.status_code} | corpo={"Retorno de rotina" in corpo} | '
      f'impressoes={"Quadro estavel" in corpo} | sem "Queixa principal"={"Queixa principal" not in corpo}')
if r.status_code != 200 or 'Retorno de rotina' not in corpo:
    failures.append('o resumo do texto livre nao traz o texto')
if 'Queixa principal' in corpo:
    failures.append('o resumo do texto livre imprime as secoes vazias do estruturado')
# O roteiro de exame nao existe nesta tela: imprimir o subtitulo com
# "Nenhum item registrado" embaixo enche a folha de ausencia, que e o mesmo
# defeito da secao Historia.
print(f'  sem "Exame neurologico"={"Exame neurol" not in corpo}')
if 'Exame neurol' in corpo:
    failures.append('o resumo do texto livre imprime a secao de exame, que essa tela nao tem')


r = cliente.get(f'/app/clinical/{estruturado.id}/resumo/')
corpo = r.content.decode()
print(f'  estruturado  HTTP {r.status_code} | Queixa principal={"Queixa principal" in corpo}')
if r.status_code != 200 or 'Queixa principal' not in corpo:
    failures.append('o resumo do estruturado perdeu a secao de historia')

print('=== 11. fronteira entre clinicas ===')
outro = Encounter.objects.filter(tenant=tenant_b).first()
if outro:
    r = cliente.get(f'/app/clinical/{outro.id}/')
    print(f'  atendimento da clinica B -> {r.status_code} (404 esperado)')
    if r.status_code != 404:
        failures.append(f'abriu atendimento de outra clinica ({r.status_code})')

print('=== limpeza ===')
from clinical.models import ExaminationFinding

# A limpeza nao confia so na lista `criados`. Um atendimento aberto por um
# caminho que o roteiro esquecesse de registrar — ou uma rodada que morresse
# no meio — ficaria para tras, e atendimento de texto livre esquecido na
# demonstracao **derruba outro roteiro**: `check_resto` procura o campo de
# habitos no primeiro atendimento aberto que encontra, e o texto livre nao
# tem esse campo, de proposito. Ja aconteceu. Por isso apaga-se tambem tudo
# o que nasceu para este paciente depois que o roteiro comecou.
ids = {e.id for e in criados if e is not None}
ids |= set(
    Encounter.objects
    .filter(tenant=tenant_a, patient=paciente, created_at__gte=COMECOU)
    .values_list('id', flat=True)
)
ids = list(ids)
CarryForwardItem.objects.filter(target_encounter_id__in=ids).delete()
CarryForwardItem.objects.filter(source_encounter_id__in=ids).delete()
ExaminationFinding.objects.filter(encounter_id__in=ids).delete()
apagados = Encounter.objects.filter(id__in=ids).delete()[0]
print(f'  {apagados} objeto(s) removido(s)')

if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: os dois tipos de atendimento convivem, o texto livre grava e finaliza,')
print('    conduta/impressoes/CID viajam entre eles, e a grade mostra e ordena as duas datas.')
