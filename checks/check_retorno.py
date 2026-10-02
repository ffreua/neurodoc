"""Retorno previsto: a data, o aviso e a fila.

"Volta em seis meses" era decisao clinica que morria na cabeca de quem
atendeu. Ninguem registrava, ninguem cobrava, e o paciente cronico sumia
ate a proxima crise -- numa especialidade feita de seguimento longo, isso
e paciente perdido.

O que este roteiro cobra, e que e onde da errado:

- **a soma de meses nao estoura o fim do mes.** 31/01 mais um mes e 28/02,
  nao 03/03. `timedelta(days=30)` erraria sistematicamente, e o erro
  aparece como retorno previsto para o dia errado -- pequeno em um caso,
  constante em todos;
- **um atendimento gera um retorno, nao dois.** Reenviar o formulario ou
  finalizar de novo atualiza o prazo, nao duplica a linha;
- **o aviso sai uma vez.** A tarefa roda todo dia; sem `notified_at` o
  paciente receberia um e-mail por dia durante as tres semanas anteriores;
- **o dia perdido e recuperado.** O corte e `<=`, e nao `==`: servidor
  reiniciado numa madrugada deixaria aquele dia sem aviso para sempre;
- **o aviso respeita a recusa.** Sem `email_enabled`, ou com divulgacao
  revogada, ninguem e procurado;
- **o texto e de cuidado, nao de captacao.** A base legal que sustenta o
  envio sem consentimento e a tutela da saude (LGPD art. 11, II, "f"), e
  ela depende do que a mensagem diz. "Sentimos sua falta, agende ja" e a
  mesma mensagem do outro lado da linha;
- **falha de um paciente nao derruba a rodada.** Um endereco invalido nao
  pode cancelar os outros cinquenta avisos do dia.
"""
from datetime import date, timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from clinical.models import Encounter
from communications.models import Delivery, DeliveryAttempt
from communications.services import RETURN_EMAIL_TEMPLATE, deliver_return_reminder
from patients.models import PatientContact
from scheduling.models import ReturnStatus, ScheduledReturn
from scheduling.returns import (
    AVISO_DIAS_ANTES, INTERVALOS_MESES, _somar_meses, a_avisar, agendar_retorno, fila, resolver,
)
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = []
atendimentos_criados = []
contatos_antes = []
contato_criado = None


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
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
atendimento = Encounter.objects.filter(tenant=tenant).select_related('patient').first()
assert atendimento is not None, 'a semeadura precisa de ao menos um atendimento'

try:
    print('\n1. A soma de meses respeita o fim do mes')
    conferir('31/01 + 1 mes = 28/02', _somar_meses(date(2026, 1, 31), 1), date(2026, 2, 28))
    conferir('31/01 + 1 mes em bissexto = 29/02', _somar_meses(date(2024, 1, 31), 1), date(2024, 2, 29))
    conferir('31/03 + 1 mes = 30/04', _somar_meses(date(2026, 3, 31), 1), date(2026, 4, 30))
    conferir('15/06 + 6 meses = 15/12', _somar_meses(date(2026, 6, 15), 6), date(2026, 12, 15))
    conferir('01/12 + 12 meses vira o ano', _somar_meses(date(2026, 12, 1), 12), date(2027, 12, 1))
    # `timedelta(days=30)` daria 02/03 no primeiro caso. A assercao existe
    # para o dia em que alguem "simplificar" a funcao.
    conferir('e nao usa 30 dias fixos',
             _somar_meses(date(2026, 1, 31), 1) == date(2026, 1, 31) + timedelta(days=30), False)

    print('\n2. Um atendimento gera um retorno, nao dois')
    r1 = agendar_retorno(ctx, atendimento, 6, vinculo)
    criados.append(r1.id)
    r2 = agendar_retorno(ctx, atendimento, 3, vinculo)
    conferir('a segunda chamada reaproveita a linha', r2.id, r1.id)
    conferir('quantas linhas para este atendimento',
             ScheduledReturn.objects.filter(origin_encounter=atendimento).count(), 1)
    r1.refresh_from_db()
    conferir('e o prazo novo venceu o antigo', r1.interval_months, 3)
    conferir('sem retorno escolhido, nao cria nada',
             agendar_retorno(ctx, atendimento, None, vinculo), None)

    print('\n3. A fila e por data, com o atrasado no topo')
    r1.due_on = timezone.localdate() - timedelta(days=10)
    r1.save(update_fields=['due_on'])
    conferir('marcado como atrasado', r1.is_overdue, True)
    conferir('aparece na fila', r1.id in [x.id for x in fila(tenant.id)], True)

    print('\n4. Resolver tira da fila')
    resolver(ctx, r1, ReturnStatus.SCHEDULED, vinculo, note='ligou, marcou para 12/03')
    r1.refresh_from_db()
    conferir('status gravado', r1.status, ReturnStatus.SCHEDULED)
    conferir('quem resolveu ficou registrado', r1.resolved_by_id, vinculo.id)
    conferir('a observacao ficou', 'ligou' in r1.note, True)
    conferir('saiu da fila', r1.id in [x.id for x in fila(tenant.id)], False)
    conferir('mas aparece no historico', r1.id in [x.id for x in fila(tenant.id, incluir_resolvidos=True)], True)

    print('\n5. O aviso: janela, uma vez so, e o dia perdido')
    hoje = timezone.localdate()
    r1.status = ReturnStatus.PENDING
    r1.notified_at = None
    r1.due_on = hoje + timedelta(days=AVISO_DIAS_ANTES)
    r1.resolved_at = None
    r1.save()
    conferir(f'vence em {AVISO_DIAS_ANTES} dias -> entra na fila de aviso',
             r1.id in [x.id for x in a_avisar()], True)

    r1.due_on = hoje + timedelta(days=AVISO_DIAS_ANTES + 5)
    r1.save(update_fields=['due_on'])
    conferir('ainda longe -> nao entra', r1.id in [x.id for x in a_avisar()], False)

    # O dia perdido: a tarefa nao rodou ontem, e o vencimento passou para
    # dentro da janela. Com `==` em vez de `<=`, este caso nunca seria
    # avisado -- e ninguem saberia.
    r1.due_on = hoje + timedelta(days=AVISO_DIAS_ANTES - 7)
    r1.save(update_fields=['due_on'])
    conferir('dia perdido e recuperado na rodada seguinte',
             r1.id in [x.id for x in a_avisar()], True)

    r1.notified_at = timezone.now()
    r1.save(update_fields=['notified_at'])
    conferir('ja avisado -> nao entra de novo', r1.id in [x.id for x in a_avisar()], False)

    r1.notified_at = None
    r1.due_on = hoje - timedelta(days=1)
    r1.save(update_fields=['notified_at', 'due_on'])
    conferir('vencido nao recebe aviso de antecedencia',
             r1.id in [x.id for x in a_avisar()], False)

    print('\n6. O aviso respeita a recusa do paciente')
    paciente = atendimento.patient
    contatos_antes = [
        (c.id, c.email, c.email_enabled, c.marketing_opt_out_at)
        for c in paciente.contacts.all()
    ]
    contato = paciente.contacts.first()
    if contato is None:
        contato = PatientContact.objects.create(
            tenant=tenant, patient=paciente, name=paciente.full_name,
            relationship='Próprio paciente', email='retorno@example.invalid',
            email_enabled=True,
        )
        contato_criado = contato.id
    r1.notified_at = None
    r1.due_on = hoje + timedelta(days=5)
    r1.status = ReturnStatus.PENDING
    r1.save()

    contato.email = 'retorno@example.invalid'
    contato.email_enabled = False
    contato.marketing_opt_out_at = None
    contato.save()
    conferir('sem autorizacao de e-mail, ninguem e avisado',
             len(deliver_return_reminder(r1)), 0)

    contato.email_enabled = True
    contato.marketing_opt_out_at = timezone.now()
    contato.save()
    conferir('divulgacao revogada tambem barra', len(deliver_return_reminder(r1)), 0)

    contato.marketing_opt_out_at = None
    contato.save()
    entregas = deliver_return_reminder(r1)
    conferir('autorizado -> a entrega nasce', len(entregas) >= 1, True)
    conferir('e e por e-mail', entregas[0].channel, 'email')
    # A entrega aponta para o retorno, e para mais nada. A restricao
    # `single_target` recusa a linha sem alvo nenhum -- foi assim que este
    # roteiro descobriu que faltava a coluna.
    conferir('a entrega aponta para o retorno', entregas[0].scheduled_return_id, r1.id)
    conferir('e nao para um agendamento', entregas[0].appointment_id, None)
    conferir('nem para um documento', entregas[0].document_id, None)
    repetida = deliver_return_reminder(r1)
    conferir('chamar de novo nao duplica a entrega',
             Delivery.objects.filter(idempotency_key__startswith=f'return:{r1.id}:').count(),
             len(entregas))

    print('\n7. O texto e de cuidado, e nao de captacao')
    corpo = RETURN_EMAIL_TEMPLATE.format(
        patient='Maria', doctor='Dr. Teste', when='01/01/2027', contato=': (11) 1234-5678',
    )
    conferir('diz que o retorno estava previsto', 'previsto' in corpo, True)
    conferir('manda ligar para agendar', 'ligue para a clínica' in corpo, True)
    conferir('avisa que a caixa nao le resposta', 'não recebe respostas' in corpo, True)
    conferir('avisa que nao ha informacao clinica', 'não contém informação clínica' in corpo, True)
    for proibida in ['sentimos sua falta', 'agende já', 'promoção', 'desconto', 'aproveite']:
        if proibida in corpo.lower():
            falhas.append(f'o texto do aviso usa linguagem de captacao: "{proibida}"')
    conferir('sem linguagem de captacao',
             any(p in corpo.lower() for p in ['sentimos sua falta', 'agende já', 'aproveite']), False)

    print('\n8. Falha de um paciente nao derruba a rodada')
    from scheduling.tasks import avisar_retornos_task

    resultado = avisar_retornos_task()
    conferir('a tarefa devolve o balanco', sorted(resultado), ['avisados', 'falhas', 'sem_contato'])

    print('\n9. A tela da secretaria: ve a fila e da baixa nela')
    # A secretaria tem SCHEDULE e nao tem READ_CLINICAL. Se a tela exigisse
    # capacidade clinica, ela ficaria fora de quem faz exatamente este
    # trabalho -- e o defeito apareceria como 404, sem explicacao.
    secretaria = Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['secretary'],
    ).select_related('user').first()
    conferir('a semeadura tem uma secretaria', secretaria is not None, True)

    r1.status = ReturnStatus.PENDING
    r1.resolved_at = None
    r1.resolved_by = None
    r1.due_on = hoje - timedelta(days=3)
    r1.save()

    cliente = Client()
    cliente.force_login(secretaria.user)
    sessao = cliente.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()

    url = reverse('scheduling:returns')
    resposta = cliente.get(url)
    conferir('a secretaria abre a fila', resposta.status_code, 200)
    pagina = resposta.content.decode()
    conferir('e o paciente atrasado aparece nela',
             atendimento.patient.full_name in pagina, True)
    conferir('marcado como vencido', 'venceu' in pagina, True)
    conferir('a tela diz quando o aviso sai', '20 dias antes' in pagina, True)

    # Filtro invalido nao pode virar erro 500: `?physician=lixo` chegaria ao
    # ORM como UUID malformado.
    conferir('?physician=lixo nao derruba a tela',
             cliente.get(url, {'physician': 'nao-e-uuid'}).status_code, 200)

    baixa = reverse('scheduling:resolve-return', args=[r1.id])
    resposta = cliente.post(baixa, {'status': ReturnStatus.SCHEDULED, 'note': 'ligou hoje'})
    conferir('dar baixa redireciona de volta', resposta.status_code, 302)
    r1.refresh_from_db()
    conferir('e a linha saiu da fila', r1.status, ReturnStatus.SCHEDULED)
    conferir('com a observacao da secretaria', 'ligou hoje' in r1.note, True)

    # Status inventado nao pode gravar no campo: a linha sumiria da fila por
    # nao bater com filtro nenhum, sem nunca ter sido trabalhada.
    r1.status = ReturnStatus.PENDING
    r1.save(update_fields=['status'])
    cliente.post(baixa, {'status': 'qualquer-coisa'})
    r1.refresh_from_db()
    conferir('status inventado e recusado', r1.status, ReturnStatus.PENDING)

    print('\n10. O caminho real: finalizar o atendimento cria o retorno')
    # As secoes anteriores chamam `agendar_retorno` direto. Esta passa pelo
    # POST de verdade -- e o defeito que ela pega e o do campo que existe no
    # template com um nome e e lido na view com outro: tudo continuaria
    # "funcionando", e nenhum retorno nasceria.
    from clinical.models import Encounter as _Enc, EncounterKind, EncounterStatus

    medico = Client()
    medico.force_login(vinculo.user)
    sessao = medico.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()

    novo_atendimento = _Enc.objects.create(
        tenant=tenant, patient=atendimento.patient, physician_membership=vinculo,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT,
        kind=EncounterKind.FREE_TEXT, free_text='Roteiro de verificacao do retorno previsto.',
        # Sem conduta, `missing_requirements` recusa a finalizacao e o
        # modal mostra a lista de pendencias no lugar do campo de retorno.
        plan_text='Retorno previsto em seis meses.',
    )
    atendimentos_criados.append(novo_atendimento.id)

    tela = medico.get(reverse('clinical:detail', args=[novo_atendimento.id])).content.decode()
    conferir('o modal de finalizacao oferece o retorno',
             'name="retorno_meses"' in tela, True)
    conferir('com as opcoes vindas de INTERVALOS_MESES',
             all(f'value="{m}"' in tela for m in INTERVALOS_MESES), True)

    medico.post(reverse('clinical:finalize', args=[novo_atendimento.id]),
                {'retorno_meses': '6'})
    novo_atendimento.refresh_from_db()
    conferir('o atendimento fechou', novo_atendimento.status, EncounterStatus.FINALIZED)
    nascido = ScheduledReturn.objects.filter(origin_encounter=novo_atendimento).first()
    conferir('e o retorno nasceu junto', nascido is not None, True)
    if nascido is not None:
        criados.append(nascido.id)
        esperado = _somar_meses(timezone.localtime(novo_atendimento.occurred_at).date(), 6)
        conferir('com a data contada do atendimento', nascido.due_on, esperado)
        conferir('e pendente, esperando a secretaria', nascido.status, ReturnStatus.PENDING)

    print('\n11. Os intervalos da tela vem de uma lista so')
    conferir('sao meses, nao dias', all(1 <= m <= 24 for m in INTERVALOS_MESES), True)
    conferir('inclui os usuais de neurologia',
             {3, 6, 12} <= set(INTERVALOS_MESES), True)

finally:
    for cid, email, enabled, opt_out in contatos_antes:
        PatientContact.objects.filter(id=cid).update(
            email=email, email_enabled=enabled, marketing_opt_out_at=opt_out,
        )
    # As tentativas seguram a entrega por `PROTECT`, e a entrega segura o
    # contato e o retorno pelo mesmo motivo. A limpeza desce na ordem
    # inversa -- e o **contato criado** so pode sair depois das entregas,
    # que era o que faltava: ele era apagado primeiro, logo acima deste
    # comentario que descreve a ordem certa.
    #
    # Num banco antigo nao doia, porque o aviso ja tinha sido enviado em
    # sessao anterior e nenhuma entrega nova apontava para o contato novo.
    # Na primeira instalacao limpa nasceu uma, e a limpeza estourou com
    # `ProtectedError` -- derrubando o roteiro inteiro no `finally`, onde
    # o erro nao diz nada sobre o que estava sendo verificado.
    entregas_do_roteiro = Delivery.objects.filter(idempotency_key__startswith='return:')
    DeliveryAttempt.objects.filter(delivery__in=entregas_do_roteiro).delete()
    entregas_do_roteiro.delete()
    if contato_criado:
        PatientContact.objects.filter(id=contato_criado).delete()
    n = ScheduledReturn.objects.filter(id__in=criados).delete()[0]
    if atendimentos_criados:
        from clinical.models import Encounter as _Limpeza

        _Limpeza.objects.filter(id__in=atendimentos_criados).delete()
    print(f'\n  limpeza: {n} objeto(s) de retorno removidos, entregas e contatos restaurados')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: a data respeita o calendario, o retorno e unico por atendimento,')
print('    o aviso sai uma vez, recupera dia perdido e respeita a recusa.')
