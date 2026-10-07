"""Intervalos pontuais na agenda, naturalidade e a ficha no atendimento.

Tres entregas pedidas juntas, e que se encontram numa so pergunta: o que
o sistema precisa saber sobre o dia e sobre a pessoa sem interromper
quem esta atendendo.

1. **Intervalo pontual na grade.** Existia `buffer_minutes`, que reserva
   minutos DEPOIS DE CADA atendimento -- a consulta que estourou nao
   empurra a seguinte. Nao servia para o almoco: a pausa de relogio cai
   num horario fixo, e em horario diferente a cada dia da semana.
   `ScheduleBlock` tambem nao servia: e bloqueio de **data**, e um
   almoco exigiria 52 linhas por ano.

2. **Naturalidade.** Nao existia. Entra com catalogo do IBGE sugerindo e
   texto livre aceitando -- porque quem nasceu fora do Brasil nao esta
   em lista de municipio brasileiro.

3. **A ficha numa gaveta**, durante o atendimento. O caminho para o
   endereco era abrir outra aba, ou sair do atendimento nao salvo.

A parte dificil, e o que este roteiro protege: a pausa precisa valer em
**todos** os caminhos -- a grade que a tela desenha, a lista de horarios
em que cabe uma consulta, e a validacao de quem tenta marcar. Os tres
passam por `open_intervals`, e e la que a subtracao mora. Um dia que
alguem some um quarto caminho sem passar por ela, a secao 2 reprova.
"""
from datetime import date, time, timedelta
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from scheduling.availability import (
    available_slots, day_grid, fits, open_intervals,
)
from scheduling.models import AvailabilityRule, RecurringBreak
from tenancy.models import Membership

failures = []
raiz = Path(dj_settings.BASE_DIR)


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


medico = Membership.objects.filter(tenant__slug='demo-clinica-a', roles__contains=['doctor']).first()
if medico is None:
    print('FALTA DADO: nenhum medico na clinica de demonstracao')
    raise SystemExit(1)

# Uma segunda-feira futura, para nao esbarrar em feriado nem em reserva.
dia = timezone.localdate() + timedelta(days=7)
while dia.weekday() != 0:
    dia += timedelta(days=1)

print('=== 1. a pausa recorta a janela do dia ===')
AvailabilityRule.objects.filter(physician_membership=medico, weekday=0).delete()
RecurringBreak.objects.filter(physician_membership=medico, weekday=0).delete()
regra = AvailabilityRule(
    tenant_id=medico.tenant_id, physician_membership=medico, weekday=0,
    local_start=time(8, 0), local_end=time(13, 0),
    starts_on=dia - timedelta(days=30), ends_on=None,
    slot_minutes=20, buffer_minutes=0,
)
regra.full_clean()
regra.save()

try:
    janelas = open_intervals(medico.id, dia)
    print('  sem pausa  :', [(timezone.localtime(a).strftime('%H:%M'),
                              timezone.localtime(b).strftime('%H:%M')) for a, b in janelas])
    confere(len(janelas) == 1, 'sem pausa, o dia e uma janela so', str(len(janelas)))

    pausa = RecurringBreak(
        tenant_id=medico.tenant_id, physician_membership=medico, weekday=0,
        local_start=time(11, 40), local_end=time(12, 0),
        starts_on=dia - timedelta(days=30), reason='Almoço',
    )
    pausa.full_clean()
    pausa.save()

    janelas = open_intervals(medico.id, dia)
    rotulos = [(timezone.localtime(a).strftime('%H:%M'),
                timezone.localtime(b).strftime('%H:%M')) for a, b in janelas]
    print('  com pausa  :', rotulos)
    confere(rotulos == [('08:00', '11:40'), ('12:00', '13:00')],
            'a pausa parte o dia em duas janelas, no horario exato', str(rotulos))

    print('=== 2. e vale nos tres caminhos, nao so na grade ===')
    # Esta e a secao que importa. A grade, a lista de horarios livres e a
    # validacao da reserva sao tres perguntas diferentes feitas pelo
    # mesmo usuario; se a pausa valesse so na primeira, a secretaria
    # veria o horario fechado e conseguiria marcar nele assim mesmo.
    celulas = day_grid(medico.id, dia)
    das_1140 = [
        c for c in celulas
        if timezone.localtime(c['start']).strftime('%H:%M') == '11:40'
    ]
    confere(bool(das_1140), 'a celula das 11:40 existe na grade')
    confere(all(c['status'] == 'blocked' for c in das_1140),
            'e aparece fechada', str([c['status'] for c in das_1140]))
    confere(all('Almoço' in (c['reason'] or '') for c in das_1140),
            'com o motivo escrito -- buraco sem motivo faz a secretaria ligar',
            str([c['reason'] for c in das_1140]))

    # `available_slots` devolve pares (inicio, fim); o que interessa
    # aqui e o inicio oferecido.
    livres = [
        timezone.localtime(inicio_slot).strftime('%H:%M')
        for inicio_slot, _fim_slot in available_slots(medico.id, dia, 20)
    ]
    confere('11:40' not in livres, 'o horario da pausa nao e oferecido como livre')
    confere('11:20' in livres and '12:00' in livres,
            'e os vizinhos continuam livres', str(livres[:20]))

    # Uma consulta de 40 min nao pode atravessar a pausa.
    import datetime as _dt

    inicio = timezone.make_aware(_dt.datetime.combine(dia, time(11, 20)))
    cabe, motivo = fits(medico.id, inicio, inicio + timedelta(minutes=40))
    print('  consulta de 40 min as 11:20 ->', cabe, '|', motivo)
    confere(not cabe, 'uma consulta nao atravessa a pausa', motivo)

    cabe, motivo = fits(medico.id, inicio, inicio + timedelta(minutes=20))
    confere(cabe, 'mas a de 20 min, que termina as 11:40, cabe', motivo)

    print('=== 3. a pausa so vale no dia da semana e na vigencia dela ===')
    terca = dia + timedelta(days=1)
    AvailabilityRule.objects.filter(physician_membership=medico, weekday=1).delete()
    regra_terca = AvailabilityRule(
        tenant_id=medico.tenant_id, physician_membership=medico, weekday=1,
        local_start=time(8, 0), local_end=time(13, 0),
        starts_on=dia - timedelta(days=30), slot_minutes=20,
    )
    regra_terca.full_clean()
    regra_terca.save()
    janelas = open_intervals(medico.id, terca)
    confere(len(janelas) == 1,
            'a pausa de segunda nao recorta a terca -- cada dia tem o seu horario',
            str(len(janelas)))

    # Vigencia: pausa encerrada ontem nao vale hoje.
    pausa.ends_on = dia - timedelta(days=1)
    pausa.save()
    confere(len(open_intervals(medico.id, dia)) == 1,
            'pausa encerrada deixa de recortar -- a agenda passada fica como foi')
    pausa.ends_on = None
    pausa.save()

    print('=== 4. o formulario recusa o intervalo que nao faz sentido ===')
    from scheduling.forms import WeeklyScheduleForm

    base = {
        'weekdays': ['0'], 'local_start': '08:00', 'local_end': '13:00',
        'slot_minutes': '20', 'buffer_minutes': '0',
        'starts_on': dia.isoformat(), 'horizon': '365',
    }

    def formulario(**extra):
        return WeeklyScheduleForm(dict(base, **extra))

    f = formulario(pausa_1_inicio='12:00', pausa_1_fim='11:00')
    confere(not f.is_valid() and 'pausa_1_fim' in f.errors,
            'fim antes do inicio e recusado', str(f.errors))

    f = formulario(pausa_1_inicio='12:00')
    confere(not f.is_valid() and 'pausa_1_fim' in f.errors,
            'meio intervalo e recusado -- gravar so o inicio nao recorta nada',
            str(f.errors))

    f = formulario(pausa_1_inicio='14:00', pausa_1_fim='15:00')
    confere(not f.is_valid() and 'pausa_1_inicio' in f.errors,
            'intervalo fora do atendimento e recusado em vez de gravado sem efeito',
            str(f.errors))

    f = formulario(pausa_1_inicio='11:00', pausa_1_fim='12:00',
                   pausa_2_inicio='11:30', pausa_2_fim='12:30')
    confere(not f.is_valid() and 'pausa_2_inicio' in f.errors,
            'dois intervalos sobrepostos sao recusados', str(f.errors))

    f = formulario(pausa_1_inicio='11:40', pausa_1_fim='12:00', pausa_1_motivo='Almoço',
                   pausa_2_inicio='09:30', pausa_2_fim='09:45', pausa_2_motivo='Café')
    confere(f.is_valid(), 'dois intervalos validos passam', str(f.errors))
    if f.is_valid():
        declaradas = f.pausas_declaradas()
        confere(len(declaradas) == 2, 'e os dois sao devolvidos', str(len(declaradas)))
        confere(declaradas[0]['inicio'] < declaradas[1]['inicio'],
                'em ordem de horario, e nao na ordem dos campos')

    # Sem nenhum intervalo o formulario continua valendo: e o caso comum.
    confere(formulario().is_valid(), 'publicar sem intervalo nenhum continua valendo')

    print('=== 5. publicar grava as pausas, e substituir as encerra ===')
    from scheduling.publishing import publish_weekly_schedule
    from tenancy.context import AccessContext
    import uuid as _uuid

    ctx = AccessContext(
        user_id=medico.user_id, tenant_id=medico.tenant_id, membership_id=medico.id,
        permissions=frozenset(), request_id=_uuid.uuid4(),
    )
    f = formulario(pausa_1_inicio='11:40', pausa_1_fim='12:00', pausa_1_motivo='Almoço')
    assert f.is_valid(), f.errors
    dados = dict(f.cleaned_data, pausas=f.pausas_declaradas())
    resultado = publish_weekly_schedule(ctx, medico, dados)
    confere(len(resultado['pausas']) == 1, 'publicar gravou a pausa',
            str(len(resultado['pausas'])))
    vigentes = RecurringBreak.objects.filter(
        physician_membership=medico, weekday=0, ends_on__isnull=True,
    ).count()
    confere(vigentes == 1, 'e ha exatamente uma em vigor na segunda', str(vigentes))

    resultado = publish_weekly_schedule(ctx, medico, dados)
    vigentes = RecurringBreak.objects.filter(
        physician_membership=medico, weekday=0, ends_on__isnull=True,
    ).count()
    confere(vigentes == 1,
            'publicar de novo substitui em vez de empilhar', str(vigentes))
finally:
    RecurringBreak.objects.filter(physician_membership=medico).delete()
    AvailabilityRule.objects.filter(physician_membership=medico, weekday__in=[0, 1]).delete()

print('=== 6. naturalidade ===')
from patients.models import Patient
from patients.naturalidade import PAIS_CHOICES, rotulo_do_pais

p = Patient.objects.first()
guardado = (p.birth_country, p.birth_city, p.birth_state)
try:
    p.birth_country, p.birth_city, p.birth_state = 'BR', 'Campinas', 'SP'
    confere(p.naturalidade == 'Campinas/SP', 'brasileiro sai como cidade/UF', p.naturalidade)
    p.birth_country, p.birth_city, p.birth_state = 'PT', 'Lisboa', ''
    confere(p.naturalidade == 'Lisboa, Portugal',
            'estrangeiro sai com o pais, e sem UF brasileira', p.naturalidade)
    p.birth_country, p.birth_city, p.birth_state = '', '', ''
    confere(p.naturalidade == '',
            'sem dado devolve vazio -- quem monta a tela decide como dizer "nao informado"',
            repr(p.naturalidade))
finally:
    p.birth_country, p.birth_city, p.birth_state = guardado

confere(rotulo_do_pais('BR') == 'Brasil', 'o codigo vira nome')
confere(rotulo_do_pais('ZZ') == 'ZZ',
        'codigo fora da lista devolve o proprio codigo, e nao vazio -- ficha '
        'antiga continua mostrando que ha um dado ali')
confere(PAIS_CHOICES[0][0] == '', 'nao informar e a primeira opcao')
confere(PAIS_CHOICES[1][0] == 'BR', 'e o Brasil vem logo depois, nao no meio do alfabeto')

from patients.forms import PatientForm

campos = PatientForm().fields
for nome in ('birth_country', 'birth_city', 'birth_state'):
    confere(nome in campos, f'{nome} esta no cadastro')
    confere(not campos[nome].required, f'{nome} nao e obrigatorio')
html = str(PatientForm()['birth_city'])
confere('nd-municipios' in html, 'a cidade esta ligada ao datalist do autocomplete')
confere('municipios/buscar' in html, 'e a URL da busca vai no proprio campo')

print('=== 7. o autocomplete nao impede quem nao esta no catalogo ===')
from catalogs.selectors import search_municipalities

# Menos de dois caracteres nao busca: uma letra traz mil linhas.
confere(search_municipalities('a') == [], 'uma letra nao dispara busca')
# Catalogo vazio nao pode derrubar a tela -- e o estado de uma
# instalacao que ainda nao rodou `import_municipios`.
confere(isinstance(search_municipalities('zzzzzz'), list),
        'termo sem resultado devolve lista, nunca excecao')
# E o campo continua sendo texto livre: o modelo aceita o que foi digitado.
p2 = Patient.objects.first()
anterior = p2.birth_city
p2.birth_city = 'Buenos Aires'
p2.full_clean(exclude=['tenant'])
confere(True, 'cidade fora do catalogo passa na validacao do modelo')
p2.birth_city = anterior

print('=== 8. a ficha na gaveta, durante o atendimento ===')
for nome in ('detail.html', 'detail_livre.html'):
    tela = Path(raiz, 'templates', 'clinical', nome).read_text(encoding='utf-8')
    confere('_gaveta_ficha.html' in tela, f'{nome}: a gaveta esta incluida')
    confere('nd-gaveta-ficha' in tela, f'{nome}: o botao aponta para ela')

gaveta = Path(raiz, 'templates', 'clinical', '_gaveta_ficha.html').read_text(encoding='utf-8')
confere('Naturalidade' in gaveta, 'a gaveta mostra a naturalidade')
for campo in ('Endereço', 'Contatos', 'Pagamento'):
    confere(campo in gaveta, f'e mostra {campo}')
# **Leitura.** Um formulario dentro da gaveta seria um formulario dentro
# da pagina do atendimento, e enviar um dos dois levaria o outro junto.
confere('<form' not in gaveta,
        'a gaveta nao tem formulario -- nada daqui escreve no atendimento')
confere('target="_blank"' in gaveta,
        'e a ficha completa abre em outra aba, em vez de navegar para fora '
        'do atendimento nao salvo')

js = Path(raiz, 'static', 'clinical', 'atendimento.js').read_text(encoding='utf-8')
confere('gavetaAberta' in js, 'o JS controla qual gaveta esta aberta')
confere("tecla === 'd'" in js, 'Alt+D abre a dos dados')
confere("tecla === 'p'" in js, 'e Alt+P continua abrindo a da consulta anterior')

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - intervalo recorta os tres caminhos, naturalidade grava, ficha abre sem sair.')
