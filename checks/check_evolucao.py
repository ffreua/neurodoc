"""Serie temporal: o que o grafico diz, e o que ele nao pode dizer.

Grafico e a forma mais economica de mentir com dado verdadeiro. Os numeros
estao todos certos e a leitura sai errada -- e em prontuario a leitura
errada vira conduta.

O que este roteiro cobra, e onde da errado:

- **o eixo do tempo e proporcional a data real.** Distribuir os pontos por
  igual e o modo mais facil de desenhar e o mais facil de ler errado:
  transforma piora lenta em despencada, e recaida aguda em declinio
  gradual. A assercao mede a distancia entre os pontos no desenho e cobra
  que ela acompanhe a distancia entre as datas;
- **a escala pontuada usa o proprio dominio.** Barthel de 40 para 60 numa
  escala de 0 a 100 e isso. Apertar o eixo nos dados faria a mesma
  variacao ocupar o grafico inteiro;
- **escala incompleta nao entra.** Escore parcial nao e comparavel com
  escore inteiro, e plotar os dois na mesma linha inventa piora;
- **unidades diferentes nao formam uma serie.** Creatinina em mg/dL e em
  umol/L na mesma linha e um salto de duas ordens de grandeza desenhado
  como insuficiencia renal;
- **um ponto so nao e evolucao**, e nao aparece no seletor;
- **a fronteira entre clinicas**, como em toda tela clinica;
- **o sistema nao interpreta.** Nao existe "melhorou" nem "piorou" na
  tela: subir e melhorar numa Barthel e piorar numa NIHSS.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from clinical.models import (
    Encounter, EncounterKind, EncounterStatus, ExamResult, ExaminationDomain,
    ExaminationFinding, LabValue,
)
from clinical.series import ESCALA, MIN_PONTOS, desenhar, series_do_paciente
from patients.models import Observation, ObservationKind, Patient, RegistrationStage
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'encontros': [], 'pacientes': [], 'achados': [], 'labs': [], 'obs': [], 'resultados': []}


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:60} -> {obtido}')
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


def atendimento(paciente, dias_atras, dono=None, quem=None, status=EncounterStatus.FINALIZED):
    e = Encounter.objects.create(
        tenant=dono or tenant, patient=paciente, physician_membership=quem or vinculo,
        occurred_at=agora - timedelta(days=dias_atras), status=status,
        kind=EncounterKind.FREE_TEXT, free_text='Roteiro de evolucao.', plan_text='Roteiro.',
    )
    criados['encontros'].append(e.id)
    return e


def escala(encontro, codigo, total, completa=True, nome='Escala do Roteiro'):
    a = ExaminationFinding.objects.create(
        tenant=encontro.tenant, encounter=encontro,
        domain=ExaminationDomain.AXIS_SCALES, item_code=f'escala.{codigo}',
        numeric_value=Decimal(str(total)),
        value_json={'scale': codigo, 'total': total, 'complete': completa, 'name': nome},
    )
    criados['achados'].append(a.id)
    return a


def laboratorio(encontro, analito, valor, unidade='mg/dL', baixo=None, alto=None):
    resultado = ExamResult.objects.filter(encounter=encontro).first()
    if resultado is None:
        resultado = ExamResult.objects.create(
            tenant=encontro.tenant, encounter=encontro, patient=encontro.patient,
            name='Laboratorio do roteiro', performed_on=encontro.occurred_at.date(),
        )
        criados['resultados'].append(resultado.id)
    v = LabValue.objects.create(
        tenant=encontro.tenant, exam_result=resultado, analyte=analito,
        value_text=str(valor), numeric_value=Decimal(str(valor)), unit=unidade,
        reference_low=Decimal(str(baixo)) if baixo is not None else None,
        reference_high=Decimal(str(alto)) if alto is not None else None,
    )
    criados['labs'].append(v.id)
    return v


def chaves(paciente):
    return {s['chave']: s for s in series_do_paciente(ctx, paciente)}


try:
    print('\n1. O eixo do tempo e proporcional a data, e nao a ordem')
    # Tres medidas: dia 0, dia 10 e dia 370. Se o desenho distribuisse os
    # pontos por igual, as duas distancias seriam iguais -- e uma piora de
    # um ano pareceria ter acontecido na mesma velocidade de dez dias.
    desigual = novo_paciente('Roteiro Evolucao Tempo')
    escala(atendimento(desigual, 370), 'ROT', 10)
    escala(atendimento(desigual, 360), 'ROT', 20)
    escala(atendimento(desigual, 0), 'ROT', 30)

    serie = chaves(desigual)[f'{ESCALA}:ROT']
    conferir('tres pontos na serie', len(serie['pontos']), 3)
    d = desenhar(serie)
    primeiro, meio, ultimo = d['pontos']
    vao_curto = meio['x'] - primeiro['x']
    vao_longo = ultimo['x'] - meio['x']
    conferir('o intervalo de 10 dias e menor que o de 360',
             vao_curto < vao_longo, True)
    # 10 dias contra 360: a razao tem de ficar perto de 36, nao de 1.
    razao = vao_longo / vao_curto
    conferir('e a razao acompanha as datas (~36x, nao 1x)', 30 < razao < 42, True)
    conferir('o primeiro ponto nasce na origem do eixo', primeiro['x'], d['eixo_x'])
    conferir('e o ultimo fecha na borda', ultimo['x'], d['fim_x'])

    print('\n2. A escala pontuada usa o dominio dela, nao o dos dados')
    # Mesma serie, com e sem o dominio cadastrado da escala.
    apertado = desenhar(serie)
    honesto = desenhar(serie, escala_cadastrada=(0, 100))
    conferir('sem dominio, o eixo se aperta nos dados', apertado['maximo'] < 100, True)
    conferir('com dominio, o eixo vai ate o maximo da escala', honesto['maximo'], 100.0)
    conferir('e comeca no minimo dela', honesto['minimo'], 0.0)
    # A mesma variacao ocupa muito menos altura no eixo honesto. E o ponto
    # inteiro: e a diferenca entre "melhorou" e "melhorou 20 de 100".
    altura_apertada = apertado['pontos'][0]['y'] - apertado['pontos'][2]['y']
    altura_honesta = honesto['pontos'][0]['y'] - honesto['pontos'][2]['y']
    conferir('e a mesma variacao desenha menor no eixo completo',
             altura_honesta < altura_apertada, True)

    print('\n3. Escala incompleta nao entra na linha')
    parcial = novo_paciente('Roteiro Evolucao Parcial')
    escala(atendimento(parcial, 60), 'PAR', 40, completa=True)
    escala(atendimento(parcial, 30), 'PAR', 12, completa=False)
    escala(atendimento(parcial, 0), 'PAR', 44, completa=True)
    serie_parcial = chaves(parcial)[f'{ESCALA}:PAR']
    conferir('so as completas entram', len(serie_parcial['pontos']), 2)
    conferir('e o escore parcial nao aparece',
             12.0 in [p['valor'] for p in serie_parcial['pontos']], False)

    print('\n4. Unidades diferentes nao formam uma serie')
    unidades = novo_paciente('Roteiro Evolucao Unidade')
    laboratorio(atendimento(unidades, 60), 'Creatinina', 1.1, 'mg/dL')
    laboratorio(atendimento(unidades, 30), 'Creatinina', 1.3, 'mg/dL')
    laboratorio(atendimento(unidades, 10), 'Creatinina', 97, 'umol/L')
    laboratorio(atendimento(unidades, 5), 'Creatinina', 115, 'umol/L')
    achadas = chaves(unidades)
    creatininas = [c for c in achadas if c.startswith('lab:creatinina')]
    conferir('viram duas series, uma por unidade', len(creatininas), 2)
    for chave in creatininas:
        valores = [p['valor'] for p in achadas[chave]['pontos']]
        misturou = max(valores) / min(valores) > 10
        conferir(f'  {chave[:34]:34} nao mistura ordens de grandeza', misturou, False)

    print('\n5. Um ponto so nao e evolucao')
    solitario = novo_paciente('Roteiro Evolucao Um Ponto')
    laboratorio(atendimento(solitario, 10), 'Sodio', 140, 'mEq/L')
    conferir(f'com 1 ponto (minimo e {MIN_PONTOS}), o seletor fica vazio',
             len(series_do_paciente(ctx, solitario)), 0)
    laboratorio(atendimento(solitario, 2), 'Sodio', 138, 'mEq/L')
    conferir('com 2, aparece', len(series_do_paciente(ctx, solitario)), 1)

    print('\n6. A faixa de referencia vem do laudo e cabe no desenho')
    faixa = novo_paciente('Roteiro Evolucao Faixa')
    laboratorio(atendimento(faixa, 40), 'Potassio', 5.9, 'mEq/L', baixo=3.5, alto=5.0)
    laboratorio(atendimento(faixa, 10), 'Potassio', 6.4, 'mEq/L', baixo=3.5, alto=5.0)
    serie_faixa = [s for s in series_do_paciente(ctx, faixa) if 'potassio' in s['chave']][0]
    df = desenhar(serie_faixa)
    conferir('a faixa foi desenhada', df['faixa'] is not None, True)
    # Todos os valores estao ACIMA da referencia. Se o dominio ignorasse a
    # faixa, ela cairia fora do desenho e o grafico nao mostraria que o
    # paciente esta fora do normal.
    conferir('e o eixo desce ate a referencia mesmo com tudo acima dela',
             df['minimo'] <= 3.5, True)
    conferir('a faixa tem altura visivel', df['faixa']['altura'] >= 1.0, True)

    print('\n7. Serie constante nao vira linha em cima do eixo')
    plana = novo_paciente('Roteiro Evolucao Plana')
    o1 = Observation.objects.create(
        tenant=tenant, patient=plana, kind=ObservationKind.WEIGHT,
        numeric_value=Decimal('72.00'), unit='kg', observed_at=agora - timedelta(days=90),
    )
    o2 = Observation.objects.create(
        tenant=tenant, patient=plana, kind=ObservationKind.WEIGHT,
        numeric_value=Decimal('72.00'), unit='kg', observed_at=agora,
    )
    criados['obs'] += [o1.id, o2.id]
    serie_plana = series_do_paciente(ctx, plana)[0]
    dp = desenhar(serie_plana)
    conferir('o dominio abre folga', dp['maximo'] > dp['minimo'], True)
    conferir('a variacao e zero, e e dita como zero', dp['variacao'], 0.0)

    print('\n8. A fronteira entre clinicas')
    outra = Tenant.objects.exclude(id=tenant.id).filter(
        membership__status=MembershipStatus.ACTIVE,
    ).distinct().first()
    if outra is not None:
        vinculo_b = Membership.objects.filter(
            tenant=outra, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
        ).first()
        if vinculo_b is not None:
            de_fora = novo_paciente('Roteiro Evolucao Outra Clinica', dono=outra)
            escala(atendimento(de_fora, 30, dono=outra, quem=vinculo_b), 'ROT', 5)
            escala(atendimento(de_fora, 0, dono=outra, quem=vinculo_b), 'ROT', 9)
            conferir('o contexto da clinica A nao ve a serie da B',
                     len(series_do_paciente(ctx, de_fora)), 0)

    print('\n9. A tela: o sobreposto responde e nao interpreta')
    cliente = Client()
    cliente.force_login(vinculo.user)
    sessao = cliente.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()

    url = reverse('clinical:evolucao', args=[desigual.id])
    resposta = cliente.get(url)
    conferir('o fragmento responde', resposta.status_code, 200)
    html = resposta.content.decode()
    conferir('e e fragmento, nao pagina inteira', '<body' in html, False)
    conferir('desenha a linha', '<polyline' in html, True)
    conferir('avisa que o eixo e tempo real', 'tempo real' in html, True)
    # O sistema nao diz se subir e bom. Depende da escala.
    for palavra in ['melhorou', 'piorou', 'evolução favorável', 'agravamento']:
        if palavra in html.lower():
            falhas.append(f'a tela interpreta o grafico: "{palavra}"')
    conferir('nao interpreta o sentido da variacao',
             any(p in html.lower() for p in ['melhorou', 'piorou']), False)

    vazio = cliente.get(reverse('clinical:evolucao', args=[solitario.id]) + '?serie=lixo')
    conferir('serie inexistente cai na primeira, sem quebrar', vazio.status_code, 200)

    # A porta de entrada. Se o botao ou o modal sumirem do template, tudo
    # acima continua passando e o recurso deixa de existir para quem usa --
    # o defeito mais barato de cometer e o mais caro de perceber.
    linha_do_tempo = cliente.get(
        reverse('clinical:timeline', args=[desigual.id]),
    ).content.decode()
    conferir('a linha do tempo tem o botao Evolucao',
             'evolucao-modal' in linha_do_tempo, True)
    conferir('e o modal aponta para o fragmento',
             f'data-evolucao-url="{url}"' in linha_do_tempo, True)
    conferir('com o script que o carrega',
             'clinical/evolucao.js' in linha_do_tempo, True)

    print('\n10. O paciente sem nenhuma serie e avisado, e nao fica pendurado')
    # O caso mais comum: paciente acompanhado so em texto livre. Era aqui
    # que a tela ficava presa em "Montando o grafico..." para sempre --
    # nao porque o fragmento falhasse, mas porque ele **nunca era
    # buscado**: o `evolucao.js` escutava `show.bs.modal`, e esta casa nao
    # usa o JavaScript do Bootstrap para modal. O evento nunca era
    # disparado, e nada no console dizia isso.
    so_texto = novo_paciente('Roteiro Evolucao So Texto')
    atendimento(so_texto, 3)          # um atendimento, nenhuma medida
    vazio_resp = cliente.get(reverse('clinical:evolucao', args=[so_texto.id]))
    conferir('o fragmento responde mesmo sem serie', vazio_resp.status_code, 200)
    vazio_html = vazio_resp.content.decode()
    conferir('e avisa que nao ha o que acompanhar',
             'Ainda não há o que acompanhar' in vazio_html, True)
    conferir('dizendo de onde a serie viria',
             'escalas pontuadas' in vazio_html, True)
    conferir('e oferecendo fechar', 'data-bs-dismiss="modal"' in vazio_html, True)
    # `<polyline>` nao serve de prova: o icone do proprio estado vazio e um
    # polyline. O que so existe quando ha serie e o seletor de serie e o
    # rotulo do grafico -- e a assercao tem de olhar para o que e exclusivo
    # do comportamento, nao para o que se parece com ele.
    conferir('nao ha seletor de serie', 'data-nd-serie' in vazio_html, False)
    conferir('nem grafico desenhado',
             'aria-label="Evolução de' in vazio_html, False)
    conferir('nem tabela de valores', '<tbody>' in vazio_html, False)

    print('\n11. O modal avisa que abriu, e o grafico escuta o aviso')
    # A assercao estrutural que impede o defeito de voltar. Ela le os dois
    # arquivos porque o defeito era a **combinacao** deles: cada um estava
    # correto sozinho.
    from pathlib import Path as _Path

    base_dir = _Path(dj_settings.BASE_DIR)
    app_js = (base_dir / 'static' / 'duralux' / 'app.js').read_text(encoding='utf-8')
    evo_js = (base_dir / 'static' / 'clinical' / 'evolucao.js').read_text(encoding='utf-8')
    conferir('openModal dispara o evento da casa',
             "nd:modal-open" in app_js, True)
    conferir('e o grafico escuta esse evento',
             "nd:modal-open" in evo_js, True)
    conferir('com rede de seguranca contra ficar pendurado',
             'setTimeout' in evo_js and 'falhou' in evo_js, True)

    secretaria = Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['secretary'],
    ).select_related('user').first()
    outro_cliente = Client()
    outro_cliente.force_login(secretaria.user)
    s2 = outro_cliente.session
    s2['tenant_id'] = str(tenant.id)
    s2.save()
    conferir('a secretaria nao abre o grafico',
             outro_cliente.get(url).status_code in (403, 404), True)

finally:
    LabValue.objects.filter(id__in=criados['labs']).delete()
    ExamResult.objects.filter(id__in=criados['resultados']).delete()
    ExaminationFinding.objects.filter(id__in=criados['achados']).delete()
    Observation.objects.filter(id__in=criados['obs']).delete()
    Encounter.objects.filter(id__in=criados['encontros']).delete()
    n = Patient.objects.filter(id__in=criados['pacientes']).delete()[0]
    print(f'\n  limpeza: {n} objeto(s) de paciente e '
          f"{len(criados['encontros'])} atendimento(s) removidos")

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o eixo do tempo segue as datas, a escala usa o dominio dela,')
print('    a incompleta fica de fora e a tela mostra o numero sem interpreta-lo.')
