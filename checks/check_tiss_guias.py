"""A guia TISS: nasce do que existe, diz o que falta, fecha congelada (Sprint 2).

Tenta quebrar:

- **cobrança**: a guia de Consulta de um horário com check-in vincula a
  cobrança que já existe — nenhum recebível novo —, e a mesma cobrança não
  entra em duas guias (nem pela tela, nem pelo banco); cancelar a solta;
- **preenchimento**: convênio, carteira, credenciamento, executante e tipo
  de consulta vêm sozinhos; o que não dá para saber vira pendência, e a
  guia não fecha com pendência que impede;
- **TUSS**: código inexistente, e código que não valia na data do serviço,
  recusados; o que valia na data passa mesmo encerrado hoje;
- **preço**: o do contrato, com a origem; valor diferente exige motivo;
  sem contrato, exige valor e motivo; fator e arredondamento uma vez só;
- **versão**: tipo de atendimento 05 vale na 4.00.00 e não na 4.03.00 (que
  pede 23);
- **fechar congela**: o snapshot e a impressão não mudam quando a carteira
  muda; guia fechada não aceita item; revisão substitui sem reescrever;
- **o que a recepção vê**: a tela da guia não traz o prontuário, e só o
  médico escreve a indicação clínica;
- **fronteira**: outra clínica não vê nem altera; GET não cria guia;
- **numeração**: sequência sem repetir;
- **impressão**: PDF com a numeração oficial, tarja no rascunho, e a SP/SADT
  de sete procedimentos em duas folhas, "Folha 2 de 2".

Tudo numa transação desfeita no fim.

    docker compose exec -T app python manage.py shell < checks/check_tiss_guias.py
"""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as dj_settings
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.mfa import RECENT_MFA_SESSION_KEY
from catalogs.models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode
from clinical.models import Encounter
from finance.models import FeeSchedule, PaymentCategory, Receivable
from patients.models import HealthPlan, Insurer, Patient, PatientCoverage
from scheduling import services as agenda
from scheduling.models import AppointmentType, BillingMode
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.plans import PlanCode
from tiss import guias
from tiss.impressao import pdf_da_guia
from tiss.models import (
    Configuracao, Credenciamento, EstadoGuia, Guia, ItemGuia, Prestador, ProfissionalTiss, TipoGuia,
)

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


clinica = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=clinica.id).order_by('created_at').first()
vinculos = list(Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE).select_related('user'))
secretaria = next((m for m in vinculos if Role.SECRETARY in (m.roles or [])
                   and not {Role.OWNER, Role.MANAGER, Role.DOCTOR} & set(m.roles or [])), None)
medico = next((m for m in vinculos if Role.DOCTOR in (m.roles or []) and m.can_practice_clinically()), None)
paciente = Patient.objects.filter(tenant=clinica).order_by('created_at').first()
if None in (secretaria, medico, paciente, outra):
    print('  (demonstração incompleta; roteiro pulado)')
    raise SystemExit(0)


def contexto(quem):
    from tenancy.permissions import capabilities_for
    return AccessContext(
        user_id=quem.user_id, tenant_id=clinica.id, membership_id=quem.id,
        permissions=frozenset(quem.roles), request_id=uuid.uuid4(),
        capabilities=capabilities_for(quem.roles, clinically_enabled=quem.can_practice_clinically(),
                                      ai_contracted=False, tiss_contracted=True),
    )


def cliente(quem, tenant=clinica):
    c = Client(SERVER_NAME='localhost')
    c.force_login(quem.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s[RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
    s.save()
    return c


def texto_pdf(conteudo):
    from pypdf import PdfReader
    leitor = PdfReader(io.BytesIO(conteudo))
    return len(leitor.pages), '\n'.join(p.extract_text() for p in leitor.pages)


ctx_sec, ctx_med = contexto(secretaria), contexto(medico)
hoje = timezone.localdate()

try:
    with transaction.atomic():
        Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
        config = Configuracao.carregar()
        Configuracao.objects.filter(id=config.id).update(ativo=True)

        # Catálogo TUSS próprio do roteiro, com vigência.
        CatalogRelease.objects.filter(system=CatalogSystem.TUSS).update(status=CatalogReleaseStatus.SUPERSEDED)
        rel = CatalogRelease.objects.create(system=CatalogSystem.TUSS, version='ANS-roteiro-guias',
                                            status=CatalogReleaseStatus.ACTIVE, imported_at=timezone.now())
        consulta_tuss = ProcedureCode.objects.create(release=rel, code='10101012', description='CONSULTA EM CONSULTORIO',
                                                     starts_on=date(2010, 1, 1), active=True)
        ProcedureCode.objects.create(release=rel, code='40103323', description='ELETRONEUROMIOGRAFIA DE MMSS',
                                     starts_on=date(2010, 1, 1), active=True)
        ProcedureCode.objects.create(release=rel, code='40103099', description='EXAME ENCERRADO EM 2020',
                                     starts_on=date(2010, 1, 1), ends_on=date(2020, 6, 30), active=False)

        operadora = Insurer.objects.create(tenant=clinica, name='OPERADORA ROTEIRO GUIAS', ans_registration='368253')
        plano = HealthPlan.objects.create(tenant=clinica, insurer=operadora, name='PLANO ROTEIRO GUIAS')
        cobertura = PatientCoverage.objects.create(tenant=clinica, patient=paciente, plan=plano,
                                                   member_number='0182D000430005', starts_on=date(2020, 1, 1))
        prestador = Prestador.objects.create(tenant=clinica, nome='CLINICA ROTEIRO LTDA', cnpj='69887146000105',
                                             cnes='9876543')
        cred = Credenciamento.objects.create(tenant=clinica, prestador=prestador, operadora=operadora,
                                             codigo_na_operadora='00012345', versao='4.03.00')
        prof = ProfissionalTiss.objects.create(tenant=clinica, nome='DR ROTEIRO', numero_conselho='11788',
                                               uf='PA', cbo='225112', membership=medico)
        TIPO = AppointmentType.OTHER
        for proc, valor in ((None, '150.00'), (consulta_tuss, '150.00')):
            FeeSchedule.objects.create(
                tenant=clinica, physician=None, plan=plano, procedure=proc, appointment_type=None if proc else TIPO,
                payment_category=PaymentCategory.INSURANCE, gross_amount=Decimal(valor),
                doctor_share_amount=Decimal('0'), effective_from=hoje - timedelta(days=1),
            )

        inicio = timezone.now().replace(microsecond=0) - timedelta(hours=2)
        appt = agenda.reserve_appointment(ctx_sec, paciente, medico, inicio, inicio + timedelta(minutes=30), TIPO,
                                          is_overbook=True, override_reason='roteiro guias', override_by=medico)
        agenda.set_billing_mode(ctx_sec, appt, BillingMode.INSURANCE, cobertura.id, secretaria.user_id)
        agenda.check_in(appt, secretaria.user_id)
        cobranca = Receivable.objects.get(appointment=appt)
        recebiveis_antes = Receivable.objects.filter(tenant=clinica).count()

        print('=== 1. A guia de Consulta do horário: o que existe vem sozinho ===')
        g = guias.criar_guia(ctx_sec, secretaria.user, paciente, TipoGuia.CONSULTA, appointment=appt)
        conferir('convênio do horário', g.cobertura_id == cobertura.id)
        conferir('carteira com zero e letra preservados', g.carteira == '0182D000430005')
        conferir('credenciamento único da operadora', g.credenciamento_id == cred.id)
        conferir('executante = o médico do horário', g.executante_id == prof.id)
        item = g.itens.first()
        conferir('a consulta cobrada vira o item', item is not None and item.recebivel_id == cobranca.id)
        conferir('nenhum recebível novo', Receivable.objects.filter(tenant=clinica).count() == recebiveis_antes)
        conferir('pendências: falta o código (a regra do check-in não tinha)',
                 any(p.campo == 'itens' for p in guias.pendencias(g)) and not guias.pode_fechar(g))
        guias.gravar_item(ctx_sec, secretaria.user, g, {'data_execucao': inicio.date(), 'codigo': '10101012',
                                                         'tabela': '22'})
        item.refresh_from_db()
        conferir('incluir o código completa o item, sem perder a cobrança',
                 g.itens.count() == 1 and item.codigo == '10101012' and item.recebivel_id == cobranca.id)
        conferir('preço do contrato, com a origem', item.valor_total == Decimal('150.00') and 'Tabela' in item.preco_origem)
        Guia.objects.filter(id=g.id).update(tipo_consulta='')
        g.refresh_from_db()
        try:
            guias.fechar(ctx_sec, secretaria.user, g)
            conferir('não fecha com pendência que impede', False, 'fechou')
        except guias.GuiaRecusada:
            conferir('não fecha com pendência que impede', True)
        Guia.objects.filter(id=g.id).update(tipo_consulta='1')
        g.refresh_from_db()
        guias.fechar(ctx_sec, secretaria.user, g)
        g.refresh_from_db()
        conferir('fechada, com snapshot e versão', g.estado == EstadoGuia.FECHADA and g.snapshot['total'] == '150.00'
                 and g.versao == '4.03.00')

        print('=== 2. Fechar congela ===')
        PatientCoverage.objects.filter(id=cobertura.id).update(member_number='999TROCADA')
        paginas, texto = texto_pdf(pdf_da_guia(Guia.objects.get(id=g.id)))
        conferir('a impressão segue o snapshot (carteira antiga)', '0182D000430005' in texto and '999TROCADA' not in texto)
        conferir('numeração oficial do modelo', '1 - Registro ANS' in texto and '22 - Valor do Procedimento' in texto)
        conferir('fechada sem tarja', 'NÃO ENVIAR' not in texto)
        try:
            guias.gravar_item(ctx_sec, secretaria.user, g, {'data_execucao': hoje, 'codigo': '10101012'})
            conferir('guia fechada não aceita item', False)
        except guias.GuiaRecusada:
            conferir('guia fechada não aceita item', True)

        print('=== 3. A mesma cobrança não entra em duas guias ===')
        g2 = guias.criar_guia(ctx_sec, secretaria.user, paciente, TipoGuia.CONSULTA, appointment=appt)
        conferir('a segunda guia não vincula a cobrança já faturada', not g2.itens.exclude(recebivel=None).exists())
        try:
            with transaction.atomic():
                ItemGuia.objects.create(tenant=clinica, guia=g2, sequencial=9, data_execucao=hoje, codigo='10101012',
                                        descricao='x', valor_unitario=1, valor_total=1, recebivel=cobranca)
            conferir('o banco recusa o vínculo duplicado', False)
        except IntegrityError:
            conferir('o banco recusa o vínculo duplicado', True)

        print('=== 4. Revisão substitui sem reescrever ===')
        snap = dict(g.snapshot)
        rev = guias.abrir_revisao(ctx_sec, secretaria.user, g)
        conferir('revisão nasce em preenchimento, com a cobrança', rev.estado == EstadoGuia.RASCUNHO
                 and rev.itens.filter(recebivel=cobranca).exists())
        Guia.objects.filter(id=rev.id).update(carteira='0182D000430005')
        guias.fechar(ctx_sec, secretaria.user, Guia.objects.get(id=rev.id))
        g.refresh_from_db()
        conferir('a original fica substituída, com o snapshot intacto',
                 g.estado == EstadoGuia.SUBSTITUIDA and g.snapshot == snap)

        print('=== 5. SP/SADT: código, data, preço, versão ===')
        s = guias.criar_guia(ctx_sec, secretaria.user, paciente, TipoGuia.SP_SADT)
        conferir('sem horário: sem item (nada prova a execução)', not s.itens.exists())
        # O paciente de demonstração tem outro convênio ativo na ficha; a guia
        # do roteiro aponta para o do teste, como a recepção escolheria.
        Guia.objects.filter(id=s.id).update(cobertura=cobertura, credenciamento=cred, carteira='0182D000430005')
        s = Guia.objects.get(id=s.id)
        for rotulo, dados_item in (
            ('código inexistente', {'codigo': '99999999'}),
            ('código que não valia na data', {'codigo': '40103099'}),
            ('sem contrato e sem valor', {'codigo': '40103323'}),
            ('valor sem motivo', {'codigo': '40103323', 'valor_unitario': '200.00'}),
        ):
            try:
                guias.gravar_item(ctx_sec, secretaria.user, s, {'data_execucao': hoje, 'tabela': '22', **dados_item})
                conferir(f'{rotulo}: recusado', False, 'aceitou')
            except guias.GuiaRecusada:
                conferir(f'{rotulo}: recusado', True)
        it = guias.gravar_item(ctx_sec, secretaria.user, s, {'data_execucao': date(2019, 5, 2), 'tabela': '22',
                                                              'codigo': '40103099', 'valor_unitario': '100.00',
                                                              'preco_motivo': 'contrato antigo'})
        conferir('encerrado hoje, mas vigente na data do serviço: aceito', it.codigo == '40103099')
        it = guias.gravar_item(ctx_sec, secretaria.user, s, {'data_execucao': hoje, 'tabela': '22', 'codigo': '40103323',
                                                              'quantidade': 3, 'valor_unitario': '33.33',
                                                              'fator': '0.70', 'preco_motivo': 'tabela do portal'})
        conferir('3 × 33,33 × 0,70 = 69,99, arredondado uma vez', it.valor_total == Decimal('69.99'), str(it.valor_total))
        Guia.objects.filter(id=s.id).update(tipo_atendimento='05')
        s.refresh_from_db()
        conferir('05 recusado na 4.03.00', any(p.campo == 'tipo_atendimento' for p in guias.pendencias(s)))
        Credenciamento.objects.filter(id=cred.id).update(versao='4.00.00')
        s = Guia.objects.get(id=s.id)
        conferir('05 aceito na 4.00.00', not any(p.campo == 'tipo_atendimento' for p in guias.pendencias(s)))
        Credenciamento.objects.filter(id=cred.id).update(versao='4.03.00')
        Guia.objects.filter(id=s.id).update(tipo_atendimento='23')
        s = Guia.objects.get(id=s.id)
        conferir('falta o solicitante: pendência', any(p.campo == 'solicitante' for p in guias.pendencias(s)))
        conferir('indicação em branco: aviso para o médico, não impede',
                 any(p.campo == 'indicacao_clinica' and not p.impede and p.quem == 'medico' for p in guias.pendencias(s)))

        print('=== 6. O que a recepção vê, e quem escreve a indicação ===')
        encontro = Encounter.objects.filter(tenant=clinica, patient=paciente).exclude(chief_complaint='').first()
        if encontro:
            Guia.objects.filter(id=s.id).update(encounter=encontro)
        c_sec = cliente(secretaria)
        pagina = c_sec.get(f'/app/tiss/guias/{s.id}/')
        corpo = pagina.content.decode()
        conferir('a secretária abre a guia', pagina.status_code == 200, str(pagina.status_code))
        if encontro:
            conferir('sem o prontuário na página', encontro.chief_complaint[:30] not in corpo)
        r = c_sec.post(f'/app/tiss/guias/{s.id}/indicacao/', {'indicacao_clinica': 'escrita pela recepção'})
        s.refresh_from_db()
        conferir('a secretária não escreve a indicação', r.status_code == 404 and s.indicacao_clinica == '')
        c_med = cliente(medico)
        c_med.post(f'/app/tiss/guias/{s.id}/indicacao/', {'indicacao_clinica': 'Parestesia em MMSS'})
        s.refresh_from_db()
        conferir('o médico escreve, com autoria', s.indicacao_clinica == 'Parestesia em MMSS'
                 and s.indicacao_por_id == medico.user_id)
        ficha = c_sec.get(f'/app/patients/{paciente.id}/').content.decode()
        conferir('a ficha mostra "Gerar guia TISS" à secretária', 'Gerar guia TISS' in ficha)

        print('=== 7. Impressão da SP/SADT em folhas ===')
        for n in range(5):
            guias.gravar_item(ctx_sec, secretaria.user, s, {'data_execucao': hoje, 'tabela': '22', 'codigo': '40103323',
                                                            'valor_unitario': '10.00', 'preco_motivo': 'teste'})
        paginas, texto = texto_pdf(pdf_da_guia(Guia.objects.get(id=s.id)))
        conferir('sete procedimentos, duas folhas', paginas == 2, str(paginas))
        conferir('"Folha 2 de 2"', 'Folha 2 de 2' in texto)
        conferir('rascunho sai com tarja', 'NÃO ENVIAR' in texto)
        conferir('indicação clínica no campo 23', 'Parestesia em MMSS' in texto)

        print('=== 8. Fronteira, GET e numeração ===')
        conferir('a lista abre', c_sec.get('/app/tiss/guias/').status_code == 200)
        conferir('a lista do paciente abre', c_sec.get(f'/app/tiss/guias/?paciente={paciente.id}').status_code == 200)
        conferir('paciente inválido no filtro: 404', c_sec.get('/app/tiss/guias/?paciente=xyz').status_code == 404)
        conferir('a nova guia abre', c_sec.get(f'/app/tiss/guias/nova/?paciente={paciente.id}').status_code == 200)
        r = c_sec.get(f'/app/tiss/guias/{s.id}/imprimir/')
        conferir('a impressão sai em PDF, sem cache', r.status_code == 200 and r.content[:4] == b'%PDF'
                 and 'no-store' in r['Cache-Control'])
        r = c_sec.post('/app/tiss/guias/nova/', {'paciente': paciente.id, 'tipo': 'sp_sadt', 'appointment': ''})
        conferir('o POST da nova guia cria e leva à guia', r.status_code == 302 and '/app/tiss/guias/' in r['Location'])
        total_guias = Guia.objects.filter(tenant=clinica).count()
        c_sec.get(f'/app/tiss/guias/nova/?paciente={paciente.id}')
        conferir('GET da nova guia não cria nada', Guia.objects.filter(tenant=clinica).count() == total_guias)
        numeros = list(Guia.objects.filter(tenant=clinica).values_list('numero_prestador', flat=True))
        conferir('números sem repetição', len(numeros) == len(set(numeros)))
        estranho = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE).select_related('user').first()
        if estranho:
            Tenant.objects.filter(id=outra.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
            c_out = cliente(estranho, outra)
            conferir('outra clínica: 404 na guia', c_out.get(f'/app/tiss/guias/{s.id}/').status_code == 404)
            r = c_out.post(f'/app/tiss/guias/{s.id}/fechar/')
            conferir('outra clínica: 404 ao fechar', r.status_code == 404)
            conferir('outra clínica: 404 ao imprimir', c_out.get(f'/app/tiss/guias/{s.id}/imprimir/').status_code == 404)
            conferir('outra clínica: paciente alheio em 404',
                     c_out.get(f'/app/tiss/guias/nova/?paciente={paciente.id}').status_code == 404)

        print('=== 9. Cancelar solta a cobrança ===')
        rev = Guia.objects.get(id=rev.id)
        guias.cancelar(ctx_sec, secretaria.user, rev, 'convênio errado')
        conferir('cancelada, e a cobrança livre', not ItemGuia.objects.filter(recebivel=cobranca).exists())
        g3 = guias.criar_guia(ctx_sec, secretaria.user, paciente, TipoGuia.CONSULTA, appointment=appt)
        conferir('uma guia nova pode faturá-la', g3.itens.filter(recebivel=cobranca).exists())

        print('=== 10. Plano sem TISS ===')
        Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.BASIC)
        conferir('no Básico, a lista dá 404', cliente(secretaria).get('/app/tiss/guias/').status_code == 404)
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Tudo certo.')
