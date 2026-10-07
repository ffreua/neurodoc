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

# ------------------------------------------------------------------
# A grade deste medico e **fixture de outros roteiros**.
#
# Este roteiro apaga regras para montar os cenarios, e a primeira versao
# nao as devolvia: `check_mes_e_estatisticas`, que roda depois na ordem
# alfabetica, passou a reprovar com "ha um dia do mes anterior com grade
# publicada -> False". O roteiro nao estava errado sobre o que mede --
# estava errado sobre o que deixa para tras.
#
# Guardar os campos e nao os objetos: `delete()` zera o `pk` da
# instancia, e recriar a partir dela gravaria uma linha com id novo e
# `created_at` de hoje.
# ------------------------------------------------------------------
DIAS_QUE_O_ROTEIRO_MEXE = (0, 1, 3)
_grade_original = [
    {
        'weekday': r.weekday, 'local_start': r.local_start, 'local_end': r.local_end,
        'starts_on': r.starts_on, 'ends_on': r.ends_on, 'slot_minutes': r.slot_minutes,
        'buffer_minutes': r.buffer_minutes, 'appointment_type': r.appointment_type,
    }
    for r in AvailabilityRule.objects.filter(
        physician_membership=medico, weekday__in=DIAS_QUE_O_ROTEIRO_MEXE,
    )
]
_pausas_originais = [
    {
        'weekday': p_.weekday, 'local_start': p_.local_start, 'local_end': p_.local_end,
        'starts_on': p_.starts_on, 'ends_on': p_.ends_on, 'reason': p_.reason,
    }
    for p_ in RecurringBreak.objects.filter(
        physician_membership=medico, weekday__in=DIAS_QUE_O_ROTEIRO_MEXE,
    )
]


def devolver_a_grade():
    """Recoloca a grade como estava antes deste roteiro."""
    AvailabilityRule.objects.filter(
        physician_membership=medico, weekday__in=DIAS_QUE_O_ROTEIRO_MEXE,
    ).delete()
    RecurringBreak.objects.filter(
        physician_membership=medico, weekday__in=DIAS_QUE_O_ROTEIRO_MEXE,
    ).delete()
    for campos in _grade_original:
        AvailabilityRule.objects.create(
            tenant_id=medico.tenant_id, physician_membership=medico, **campos,
        )
    for campos in _pausas_originais:
        RecurringBreak.objects.create(
            tenant_id=medico.tenant_id, physician_membership=medico, **campos,
        )


print('=== 1. a pausa recorta a janela do dia ===')
print(f'  grade guardada para devolver: {len(_grade_original)} regra(s), '
      f'{len(_pausas_originais)} pausa(s)')
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

    print('=== 2b. a tarde RECOMECA quando a pausa acaba ===')
    # O defeito do primeiro teste real, em 07/10/2026. A cadencia corria
    # a partir do inicio da janela e a pausa apenas fechava a celula que
    # a tocasse: janela 08h40-18h40, celula de 40 min, almoco das 12h40
    # as 13h davam
    #
    #     ... 12h00, [12h40 fechada], 13h20, 14h00 ...
    #
    # -- a celula inteira das 12h40 perdida, E a tarde voltando vinte
    # minutos depois do fim do almoco. O esperado e a tarde recomecar
    # quando a pausa acaba.
    #
    # Montado com os numeros exatos do caso relatado, e nao com numeros
    # redondos: 08h40 e 12h40 so caem na cadencia porque a janela comeca
    # em 08h40, e e justamente esse encaixe que o defeito escondia.
    AvailabilityRule.objects.filter(physician_membership=medico, weekday=0).delete()
    RecurringBreak.objects.filter(physician_membership=medico, weekday=0).delete()
    regra_real = AvailabilityRule(
        tenant_id=medico.tenant_id, physician_membership=medico, weekday=0,
        local_start=time(8, 40), local_end=time(18, 40),
        starts_on=dia - timedelta(days=30), slot_minutes=40, buffer_minutes=0,
    )
    regra_real.full_clean()
    regra_real.save()
    pausa_real = RecurringBreak(
        tenant_id=medico.tenant_id, physician_membership=medico, weekday=0,
        local_start=time(12, 40), local_end=time(13, 0),
        starts_on=dia - timedelta(days=30), reason='Almoço',
    )
    pausa_real.full_clean()
    pausa_real.save()

    celulas = day_grid(medico.id, dia)
    livres_reais = [
        timezone.localtime(c['start']).strftime('%H:%M')
        for c in celulas if c['status'] in ('free', 'past', 'done')
    ]
    print('  manha :', livres_reais[:7])
    print('  tarde :', livres_reais[7:])
    esperado = [
        '08:40', '09:20', '10:00', '10:40', '11:20', '12:00',
        '13:00', '13:40', '14:20', '15:00', '15:40', '16:20', '17:00', '17:40',
    ]
    confere(livres_reais == esperado,
            'a manha vai ate 12h00 e a tarde recomeca as 13h00',
            f'veio {livres_reais}')
    confere('12:40' not in livres_reais,
            'as 12h40 nao sao oferecidas -- e quando a pausa comeca')
    confere('13:20' not in livres_reais,
            'e 13h20 tampouco: a tarde nao fica deslocada em 20 minutos')

    # A pausa aparece, com o horario real dela e com o motivo.
    da_pausa = [
        c for c in celulas
        if timezone.localtime(c['start']).strftime('%H:%M') == '12:40'
    ]
    confere(len(da_pausa) == 1, 'ha uma celula para a pausa', str(len(da_pausa)))
    if da_pausa:
        c = da_pausa[0]
        fim = timezone.localtime(c['end']).strftime('%H:%M')
        confere(c['status'] == 'blocked' and fim == '13:00',
                'fechada, das 12h40 as 13h00 -- o horario real, nao o da celula',
                f"{c['status']} ate {fim}")
        confere(c['reason'] == 'Almoço', 'com o motivo escrito', str(c['reason']))

    # E as celulas estao em ordem: a pausa foi acrescentada depois da
    # grade, e sem ordenar aparecia no rodape do dia.
    inicios = [c['start'] for c in celulas]
    confere(inicios == sorted(inicios), 'as celulas saem em ordem de horario')

    # O mesmo tem de valer para quem pergunta onde cabe uma consulta.
    livres_oferecidos = [
        timezone.localtime(i).strftime('%H:%M')
        for i, _f in available_slots(medico.id, dia, 40)
    ]
    confere('13:00' in livres_oferecidos and '13:20' not in livres_oferecidos,
            'a lista de horarios livres oferece 13h00, e nao 13h20',
            str(livres_oferecidos))

    AvailabilityRule.objects.filter(physician_membership=medico, weekday=0).delete()
    RecurringBreak.objects.filter(physician_membership=medico, weekday=0).delete()
    regra.pk = None
    regra.id = None
    regra.save()
    pausa.pk = None
    pausa.id = None
    pausa.save()

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
    devolver_a_grade()

print('=== 5b. remover a grade publicada hoje nao derruba a tela ===')
# O 500 do primeiro teste real, em 07/10/2026: `remove_rule` mandava a
# regra terminar ONTEM, e uma regra que comeca HOJE nao pode terminar
# ontem -- `full_clean` recusava e a tela devolvia 500. Pegava
# exatamente quem acabou de publicar e viu que errou, que e quem mais
# refaz.
from scheduling.publishing import remove_rule
from tenancy.context import AccessContext as _Ctx
import uuid as _uuid2

hoje = timezone.localdate()
ctx2 = _Ctx(
    user_id=medico.user_id, tenant_id=medico.tenant_id, membership_id=medico.id,
    permissions=frozenset(), request_id=_uuid2.uuid4(),
)

try:
    AvailabilityRule.objects.filter(physician_membership=medico, weekday=3).delete()
    RecurringBreak.objects.filter(physician_membership=medico, weekday=3).delete()

    nova = AvailabilityRule(
        tenant_id=medico.tenant_id, physician_membership=medico, weekday=3,
        local_start=time(8, 40), local_end=time(18, 40),
        starts_on=hoje, slot_minutes=40,
    )
    nova.full_clean()
    nova.save()
    pausa_nova = RecurringBreak(
        tenant_id=medico.tenant_id, physician_membership=medico, weekday=3,
        local_start=time(12, 40), local_end=time(13, 0), starts_on=hoje, reason='Almoço',
    )
    pausa_nova.full_clean()
    pausa_nova.save()

    try:
        desfecho = remove_rule(ctx2, medico, nova)
        confere(True, 'remover a grade publicada hoje nao levanta excecao')
        confere(desfecho == 'deleted', 'sem agendamento hoje, ela e apagada', str(desfecho))
    except Exception as exc:
        desfecho = None
        confere(False, 'remover a grade publicada hoje nao levanta excecao',
                f'{type(exc).__name__}: {exc}')

    confere(not AvailabilityRule.objects.filter(pk=nova.pk).exists(),
            'e a regra sai de fato')
    # A pausa acompanha: intervalo orfao voltaria a recortar a agenda no
    # dia em que alguem republicasse aquele dia sem substituir.
    confere(not RecurringBreak.objects.filter(pk=pausa_nova.pk).exists(),
            'a pausa daquele dia sai junto')

    # Regra antiga continua sendo ENCERRADA, e nao apagada: a agenda ja
    # atendida tem de continuar reconstruivel.
    antiga = AvailabilityRule(
        tenant_id=medico.tenant_id, physician_membership=medico, weekday=3,
        local_start=time(8, 0), local_end=time(12, 0),
        starts_on=hoje - timedelta(days=60), slot_minutes=40,
    )
    antiga.full_clean()
    antiga.save()
    desfecho = remove_rule(ctx2, medico, antiga)
    antiga.refresh_from_db()
    confere(desfecho == 'closed', 'regra que ja vigorou e encerrada', str(desfecho))
    confere(antiga.ends_on == hoje - timedelta(days=1),
            'com fim ontem -- o passado fica como foi', str(antiga.ends_on))
finally:
    # Sempre, inclusive se uma assercao acima estourar: a grade deste
    # medico e fixture de `check_mes_e_estatisticas`, que roda depois.
    devolver_a_grade()

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
confere('data-nd-municipio' in html, 'a cidade carrega o gancho do autocomplete')
confere('municipios/buscar' in html, 'e a URL da busca vai no proprio campo')
# `<datalist>` nativo nao abre em boa parte dos navegadores de celular --
# foi o que o primeiro teste em telefone mostrou. A lista e desenhada
# pelo proprio JavaScript.
confere('nd-municipios' not in html,
        'e nao depende mais do <datalist> nativo, que nao abre no celular')
html_uf = str(PatientForm()['birth_state'])
confere('data-nd-municipio-uf' in html_uf,
        'a UF carrega o gancho do filtro -- sem ele "Sao Jose" devolve dezenove',
        html_uf[:120])

# A ordem na tela: no celular os tres campos empilham, e a ordem vira a
# sequencia em que se preenche. Com a cidade antes da UF, a sugestao nao
# tem como filtrar.
tela_cadastro = Path(raiz, 'templates', 'patients', 'form.html').read_text(encoding='utf-8')
posicoes = {
    nome: tela_cadastro.find(f'field=form.{nome}')
    for nome in ('birth_country', 'birth_state', 'birth_city')
}
confere(posicoes['birth_country'] < posicoes['birth_state'] < posicoes['birth_city'],
        'a ordem na tela e pais, UF, cidade', str(posicoes))

js_nat = Path(raiz, 'static', 'patients', 'naturalidade.js').read_text(encoding='utf-8')
confere('nd-natur-lista' in js_nat, 'o JS desenha a propria lista')
confere('touchstart' in js_nat,
        'e fecha ao tocar fora -- `blur` dispara antes do clique e fecharia '
        'a lista sem deixar escolher')

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
