"""Lista de espera da agenda (1.31): montar, ordenar, puxar para um horário.

O que este roteiro tenta quebrar, e onde a lista daria errado:

- **a ordem.** Incluir vai para o fim; subir e descer trocam com o vizinho
  **visível** (no recorte de um médico, a linha de outro médico não conta);
  "levar à posição" abre espaço; quem sai deixa a sequência 1, 2, 3 sem
  buraco. Número fora da faixa é trazido para dentro, e não vira erro;
- **um paciente aguarda uma vez só**, pelo serviço e pelo banco;
- **puxar no modal**: a consulta nasce pelo caminho de sempre, a espera se
  encerra ligada a ela e os de baixo sobem — e se o horário for recusado,
  a espera **continua** aguardando. Puxar de novo uma espera já encerrada
  (duas pessoas ao mesmo tempo) é recusado **sem** marcar segundo horário;
  espera de outro médico não entra na agenda deste; paciente trocado no
  formulário não leva a espera junto;
- **o caminho de sempre do modal não mudou**: marcar pela busca não mexe
  na espera, só avisa que o nome continua lá;
- **quem pode**: secretária e médico montam e reordenam (capacidade de
  agenda); outra clínica recebe 404 nas rotas e não vê nada nas opções;
  o banco recusa espera apontando paciente de outra clínica;
- **o pré-cadastro** pela lista passa pelo limite do plano, e recusada a
  inclusão não sobra paciente criado;
- só POST muda alguma coisa, e a trilha registra sem nome de paciente.

Tudo dentro de uma transação desfeita no fim: nada fica na base de
demonstração, e nenhuma mensagem sai (os eventos esperam o commit).
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from patients.models import Patient
from scheduling import espera
from scheduling.models import Appointment, AppointmentStatus, EsperaStatus, PacienteEmEspera
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.get(slug='demo-clinica-b')
medicos = list(Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').order_by('id'))
medico = medicos[0]
secretaria = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['secretary'],
).select_related('user').first()
assert secretaria is not None, 'a semeadura precisa de uma secretaria na Clinica Demo A'
vinculo_b = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE).first()


def contexto(vinculo):
    return AccessContext(
        user_id=vinculo.user_id, tenant_id=vinculo.tenant_id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles or []), request_id=None,
        tenant_status=vinculo.tenant.status, capabilities=frozenset(),
    )


def cliente_de(vinculo):
    cliente = Client()
    cliente.force_login(vinculo.user)
    sessao = cliente.session
    sessao['tenant_id'] = str(vinculo.tenant_id)
    sessao.save()
    return cliente


def ordem():
    return [(e.patient.full_name, e.posicao) for e in espera.lista(tenant.id)]


def posicoes():
    return [e.posicao for e in espera.lista(tenant.id)]


ctx = contexto(secretaria)
pacientes = list(Patient.objects.filter(tenant=tenant).order_by('record_number', 'id')[:6])
assert len(pacientes) >= 6, 'a semeadura precisa de ao menos seis pacientes na Clinica Demo A'
paciente_b = Patient.objects.filter(tenant=outra).first()

try:
    with transaction.atomic():
        # Começa da lista vazia, para as posições terem significado.
        PacienteEmEspera.objects.filter(tenant=tenant).delete()

        print('\n1. Incluir vai para o fim, e um paciente aguarda uma vez so')
        e1 = espera.incluir(ctx, pacientes[0], ator=secretaria)
        e2 = espera.incluir(ctx, pacientes[1], physician_membership=medico, ator=secretaria)
        e3 = espera.incluir(ctx, pacientes[2], ator=secretaria)
        conferir('posicoes 1, 2, 3', posicoes(), [1, 2, 3])
        try:
            espera.incluir(ctx, pacientes[0], ator=secretaria)
            conferir('o mesmo paciente de novo e recusado pelo servico', False, True)
        except espera.EsperaError as exc:
            conferir('o mesmo paciente de novo e recusado pelo servico', 'já está' in str(exc), True)
        try:
            with transaction.atomic():
                PacienteEmEspera.objects.create(
                    tenant=tenant, patient=pacientes[0], posicao=99,
                )
            conferir('e pelo banco', False, True)
        except IntegrityError:
            conferir('e pelo banco', True, True)

        print('\n2. Ordenar: setas, levar a posicao, numero fora da faixa')
        espera.mover_vizinho(ctx, e3, 'subir')
        conferir('subir troca com o de cima', [e.id for e in espera.lista(tenant.id)], [e1.id, e3.id, e2.id])
        espera.mover_vizinho(ctx, e1, 'subir')
        conferir('o primeiro nao sobe alem do topo', posicoes(), [1, 2, 3])
        espera.mover_para(ctx, e2, 1)
        conferir('levar a 1 abre espaco', [e.id for e in espera.lista(tenant.id)], [e2.id, e1.id, e3.id])
        espera.mover_para(ctx, e2, 999)
        conferir('posicao 999 vira a ultima', [e.id for e in espera.lista(tenant.id)][-1], e2.id)
        espera.mover_para(ctx, e2, -5)
        conferir('posicao negativa vira a primeira', [e.id for e in espera.lista(tenant.id)][0], e2.id)
        conferir('a sequencia continua sem buraco', posicoes(), [1, 2, 3])

        print('\n3. No recorte de um medico, o vizinho e o visivel')
        # Ordem agora: e2 (medico), e1 (qualquer), e3 (qualquer). Uma espera
        # de OUTRO medico no meio nao pode ser o vizinho de ninguem do recorte.
        if len(medicos) > 1:
            e4 = espera.incluir(ctx, pacientes[3], physician_membership=medicos[1], ator=secretaria)
            espera.mover_para(ctx, e4, 2)  # e2, e4, e1, e3
            espera.mover_vizinho(ctx, e1, 'subir', physician_membership_id=medico.id)
            ids = [e.id for e in espera.lista(tenant.id)]
            conferir('subir no recorte pula a linha de outro medico', ids.index(e1.id) < ids.index(e2.id), True)
            conferir('e a de outro medico nao some', e4.id in ids, True)
            recorte = [e.id for e in espera.lista(tenant.id, physician_membership_id=medico.id)]
            conferir('o recorte do medico nao mostra a do colega', e4.id in recorte, False)
            conferir('mas mostra a de qualquer medico', e3.id in recorte, True)
            espera.retirar(ctx, e4, motivo='teste', ator=secretaria)
        else:
            print('  (so um medico na demonstracao: secao pulada)')
        conferir('depois de retirar, a sequencia fecha', posicoes(), [1, 2, 3])

        print('\n4. Retirar e editar')
        espera.editar(ctx, e3, physician_membership=medico, appointment_type='return_visit',
                      observacao='  so pela manha  ')
        e3.refresh_from_db()
        conferir('editar grava medico, tipo e observacao limpa',
                 (e3.physician_membership_id, e3.appointment_type, e3.observacao),
                 (medico.id, 'return_visit', 'so pela manha'))
        e5 = espera.incluir(ctx, pacientes[4], ator=secretaria)
        espera.retirar(ctx, e5, motivo='desistiu', ator=secretaria)
        e5.refresh_from_db()
        conferir('retirado sai com motivo e sem posicao', (e5.status, e5.motivo_saida, e5.posicao),
                 (EsperaStatus.RETIRADO, 'desistiu', 0))
        try:
            espera.mover_para(ctx, e5, 1)
            conferir('mover quem saiu e recusado', False, True)
        except espera.EsperaError:
            conferir('mover quem saiu e recusado', True, True)
        conferir('e pode voltar a lista depois de sair',
                 espera.incluir(ctx, pacientes[4], ator=secretaria).posicao, 4)
        espera.retirar(ctx, espera.esperando(tenant.id, pacientes[4].id), ator=secretaria)

        print('\n5. Telas: secretaria e medico montam; so POST muda')
        sec = cliente_de(secretaria)
        doc = cliente_de(medico)
        url = reverse('scheduling:espera')
        resposta = sec.get(url)
        conferir('a secretaria abre a lista', resposta.status_code, 200)
        pagina = resposta.content.decode()
        conferir('e ve os nomes na ordem',
                 pagina.index(pacientes[1].full_name) < pagina.index(pacientes[2].full_name), True)
        conferir('o medico abre a lista', doc.get(url).status_code, 200)
        conferir('?physician=lixo nao derruba a tela', sec.get(url, {'physician': 'lixo'}).status_code, 200)
        conferir('o historico abre', sec.get(url, {'encerradas': '1'}).status_code, 200)
        conferir('o menu da agenda tem a lista', 'Lista de espera' in pagina, True)
        mover = reverse('scheduling:espera-mover', args=[e1.id])
        conferir('GET em mover nao e aceito', sec.get(mover).status_code, 405)
        antes = posicoes()
        r = doc.post(mover, {'posicao': '1'})
        conferir('o medico reordena (302)', r.status_code, 302)
        conferir('e o nome foi para o topo', espera.lista(tenant.id)[0].id, e1.id)
        r = sec.post(mover, {'posicao': 'abc'})
        conferir('posicao sem numero nao derruba (302)', r.status_code, 302)
        r = sec.post(mover, {'direcao': 'descer', 'filtro': str(medico.id)})
        conferir('descer pelo recorte responde e volta ao filtro', r['Location'].endswith(f'physician={medico.id}'), True)
        r = sec.post(mover, {'direcao': 'lado'})
        conferir('direcao inventada e recusada sem 500', r.status_code, 302)
        conferir('e a sequencia segue inteira', sorted(posicoes()), list(range(1, len(antes) + 1)))

        r = sec.post(reverse('scheduling:espera-incluir'), {
            'patient_id': str(pacientes[5].id), 'physician': str(medico.id),
            'appointment_type': 'first_visit', 'observacao': 'prefere SMS',
        })
        nova = espera.esperando(tenant.id, pacientes[5].id)
        conferir('incluir pela tela grava no fim', (r.status_code, nova and nova.posicao), (302, 4))
        r = sec.post(reverse('scheduling:espera-incluir'), {'physician': 'lixo'})
        conferir('incluir sem paciente nem nome e recusado sem 500', r.status_code, 302)
        total = Patient.objects.filter(tenant=tenant).count()
        r = sec.post(reverse('scheduling:espera-incluir'), {
            'new_name': 'Paciente Da Espera Teste', 'new_phone': '11988887777',
        })
        pre = Patient.objects.filter(tenant=tenant, full_name='PACIENTE DA ESPERA TESTE').first()
        conferir('o pre-cadastro pela lista cria o paciente em caixa alta', pre is not None, True)
        conferir('e o poe na lista', bool(pre and espera.esperando(tenant.id, pre.id)), True)
        # Recusada a inclusao (o mesmo pre-cadastro ja aguarda... por outro
        # caminho: paciente que ja aguarda), nada sobra.
        r = sec.post(reverse('scheduling:espera-incluir'), {'patient_id': str(pacientes[5].id)})
        conferir('paciente que ja aguarda: recusado', espera.lista(tenant.id).__len__(), 5)
        conferir('e nenhum paciente a mais alem do pre-cadastro',
                 Patient.objects.filter(tenant=tenant).count(), total + 1)
        editar = reverse('scheduling:espera-editar', args=[nova.id])
        r = sec.post(editar, {'physician': '', 'appointment_type': '', 'observacao': 'qualquer horario'})
        nova.refresh_from_db()
        conferir('editar pela tela: qualquer medico', (nova.physician_membership_id, nova.observacao),
                 (None, 'qualquer horario'))
        r = sec.post(editar, {'physician': str(vinculo_b.id) if vinculo_b else 'x'})
        nova.refresh_from_db()
        conferir('medico de outra clinica nao e aceito', nova.physician_membership_id, None)

        print('\n6. Opcoes do modal')
        opcoes_url = reverse('scheduling:espera-opcoes')
        dados = sec.get(opcoes_url, {'physician': str(medico.id)}).json()['results']
        ids_opcoes = [d['id'] for d in dados]
        esperadas = [e.id for e in espera.lista(tenant.id, physician_membership_id=medico.id)]
        conferir('as opcoes sao as do recorte, na ordem', ids_opcoes, [str(i) for i in esperadas])
        conferir('com nome e posicao', all(d['full_name'] and d['posicao'] for d in dados), True)
        conferir('sem medico na URL: 404', sec.get(opcoes_url).status_code, 404)
        conferir('medico invalido: 404', sec.get(opcoes_url, {'physician': 'lixo'}).status_code, 404)
        if vinculo_b:
            cb = cliente_de(vinculo_b)
            r = cb.get(opcoes_url, {'physician': str(medico.id)})
            conferir('outra clinica pedindo o medico daqui: 404', r.status_code, 404)
            conferir('outra clinica: mover em 404', cb.post(mover, {'posicao': '1'}).status_code, 404)
            conferir('outra clinica: retirar em 404',
                     cb.post(reverse('scheduling:espera-retirar', args=[e1.id])).status_code, 404)
            conferir('outra clinica nao ve os nomes',
                     pacientes[0].full_name in cb.get(url).content.decode(), False)
        if paciente_b:
            try:
                with transaction.atomic():
                    PacienteEmEspera.objects.create(tenant=tenant, patient=paciente_b, posicao=50)
                conferir('o banco recusa paciente de outra clinica', False, True)
            except IntegrityError:
                conferir('o banco recusa paciente de outra clinica', True, True)

        print('\n7. Puxar no modal de marcar')
        book = reverse('scheduling:quick-book', args=[medico.id])
        inicio = (timezone.localtime() + timedelta(days=40)).replace(hour=6, minute=7, second=0, microsecond=0)
        alvo = espera.lista(tenant.id, physician_membership_id=medico.id)[0]
        abaixo = [e.id for e in espera.lista(tenant.id) if e.posicao > alvo.posicao]
        consultas = Appointment.objects.filter(tenant=tenant).count()
        # Fora da grade sem encaixe: o horario e recusado, e a espera fica.
        r = sec.post(book, {
            'starts_at': inicio.isoformat(), 'appointment_type': 'follow_up',
            'espera_id': str(alvo.id), 'patient_id': str(alvo.patient_id),
            'date': inicio.date().isoformat(),
        })
        alvo.refresh_from_db()
        conferir('horario recusado: a espera continua aguardando', alvo.status, EsperaStatus.AGUARDANDO)
        conferir('e nenhuma consulta nasceu', Appointment.objects.filter(tenant=tenant).count(), consultas)
        # Paciente trocado no formulario: nao leva a espera junto.
        r = sec.post(book, {
            'starts_at': inicio.isoformat(), 'appointment_type': 'follow_up',
            'espera_id': str(alvo.id), 'patient_id': str(pacientes[0].id if pacientes[0].id != alvo.patient_id else pacientes[1].id),
            'is_overbook': 'on', 'override_reason': 'teste', 'date': inicio.date().isoformat(),
        })
        alvo.refresh_from_db()
        conferir('paciente trocado: recusado, espera intacta', alvo.status, EsperaStatus.AGUARDANDO)
        conferir('e nenhuma consulta', Appointment.objects.filter(tenant=tenant).count(), consultas)
        # Agora como o modal manda: encaixe, para nao depender da grade.
        r = sec.post(book, {
            'starts_at': inicio.isoformat(), 'appointment_type': 'follow_up',
            'espera_id': str(alvo.id), 'patient_id': str(alvo.patient_id),
            'is_overbook': 'on', 'override_reason': 'lista de espera', 'date': inicio.date().isoformat(),
        })
        alvo.refresh_from_db()
        conferir('puxado: a espera se encerra como agendada', alvo.status, EsperaStatus.AGENDADO)
        conferir('ligada a consulta do paciente certo',
                 bool(alvo.appointment and alvo.appointment.patient_id == alvo.patient_id
                      and alvo.appointment.status == AppointmentStatus.SCHEDULED), True)
        conferir('os de baixo subiram', posicoes(), list(range(1, len(posicoes()) + 1)))
        conferir('e quem estava abaixo continua na lista',
                 all(PacienteEmEspera.objects.get(id=i).status == EsperaStatus.AGUARDANDO for i in abaixo), True)
        consultas = Appointment.objects.filter(tenant=tenant).count()
        # A segunda pessoa puxa o mesmo nome um instante depois.
        r = sec.post(book, {
            'starts_at': (inicio + timedelta(hours=2)).isoformat(), 'appointment_type': 'follow_up',
            'espera_id': str(alvo.id), 'patient_id': str(alvo.patient_id),
            'is_overbook': 'on', 'override_reason': 'segunda vez', 'date': inicio.date().isoformat(),
        })
        conferir('puxar de novo uma espera encerrada nao marca segundo horario',
                 Appointment.objects.filter(tenant=tenant).count(), consultas)
        if len(medicos) > 1:
            de_outro = espera.incluir(ctx, pacientes[3], physician_membership=medicos[1], ator=secretaria)
            r = sec.post(book, {
                'starts_at': (inicio + timedelta(hours=3)).isoformat(), 'appointment_type': 'follow_up',
                'espera_id': str(de_outro.id), 'patient_id': str(de_outro.patient_id),
                'is_overbook': 'on', 'override_reason': 'x', 'date': inicio.date().isoformat(),
            })
            de_outro.refresh_from_db()
            conferir('espera de outro medico nao entra nesta agenda',
                     (de_outro.status, Appointment.objects.filter(tenant=tenant).count()),
                     (EsperaStatus.AGUARDANDO, consultas))

        print('\n8. O caminho de sempre do modal nao mudou')
        quem = espera.lista(tenant.id)[0]
        r = sec.post(book, {
            'starts_at': (inicio + timedelta(hours=5)).isoformat(), 'appointment_type': 'follow_up',
            'patient_id': str(quem.patient_id), 'is_overbook': 'on', 'override_reason': 'busca',
            'date': inicio.date().isoformat(),
        }, follow=True)
        quem.refresh_from_db()
        conferir('marcar pela busca marca', Appointment.objects.filter(tenant=tenant).count(), consultas + 1)
        conferir('e nao encerra a espera', quem.status, EsperaStatus.AGUARDANDO)
        conferir('mas avisa que o nome continua na lista',
                 'continua na lista de espera' in r.content.decode(), True)
        r = sec.get(url)
        conferir('e a lista mostra que ele ja tem horario', 'Já tem horário em' in r.content.decode(), True)

        print('\n9. A trilha sem nome de paciente')
        eventos = AuditEvent.objects.filter(tenant_id=tenant.id, action__startswith='scheduling.espera_')
        acoes = set(eventos.values_list('action', flat=True))
        conferir('incluida, movida, editada, retirada e agendada na trilha',
                 {'scheduling.espera_incluida', 'scheduling.espera_movida', 'scheduling.espera_editada',
                  'scheduling.espera_retirada', 'scheduling.espera_agendada'} <= acoes, True)
        nomes = [p.full_name for p in pacientes]
        conferir('nenhum nome nos metadados',
                 any(n in str(m) for m in eventos.values_list('integrity_metadata', flat=True) for n in nomes), False)

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('Lista de espera: tudo confere.')
