"""O espelho da TUSS não esvazia a busca e guarda a vigência (1.30).

Até a 1.29 a versão tinha nome fixo, e a rodada semanal voltava a **única**
release ativa para rascunho e apagava os códigos antes de rebaixá-los — com
a ANS a ~80 s por página, a busca ficava vazia por horas todo domingo; com
um honorário apontando para um código (PROTECT), o `delete()` estourava e a
tabela parava de envelhecer. E todo código com data de fim era tratado como
encerrado, mesmo os que valem até 31/12/2026.

O roteiro simula a ANS (`_fetch_page`) e confere: a busca responde pela
ativa **durante** a rodada; o honorário segura o código antigo sem quebrar
nada; a substituída fica; conteúdo igual não cria release; a vigência é
gravada e lida pela data; e o rascunho da 1.29, se existir, é retomado.

Tudo dentro de uma transação desfeita no fim.

    docker compose exec -T app python manage.py shell < checks/check_tuss_vigencia.py
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import transaction

from catalogs.models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode
from catalogs.selectors import active_release, search_procedure_codes
from finance.models import FeeSchedule, PaymentCategory
from integrations import tuss
from tenancy.models import Tenant

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


def entrada(codigo, termo, inicio='2016-01-01', fim='-'):
    return tuss.TussEntry(code=codigo, description=termo, starts_on=inicio, ends_on=fim)


TABELA_A = [
    entrada('90000001', 'ELETROENCEFALOGRAMA DE ROTINA ROTEIRO'),
    entrada('90000002', 'ELETRONEUROMIOGRAFIA ROTEIRO', fim='2026-12-31'),
    entrada('90000003', 'POLISSONOGRAFIA ROTEIRO', fim='2020-06-30'),
]
TABELA_B = TABELA_A[:2] + [entrada('90000004', 'TERMO NOVO ROTEIRO', inicio='2026-10-01')]


def ans_simulada(tabela, durante=None):
    """Uma página com a tabela, depois página vazia (fim)."""
    def _pagina(http, table, pagina):
        if durante and pagina == 1:
            durante()
        return list(tabela) if pagina == 1 else []
    return _pagina


def rodar(tabela, durante=None):
    with patch.object(tuss, '_fetch_page', side_effect=ans_simulada(tabela, durante)), \
         patch.object(tuss.time, 'sleep'):
        return tuss.sync_incremental('tuss-roteiro')


try:
    with transaction.atomic():
        print('=== 1. Vigência lida pela data, não pela presença do fim ===')
        e = entrada('1', 'x', fim='2026-12-31')
        conferir('vale no último dia', e.in_force_on(date(2026, 12, 31)))
        conferir('não vale no dia seguinte', not e.in_force_on(date(2027, 1, 1)))
        conferir('"-" é vigência aberta', entrada('1', 'x').in_force_on(date(2030, 1, 1)))
        conferir('início futuro ainda não vale',
                 not entrada('1', 'x', inicio='2027-01-01').in_force_on(date(2026, 10, 30)))
        conferir('data quebrada vira nula, sem exceção', tuss._data_iso('31/12/2026') is None)

        print('=== 2. Uma release ativa já existe; o honorário aponta para um código dela ===')
        CatalogRelease.objects.filter(system=CatalogSystem.TUSS).update(
            status=CatalogReleaseStatus.SUPERSEDED)
        antiga = CatalogRelease.objects.create(
            system=CatalogSystem.TUSS, version='ANS-roteiro-antiga',
            status=CatalogReleaseStatus.ACTIVE, content_sha256='antiga',
        )
        from django.utils import timezone
        CatalogRelease.objects.filter(id=antiga.id).update(imported_at=timezone.now())
        codigo_antigo = ProcedureCode.objects.create(
            release=antiga, code='90000001', description='ELETROENCEFALOGRAMA ANTIGO',
            search_text='90000001 ELETROENCEFALOGRAMA ANTIGO',
        )
        tenant = Tenant.objects.order_by('created_at').first()
        honorario = FeeSchedule.objects.create(
            tenant=tenant, procedure=codigo_antigo, payment_category=PaymentCategory.PRIVATE,
            gross_amount=Decimal('100.00'), doctor_share_amount=Decimal('0.00'),
            effective_from=date(2026, 1, 1),
        )

        visto_durante = {}

        def olhar_busca():
            ativa = active_release(CatalogSystem.TUSS)
            visto_durante['ativa'] = ativa.version if ativa else None
            visto_durante['achou'] = bool(search_procedure_codes('ELETROENCEFALOGRAMA'))

        r = rodar(TABELA_A, durante=olhar_busca)

        print('=== 3. Durante a rodada, a busca responde pela ativa ===')
        conferir('a ativa continua ativa enquanto o rascunho é baixado',
                 visto_durante.get('ativa') == 'ANS-roteiro-antiga', str(visto_durante))
        conferir('e a busca acha o procedimento', visto_durante.get('achou'), str(visto_durante))

        print('=== 4. No fim, troca numa transação, sem apagar a antiga ===')
        nova = active_release(CatalogSystem.TUSS)
        antiga.refresh_from_db()
        conferir('rodada completa', r['completo'], str(r))
        conferir('a nova é a ativa', nova and nova.version.startswith('ANS-tuss-roteiro-'), str(nova))
        conferir('a antiga virou substituída', antiga.status == CatalogReleaseStatus.SUPERSEDED)
        conferir('o código da antiga continua no banco',
                 ProcedureCode.objects.filter(id=codigo_antigo.id).exists())
        honorario.refresh_from_db()
        conferir('o honorário continua apontando para ele', honorario.procedure_id == codigo_antigo.id)
        conferir('a assinatura do conteúdo foi gravada', len(nova.content_sha256) == 64)

        print('=== 5. A vigência foi gravada por código ===')
        enmg = ProcedureCode.objects.get(release=nova, code='90000002')
        psg = ProcedureCode.objects.get(release=nova, code='90000003')
        conferir('fim de vigência gravado', enmg.ends_on == date(2026, 12, 31), str(enmg.ends_on))
        conferir('início gravado', enmg.starts_on == date(2016, 1, 1))
        conferir('vence em 31/12/2026 e ainda vale hoje', enmg.active)
        conferir('o que venceu em 2020 está encerrado', not psg.active)
        conferir('"-" vira fim nulo',
                 ProcedureCode.objects.get(release=nova, code='90000001').ends_on is None)

        print('=== 6. Conteúdo igual não cria release ===')
        total_antes = CatalogRelease.objects.filter(system=CatalogSystem.TUSS).count()
        r2 = rodar(TABELA_A)
        conferir('a mesma continua ativa', active_release(CatalogSystem.TUSS).id == nova.id)
        conferir('o rascunho igual foi descartado',
                 CatalogRelease.objects.filter(system=CatalogSystem.TUSS).count() == total_antes)
        conferir('e não sobrou rascunho',
                 not CatalogRelease.objects.filter(system=CatalogSystem.TUSS,
                                                   status=CatalogReleaseStatus.DRAFT).exists())
        conferir('a rodada informa a versão que ficou', r2['versao'] == nova.version, str(r2))

        print('=== 7. Conteúdo diferente cria release nova ===')
        rodar(TABELA_B)
        terceira = active_release(CatalogSystem.TUSS)
        conferir('outra release ativa', terceira.id != nova.id)
        conferir('com o termo novo', ProcedureCode.objects.filter(release=terceira, code='90000004').exists())

        print('=== 8. O rascunho da 1.29 (nome sem data) é retomado, não abandonado ===')
        legado = CatalogRelease.objects.create(
            system=CatalogSystem.TUSS, version='ANS-tuss-roteiro',
            status=CatalogReleaseStatus.DRAFT,
        )
        conferir('a rodada continua o rascunho antigo', tuss._rascunho_da_rodada('tuss-roteiro').id == legado.id)

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Tudo certo.')
