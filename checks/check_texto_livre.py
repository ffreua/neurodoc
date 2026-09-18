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
#: CPF do paciente descartavel da secao 13. Declarado aqui em cima porque a
#: escolha da cobaia precisa EXCLUI-LO: uma rodada que morra antes da limpeza
#: o deixa no banco, e `first()` o escolheria na rodada seguinte — os
#: atendimentos do roteiro nasceriam nele, e a limpeza esbarraria nas chaves
#: protegidas que o proprio roteiro criou. Ja aconteceu.
CPF_DESCARTAVEL = '52998224725'
# Ordem explicita: `first()` sem `order_by` deixa a escolha com o Postgres, e
# uma rodada passa a nao ser comparavel com a outra.
paciente = (
    Patient.objects
    .filter(tenant=tenant_a)
    .exclude(cpf=CPF_DESCARTAVEL)
    .order_by('created_at')
    .first()
)
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

print('=== 1b. TODA porta que abre atendimento oferece os dois tipos ===')
# O defeito que este bloco existe para impedir: os dois botoes foram postos
# na ficha do paciente e esquecidos na tela de prontuario. Quem entra pelo
# prontuario nao passa pela ficha — e uma porta sem a escolha nao parece uma
# porta faltando, parece que o texto livre nao existe.
#
# Confere as telas renderizadas (o que o medico ve) e, depois, o codigo-fonte
# dos templates (para uma porta nova nascer coberta).
for rotulo, url in [
    ('ficha do paciente', f'/app/patients/{paciente.id}/'),
    ('prontuario',        f'/app/clinical/patients/{paciente.id}/timeline/'),
]:
    corpo = cliente.get(url).content.decode()
    tem_estruturado = 'value="structured"' in corpo
    tem_livre = 'value="free_text"' in corpo
    print(f'  {rotulo:<20} estruturado={tem_estruturado} texto livre={tem_livre}')
    if not (tem_estruturado and tem_livre):
        failures.append(f'{rotulo}: a tela nao oferece os dois tipos de atendimento')

import os
from django.conf import settings

raizes = [d for conf in settings.TEMPLATES for d in conf.get('DIRS', [])]
portas = []
for raiz in raizes:
    for pasta, _, arquivos in os.walk(raiz):
        for nome in arquivos:
            if not nome.endswith('.html'):
                continue
            caminho = os.path.join(pasta, nome)
            with open(caminho, encoding='utf-8') as fh:
                fonte = fh.read()
            if "clinical:new" not in fonte:
                continue
            relativo = os.path.relpath(caminho, raiz)
            portas.append(relativo)
            if 'value="structured"' not in fonte or 'value="free_text"' not in fonte:
                failures.append(f'{relativo} abre atendimento sem oferecer os dois tipos')
print(f'  templates que abrem atendimento: {sorted(portas)}')
if not portas:
    failures.append('nenhum template abre atendimento — a busca por clinical:new falhou')

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

# A ordem da pagina e parte do pedido: texto -> medicacao -> impressoes e
# conduta -> CID, numa coluna so. Confere pela POSICAO de cada titulo no
# corpo, que e o que o olho encontra de cima para baixo.
ordem_pedida = ['Texto livre', 'Medicacoes em uso', 'Impressoes e conduta', 'Hipoteses (CID-10)']
import unicodedata


def sem_acento(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn'
    )


corpo_liso = sem_acento(corpo)
posicoes = [(titulo, corpo_liso.find(f'</span>{titulo}')) for titulo in ordem_pedida]
print('  ordem na pagina:', [t for t, _ in sorted(posicoes, key=lambda par: par[1])])
if any(pos < 0 for _, pos in posicoes):
    failures.append(f'titulo nao encontrado na tela: {[t for t, p in posicoes if p < 0]}')
elif [p for _, p in posicoes] != sorted(p for _, p in posicoes):
    failures.append('a tela de texto livre esta fora da ordem texto/medicacao/impressoes/CID')

# Os campos ficam FORA do <form> e pertencem a ele por `form=` (HTML5). Sem
# o atributo, o que se digita no texto nao e enviado -- e a tela pareceria
# salvar sem salvar.
for marca in ['id="nd-atendimento-livre"', 'form="nd-atendimento-livre"']:
    presente = marca in corpo
    print(f'  {marca:<34} {presente}')
    if not presente:
        failures.append(f'a tela de texto livre nao tem {marca}')
livre_form_attrs = corpo.count('form="nd-atendimento-livre"')
print(f'  campos amarrados ao formulario: {livre_form_attrs} (4 esperados: 3 campos + botao)')
if livre_form_attrs < 4:
    failures.append(f'so {livre_form_attrs} elemento(s) apontam para o formulario do atendimento')

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

print('=== 12. a ficha do paciente lista TODOS os atendimentos, com tipo e as duas datas ===')
# A ficha mostrava os cinco ultimos e so a data de abertura: ver o sexto
# obrigava a ir ao prontuario, e nada dizia se a evolucao era estruturada ou
# texto livre.
total = Encounter.objects.filter(tenant=tenant_a, patient=paciente).count()
corpo = cliente.get(f'/app/patients/{paciente.id}/').content.decode()
linhas = corpo.count('/app/clinical/')
print(f'  atendimentos do paciente: {total} | "Abrir" na ficha: >= {total}')
for marca in ['Texto livre', 'Estruturada', 'Abertura', 'Fechamento', 'em aberto',
              'ordenar=abertura', 'ordenar=fechamento', 'overflow-y: auto']:
    presente = marca in corpo
    print(f'  {marca:<20} {presente}')
    if not presente:
        failures.append(f'a ficha do paciente nao traz {marca!r}')
if 'Atendimentos recentes' in corpo:
    failures.append('a ficha ainda corta a lista em "Atendimentos recentes"')
# Cada atendimento tem de estar la, e nao so os cinco ultimos.
for e in Encounter.objects.filter(tenant=tenant_a, patient=paciente)[:12]:
    if f'/app/clinical/{e.id}/' not in corpo:
        failures.append('a ficha do paciente nao lista todos os atendimentos')
        break
for ordem in ('abertura', 'fechamento'):
    r = cliente.get(f'/app/patients/{paciente.id}/?ordenar={ordem}&desc=1')
    print(f"  ordenar={ordem}&desc=1 -> HTTP {r.status_code}")
    if r.status_code != 200:
        failures.append(f'a ficha nao ordena por {ordem} ({r.status_code})')
r = cliente.get(f'/app/patients/{paciente.id}/?ordenar=patient__cpf')
if r.status_code != 200:
    failures.append('ordenacao forjada na ficha do paciente quebrou a tela')

print('=== 13. contato informado no cadastro vai para a area de Contatos ===')
corpo = cliente.get('/app/patients/new/').content.decode()
for marca in ['id_contact_phone', 'id_contact_email', 'id_contact_accepts_messages']:
    presente = marca in corpo
    print(f'  {marca:<32} {presente}')
    if not presente:
        failures.append(f'o cadastro de paciente nao tem {marca}')

cpf_novo = '529.982.247-25'


def apagar_paciente_do_roteiro():
    """Apaga o paciente descartavel, descascando as chaves protegidas.

    Contato, atendimento e recebivel apontam para o paciente com PROTECT — a
    protecao existe para que apagar paciente nao leve embora, em silencio, o
    contato que autorizou receber documento e a consulta que ja foi faturada.
    Aqui e limpeza de roteiro: desce um nivel por vez ate o paciente sair.

    Enumerar os modelos a mao seria pior: cada relacao nova acrescentada ao
    paciente voltaria a quebrar esta limpeza, e a falha apareceria como um
    traceback no fim de um roteiro que passou.
    """
    from django.db.models.deletion import ProtectedError

    def apagar(consulta):
        for _ in range(15):
            try:
                return consulta.delete()
            except ProtectedError as erro:
                protegidos = list(erro.protected_objects)
                modelo = type(protegidos[0])
                apagar(modelo.objects.filter(pk__in=[o.pk for o in protegidos]))
        raise RuntimeError('nao consegui apagar o paciente do roteiro')

    apagar(Patient.objects.filter(tenant=tenant_a, cpf=CPF_DESCARTAVEL))

apagar_paciente_do_roteiro()
r = cliente.post('/app/patients/new/', {
    'full_name': 'Paciente Do Roteiro Livre', 'cpf': cpf_novo,
    'birth_date': '1980-05-04', 'sex_at_registration': 'female',
    'country': 'BR', 'payment_category': 'private',
    'referral_source': 'patient', 'marital_status': 'single',
    'contact_phone': '(11) 98765-4321', 'contact_email': 'roteiro@exemplo.local',
    'contact_accepts_messages': 'on',
}, follow=True)
novo = Patient.objects.filter(tenant=tenant_a, cpf=CPF_DESCARTAVEL).first()
print(f'  cadastro HTTP {r.status_code} | paciente criado: {novo is not None}')
if novo is None:
    failures.append(f'o cadastro com contato nao gravou o paciente ({r.status_code})')
else:
    contato = novo.contacts.first()
    if contato is None:
        failures.append('o contato informado no cadastro nao virou contato do paciente')
    else:
        print(f'  contato: {contato.name!r} | {contato.phone!r} | {contato.email!r} | '
              f'sms={contato.sms_enabled} email={contato.email_enabled}')
        if contato.phone != '11987654321':
            failures.append(f'o telefone guardou a mascara: {contato.phone!r}')
        if contato.email != 'roteiro@exemplo.local':
            failures.append('o e-mail do cadastro nao chegou ao contato')
        if not contato.name:
            failures.append('o contato do cadastro ficou sem nome')
        # Divulgacao NAO se deduz do contato dado no balcao: a LGPD exige
        # consentimento especifico, e a caixa do cadastro nao e essa.
        if contato.marketing_opt_in_at is not None:
            failures.append('o cadastro marcou consentimento de divulgacao sozinho')
        ficha = cliente.get(f'/app/patients/{novo.id}/').content.decode()
        if '11987654321' not in ficha and '98765-4321' not in ficha:
            failures.append('o contato do cadastro nao aparece na ficha')
    # Telefone com numero de digitos impossivel e recusado, e nao gravado torto.
    apagar_paciente_do_roteiro()
    r = cliente.post('/app/patients/new/', {
        'full_name': 'Telefone Curto', 'cpf': cpf_novo,
        'birth_date': '1980-05-04', 'sex_at_registration': 'female',
        'country': 'BR', 'payment_category': 'private',
        'referral_source': 'patient', 'marital_status': 'single',
        'contact_phone': '1234',
    })
    recusou = Patient.objects.filter(tenant=tenant_a, cpf=CPF_DESCARTAVEL).first() is None
    print(f'  telefone de 4 digitos recusado: {recusou}')
    if not recusou:
        failures.append('o cadastro aceitou telefone de 4 digitos')
    apagar_paciente_do_roteiro()

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
