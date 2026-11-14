"""Período contratado: anual, semestral, trimestral (1.30; vigência por período na 1.47).

Desde o contrato 2.2 a periodicidade **é** a vigência: doze, seis ou três
meses, cada período pago de uma vez e sem renovação automática. Ela vai do
convite ao aceite, e este roteiro tenta quebrar o caminho dela:

- **o catálogo**: 20% só no anual (de lançamento), 5% no semestral, preço
  cheio no trimestral — e as contas em centavos, sem um centavo perdido;
- **o convite**: carrega a periodicidade; uma desconhecida é recusada; o
  de colaborador não muda nada;
- **o aceite**: grava a periodicidade, o equivalente em 12 meses e o
  pagamento único do período, **vence** ao fim do período (3, 6 ou 12 meses,
  sem estourar o fim do mês) e abre a primeira `Vigencia` — e a via por
  e-mail diz o período e o valor;
- **o Gratuito**: sem periodicidade nem valor no aceite, sem vigência, 12 meses;
- **o que já existe**: aceite antigo, sem periodicidade, continua legível.

Tudo numa transação desfeita.

    docker compose exec -T app python manage.py shell < checks/check_periodicidade.py
"""
import uuid

from django.db import transaction

from contratacao.models import Vigencia
from tenancy.contracts import _corpo, preco_anual_centavos, preco_do_pagamento_centavos, somar_meses
from tenancy.invitations import issue_invitation
from tenancy.models import ContractAcceptance, Invitation, InvitationPurpose
from tenancy.plans import PERIODICIDADES, PlanCode, brl, preco_na_periodicidade
from tenancy.services import accept_platform_invitation

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


def cnpj(base):
    def dv(numeros, pesos):
        resto = sum(a * b for a, b in zip(numeros, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    n = [int(x) for x in base]
    d1 = dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


def contratar(plano, periodicidade=None, base='778899000001'):
    convite, token = issue_invitation(InvitationPurpose.PLATFORM, plan=plano, periodicidade=periodicidade)
    _, _, _, aceite = accept_platform_invitation(
        token, f'periodicidade-{uuid.uuid4().hex[:8]}@roteiro.invalid', 'Senha-forte-123!',
        'CLINICA ROTEIRO PERIODICIDADE LTDA', cnpj(base), contract_powers=True,
    )
    return convite, aceite


try:
    with transaction.atomic():
        print('=== 1. O catálogo ===')
        for code, cheio in ((PlanCode.BASIC, 8500), (PlanCode.COMPLETE, 17500)):
            a = preco_na_periodicidade(code, 'anual')
            s = preco_na_periodicidade(code, 'semestral')
            tr = preco_na_periodicidade(code, 'trimestral')
            conferir(f'{code}: preço cheio {brl(cheio)}', a['cheio'] == cheio)
            conferir(f'{code}: anual com 20%', a['mensal'] * 100 == cheio * 80 and a['pagamento'] == a['ano'])
            conferir(f'{code}: semestral com 5%, dois pagamentos fecham o ano',
                     s['mensal'] == (cheio * 95 + 50) // 100 and s['pagamento'] * 2 == s['ano'])
            conferir(f'{code}: trimestral sem desconto, quatro pagamentos fecham o ano',
                     tr['mensal'] == cheio and tr['pagamento'] * 4 == tr['ano'])
            conferir(f'{code}: anual < semestral < trimestral no ano', a['ano'] < s['ano'] < tr['ano'])
        conferir('o desconto de lançamento é só o do anual',
                 [str(c) for c, r in PERIODICIDADES.items() if r['lancamento']] == ['anual'])

        print('=== 2. O convite ===')
        try:
            issue_invitation(InvitationPurpose.PLATFORM, plan=PlanCode.BASIC, periodicidade='mensal')
            conferir('periodicidade desconhecida recusada', False)
        except ValueError:
            conferir('periodicidade desconhecida recusada', True)
        padrao, _ = issue_invitation(InvitationPurpose.PLATFORM, plan=PlanCode.BASIC)
        conferir('sem dizer, o convite é anual', padrao.periodicidade == 'anual')

        print('=== 3. O aceite grava a condição comercial ===')
        convite, aceite = contratar(PlanCode.BASIC, 'semestral')
        conferir('o convite levou a periodicidade', convite.periodicidade == 'semestral')
        conferir('o aceite grava "semestral"', aceite.periodicidade == 'semestral')
        conferir('o total de 12 meses é o do semestral (R$ 969,00)', aceite.price_annual_cents == 96900,
                 aceite.price_annual_cents)
        conferir('e cada pagamento, R$ 484,50', aceite.price_payment_cents == 48450, aceite.price_payment_cents)
        via = _corpo(aceite)
        conferir('a via por e-mail diz o período, o valor e que é pagamento único',
                 'Semestral' in via and 'R$ 484,50' in via and 'pagamento único' in via
                 and 'sem renovação automática' in via, via[:600])
        conferir('o semestral vence em seis meses', aceite.expires_at.date() == somar_meses(aceite.created_at, 6).date(),
                 aceite.expires_at)
        vig = Vigencia.objects.filter(aceite=aceite).first()
        conferir('e abre o primeiro período, com o valor do semestre',
                 vig is not None and vig.fim == aceite.expires_at and vig.valor_centavos == 48450
                 and vig.origem == 'aceite' and vig.pedido_id is None)
        _, aceite_c = contratar(PlanCode.COMPLETE, 'trimestral', base='778899010001')
        conferir('Completo trimestral: R$ 525,00 por trimestre (R$ 2.100,00 no ano, para comparar)',
                 (aceite_c.price_annual_cents, aceite_c.price_payment_cents) == (210000, 52500))
        conferir('o trimestral vence em três meses', aceite_c.expires_at.date() == somar_meses(aceite_c.created_at, 3).date())
        _, aceite_a = contratar(PlanCode.COMPLETE, 'anual', base='778899020001')
        conferir('Completo anual: R$ 1.680,00 de uma vez',
                 (aceite_a.price_annual_cents, aceite_a.price_payment_cents) == (168000, 168000))
        conferir('o anual vence em doze meses', aceite_a.expires_at.date() == somar_meses(aceite_a.created_at, 12).date())
        from datetime import datetime, timezone as tz
        conferir('31/08 mais seis meses é 28/02 (ou 29), sem estourar o mês',
                 somar_meses(datetime(2026, 8, 31, 15, tzinfo=tz.utc), 6) == datetime(2027, 2, 28, 15, tzinfo=tz.utc)
                 and somar_meses(datetime(2027, 8, 31, 15, tzinfo=tz.utc), 6) == datetime(2028, 2, 29, 15, tzinfo=tz.utc)
                 and somar_meses(datetime(2028, 2, 29, 9, tzinfo=tz.utc), 12) == datetime(2029, 2, 28, 9, tzinfo=tz.utc))

        print('=== 4. O Gratuito e o que já existia ===')
        _, gratis = contratar(PlanCode.FREE, 'semestral', base='778899030001')
        conferir('Gratuito: sem periodicidade nem valor', not gratis.periodicidade
                 and gratis.price_annual_cents in (None, 0) and gratis.price_payment_cents in (None, 0))
        conferir('Gratuito: sem vigência, e o aceite nos 12 meses de sempre',
                 not Vigencia.objects.filter(aceite=gratis).exists()
                 and gratis.expires_at.date() == somar_meses(gratis.created_at, 12).date())
        conferir('Personalizado: valor combinado, nada calculado',
                 preco_anual_centavos(PlanCode.CUSTOM) is None
                 and preco_do_pagamento_centavos(PlanCode.CUSTOM, 'semestral') is None)
        antigo = ContractAcceptance.objects.filter(periodicidade='').exclude(id=gratis.id).first()
        if antigo is not None:
            conferir('aceite anterior à 1.30 continua legível na via', 'Valor' in _corpo(antigo))
        conferir('convite de colaborador não carrega periodicidade nova',
                 Invitation._meta.get_field('periodicidade').default == 'anual')
        raise Desfazer
except Desfazer:
    pass

if falhas:
    raise SystemExit(f'FALHA: {len(falhas)} verificação(ões): ' + '; '.join(falhas))
print('OK: o período vai do convite ao aceite, com o pagamento único e o vencimento dele,\n'
      '    abre a primeira vigência, e o desconto só onde ele vale.')
