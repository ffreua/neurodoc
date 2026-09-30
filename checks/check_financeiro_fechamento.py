"""Exportação, documento fiscal, repasse e limpeza segura do financeiro.

O roteiro roda numa transação que é sempre revertida. Assim ele consegue
provar inclusive a exclusão definitiva de todo o histórico da clínica sem
alterar a base de demonstração usada pelos demais roteiros.
"""
import datetime
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.test import Client
from django.utils import timezone

from audit.models import AuditEvent
from clinical.models import Encounter, EncounterKind, EncounterStatus
from finance.models import FinancialAdjustment, Payment, Receivable, ReceivableStatus
from finance.payments import record_payment
from patients.models import Patient, PatientStatus, RegistrationStage
from reporting import operations
from tenancy.models import Membership, MembershipStatus, Role, Tenant


settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
settings.SECURE_SSL_REDIRECT = False


falhas = []


def conferir(condicao, mensagem):
    print(f'  {mensagem:<64} -> {"ok" if condicao else "FALHA"}')
    if not condicao:
        falhas.append(mensagem)


def cliente(vinculo):
    navegador = Client()
    navegador.force_login(vinculo.user)
    sessao = navegador.session
    sessao['tenant_id'] = str(vinculo.tenant_id)
    sessao.save()
    return navegador


with transaction.atomic():
    try:
        tenant = Tenant.objects.get(slug='demo-clinica-a')
        dono = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE,
            roles__contains=[Role.OWNER],
        ).select_related('user').first()
        gestor = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE,
            roles__contains=[Role.MANAGER],
        ).select_related('user').first()
        secretaria = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE,
            roles__contains=[Role.SECRETARY],
        ).select_related('user').first()
        if None in (dono, gestor, secretaria):
            print('PULADO: demonstração sem dono, gestor e secretária ativos')
            transaction.set_rollback(True)
            raise SystemExit(0)

        hoje = timezone.localdate()
        paciente = Patient.objects.create(
            tenant=tenant,
            full_name=f'Financeiro Exportação {uuid.uuid4().hex[:8]}',
            birth_date=datetime.date(1984, 5, 6),
            registration_stage=RegistrationStage.COMPLETE,
            status=PatientStatus.ACTIVE,
        )
        encontro = Encounter.objects.create(
            tenant=tenant, patient=paciente, physician_membership=dono,
            occurred_at=timezone.now(), kind=EncounterKind.FREE_TEXT,
            status=EncounterStatus.FINALIZED, finalized_at=timezone.now(),
            finalized_by=dono,
        )
        recebivel = Receivable.objects.create(
            tenant=tenant, patient=paciente, encounter=encontro,
            fee_snapshot={
                'payment_category': 'private',
                'doctor_share_amount': '60.00',
                'physician_id': str(dono.id),
            },
            expected_amount=Decimal('100.00'), charged_amount=Decimal('100.00'),
            due_date=hoje, competence_date=hoje, status=ReceivableStatus.PENDING,
        )
        pagamento = record_payment(
            recebivel, Decimal('40.00'), 'pix', dono.user_id,
            external_reference='PIX-TRANSACAO-123',
        )

        inicio = hoje.isoformat()
        fim = hoje.isoformat()
        navegador_secretaria = cliente(secretaria)
        navegador_gestor = cliente(gestor)
        navegador_dono = cliente(dono)

        print('=== 1. o detalhe guarda o número do recibo ou da nota fiscal ===')
        detalhe = navegador_secretaria.get(f'/app/finance/{recebivel.id}/')
        conferir(detalhe.status_code == 200, 'secretária continua abrindo o recebível')
        conferir(
            'Número do recibo ou nota fiscal' in detalhe.content.decode('utf-8', 'replace'),
            'o detalhe oferece o campo fiscal',
        )
        salvo = navegador_secretaria.post(
            f'/app/finance/{recebivel.id}/fiscal-document/',
            {'fiscal_document_number': 'NF-e 2026/00042'},
        )
        recebivel.refresh_from_db()
        conferir(salvo.status_code == 302, 'salvar o número fiscal redireciona sem erro')
        conferir(
            getattr(recebivel, 'fiscal_document_number', '') == 'NF-e 2026/00042',
            'o número fiscal fica salvo no recebível',
        )
        conferir(
            AuditEvent.objects.filter(
                tenant=tenant, action='finance.fiscal_document_updated',
                object_id=recebivel.id,
            ).exists(),
            'a alteração do número fiscal entra na auditoria',
        )

        print('=== 2. competência e caixa exportam o período filtrado em CSV ===')
        pagina = navegador_secretaria.get(f'/app/finance/?start={inicio}&end={fim}')
        corpo_pagina = pagina.content.decode('utf-8', 'replace')
        conferir('Exportar competência' in corpo_pagina, 'a competência oferece exportação')
        conferir('Exportar caixa' in corpo_pagina, 'o caixa oferece exportação')

        export_competencia = navegador_secretaria.get(
            f'/app/finance/export/competence.csv?start={inicio}&end={fim}',
        )
        texto_competencia = export_competencia.content.decode('utf-8-sig', 'replace')
        conferir(export_competencia.status_code == 200, 'CSV de competência responde 200')
        conferir(
            export_competencia.get('Content-Disposition', '').endswith('.csv"'),
            'CSV de competência baixa como arquivo',
        )
        conferir(paciente.full_name in texto_competencia, 'CSV de competência leva o paciente')
        conferir('NF-e 2026/00042' in texto_competencia, 'CSV de competência leva o número fiscal')
        conferir('60.00' in texto_competencia, 'CSV de competência leva o repasse previsto')

        export_caixa = navegador_secretaria.get(
            f'/app/finance/export/cash.csv?start={inicio}&end={fim}',
        )
        texto_caixa = export_caixa.content.decode('utf-8-sig', 'replace')
        conferir(export_caixa.status_code == 200, 'CSV de caixa responde 200')
        conferir(paciente.full_name in texto_caixa, 'CSV de caixa leva o paciente')
        conferir('NF-e 2026/00042' in texto_caixa, 'CSV de caixa leva o número fiscal')
        conferir('PIX-TRANSACAO-123' in texto_caixa, 'CSV mantém separada a referência bancária')

        print('=== 3. somente gestor/dono marca o repasse individual ===')
        negado = navegador_secretaria.post(
            f'/app/finance/{recebivel.id}/doctor-share/mark/',
        )
        recebivel.refresh_from_db()
        conferir(negado.status_code == 404, 'secretária não pode marcar repasse')
        conferir(
            getattr(recebivel, 'doctor_share_paid_at', None) is None,
            'a tentativa negada não altera a cobrança',
        )

        receita_antes = operations.revenue_by_competence(tenant, hoje, hoje)
        caixa_antes = operations.cash_received(tenant, hoje, hoje)
        saldo_antes = operations.outstanding_balance(tenant, hoje)
        repasse_antes = operations.doctor_share_forecast(tenant, hoje, hoje)
        categorias_antes = operations.payment_category_breakdown(tenant, hoje, hoje)
        marcado = navegador_gestor.post(
            f'/app/finance/{recebivel.id}/doctor-share/mark/',
        )
        recebivel.refresh_from_db()
        conferir(marcado.status_code == 302, 'gestor marca o repasse')
        conferir(
            getattr(recebivel, 'doctor_share_paid_at', None) is not None,
            'data do repasse realizado fica salva',
        )
        conferir(
            str(getattr(recebivel, 'doctor_share_paid_by_id', '')) == str(gestor.id),
            'responsável pelo repasse fica salvo',
        )
        conferir(
            getattr(recebivel, 'doctor_share_paid_amount', None) == Decimal('60.00'),
            'valor congelado do repasse fica salvo',
        )
        conferir(
            operations.revenue_by_competence(tenant, hoje, hoje)
            == receita_antes - Decimal('100.00'),
            'repasse realizado sai da receita por competência',
        )
        conferir(
            operations.cash_received(tenant, hoje, hoje) == caixa_antes - Decimal('40.00'),
            'repasse realizado sai do caixa',
        )
        conferir(
            operations.outstanding_balance(tenant, hoje) == saldo_antes - Decimal('60.00'),
            'repasse realizado sai do saldo em aberto',
        )
        conferir(
            operations.doctor_share_forecast(tenant, hoje, hoje)
            == repasse_antes - Decimal('60.00'),
            'repasse realizado sai da previsão de repasse',
        )
        conferir(
            operations.payment_category_breakdown(tenant, hoje, hoje)['private']
            == categorias_antes['private'] - 1,
            'repasse realizado sai do indicador particular/plano',
        )
        pagina_depois = navegador_dono.get(f'/app/finance/?start={inicio}&end={fim}')
        conferir(
            paciente.full_name not in pagina_depois.content.decode('utf-8', 'replace'),
            'repasse realizado some de competência e caixa',
        )
        csv_depois = navegador_dono.get(
            f'/app/finance/export/competence.csv?start={inicio}&end={fim}',
        ).content.decode('utf-8-sig', 'replace')
        conferir(paciente.full_name not in csv_depois, 'repasse realizado sai da exportação')

        historico = navegador_gestor.get('/app/finance/history/')
        conferir(historico.status_code == 200, 'gestor abre o histórico retirado')
        conferir(
            paciente.full_name in historico.content.decode('utf-8', 'replace'),
            'o repasse realizado continua consultável',
        )
        desfeito = navegador_gestor.post(
            f'/app/finance/{recebivel.id}/doctor-share/undo/',
        )
        recebivel.refresh_from_db()
        conferir(desfeito.status_code == 302, 'gestor consegue desfazer repasse marcado por engano')
        conferir(
            getattr(recebivel, 'doctor_share_paid_at', None) is None,
            'desfazer devolve a cobrança ao financeiro',
        )
        conferir(
            getattr(recebivel, 'doctor_share_paid_amount', 'campo-ausente') is None,
            'desfazer limpa o valor de repasse realizado',
        )

        print('=== 4. arquivar todo o histórico é reversível e restrito ===')
        total_antes = Receivable.objects.filter(tenant=tenant).count()
        negado = navegador_secretaria.post(
            '/app/finance/history/archive/', {'confirmation': 'ARQUIVAR'},
        )
        conferir(negado.status_code == 404, 'secretária não pode arquivar o histórico')
        arquivado = navegador_dono.post(
            '/app/finance/history/archive/', {'confirmation': 'ARQUIVAR'},
        )
        conferir(arquivado.status_code == 302, 'dono arquiva todo o histórico')
        tem_campo_arquivo = any(
            campo.name == 'archived_at' for campo in Receivable._meta.get_fields()
        )
        conferir(
            tem_campo_arquivo and Receivable.objects.filter(
                tenant=tenant, archived_at__isnull=True,
            ).count() == 0,
            'nenhuma cobrança ativa sobra depois do arquivamento',
        )
        conferir(
            Receivable.objects.filter(tenant=tenant).count() == total_antes,
            'arquivar não apaga linhas do banco',
        )
        conferir(
            operations.revenue_by_competence(
                tenant, datetime.date(1900, 1, 1), datetime.date(2999, 12, 31),
            ) == Decimal('0.00'),
            'arquivar zera os indicadores financeiros',
        )
        restaurado = navegador_gestor.post('/app/finance/history/restore/')
        receber_de_novo = Receivable.objects.get(id=recebivel.id)
        conferir(restaurado.status_code == 302, 'gestor restaura o histórico arquivado')
        conferir(
            getattr(receber_de_novo, 'archived_at', 'campo-ausente') is None,
            'a cobrança restaurada volta a ficar ativa',
        )

        print('=== 5. exclusão definitiva exige confirmação reforçada ===')
        outro_tenant = Tenant.objects.exclude(id=tenant.id).order_by('created_at').first()
        outro_antes = None
        if outro_tenant:
            outro_antes = (
                Receivable.objects.filter(tenant=outro_tenant).count(),
                Payment.objects.filter(tenant=outro_tenant).count(),
                FinancialAdjustment.objects.filter(tenant=outro_tenant).count(),
            )
        tela_limpeza = navegador_dono.get('/app/finance/history/')
        corpo_limpeza = tela_limpeza.content.decode('utf-8', 'replace')
        conferir('Apagar definitivamente' in corpo_limpeza, 'dono vê a opção destrutiva')
        conferir(
            'Apagar definitivamente' not in navegador_secretaria.get(
                f'/app/finance/?start={inicio}&end={fim}',
            ).content.decode('utf-8', 'replace'),
            'secretária não vê a opção destrutiva',
        )
        recusado = navegador_dono.post(
            '/app/finance/history/delete/',
            {'confirmation': 'APAGA', 'understand': 'on'},
        )
        conferir(recusado.status_code == 400, 'texto incorreto recusa a exclusão')
        conferir(Receivable.objects.filter(tenant=tenant).exists(), 'confirmação errada preserva os dados')
        apagado = navegador_dono.post(
            '/app/finance/history/delete/',
            {'confirmation': 'APAGAR', 'understand': 'on'},
        )
        conferir(apagado.status_code == 302, 'confirmação dupla executa a exclusão')
        conferir(not Receivable.objects.filter(tenant=tenant).exists(), 'todas as cobranças são apagadas')
        conferir(not Payment.objects.filter(tenant=tenant).exists(), 'todos os pagamentos são apagados')
        conferir(
            not FinancialAdjustment.objects.filter(tenant=tenant).exists(),
            'todos os ajustes são apagados',
        )
        conferir(Patient.objects.filter(id=paciente.id).exists(), 'a exclusão preserva o paciente')
        conferir(Encounter.objects.filter(id=encontro.id).exists(), 'a exclusão preserva o prontuário')
        if outro_tenant:
            conferir(
                outro_antes == (
                    Receivable.objects.filter(tenant=outro_tenant).count(),
                    Payment.objects.filter(tenant=outro_tenant).count(),
                    FinancialAdjustment.objects.filter(tenant=outro_tenant).count(),
                ),
                'a exclusão preserva o financeiro de outra clínica',
            )
        conferir(
            AuditEvent.objects.filter(
                tenant=tenant, action='finance.history_permanently_deleted',
            ).exists(),
            'a exclusão definitiva deixa registro de auditoria',
        )
    finally:
        transaction.set_rollback(True)


print('---')
if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)
print('OK: exportação, documento fiscal, repasse e limpeza financeira completos.')
