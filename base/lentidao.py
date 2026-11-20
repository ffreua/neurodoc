"""Registro das telas lentas: o tempo de servidor de cada resposta acima do limite.

Por que existe: o log da aplicação não guarda tempo de requisição, e a
estimativa de capacidade de 2026-11-20 teve de ser montada com medida
local. Isto dá a medida real, contínua, de produção, e o console mostra
(`/instalacao/telas-lentas/`).

O custo, que foi a pergunta do titular: duas leituras de relógio e um
contador de consultas por requisição — microssegundos. Gravar acontece
**só** acima do limite, e acrescenta uns milissegundos a uma resposta que
já levou centenas. Qualquer falha ao gravar é engolida: medir nunca pode
derrubar a tela que está sendo medida.
"""
import logging
import time

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

#: Dias que um registro fica. Tendência, não histórico.
RETENCAO_DIAS = 30


class _Contador:
    """Conta as consultas da requisição pelo gancho do Django.

    `connection.queries` só existe com `DEBUG`; o gancho vale em produção e
    custa uma chamada de função por consulta.
    """

    def __init__(self):
        self.total = 0

    def __call__(self, execute, sql, params, many, context):
        self.total += 1
        return execute(sql, params, many, context)


class TelasLentasMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limite = getattr(settings, 'TELAS_LENTAS_MS', 500) or 0
        if limite <= 0:
            return self.get_response(request)
        contador = _Contador()
        inicio = time.perf_counter()
        with connection.execute_wrapper(contador):
            response = self.get_response(request)
        ms = int((time.perf_counter() - inicio) * 1000)
        # Stream (SSE do chat, da IA) devolve a resposta antes de terminar: o
        # tempo dele é o da conexão aberta, não o de uma tela.
        if ms >= limite and not getattr(response, 'streaming', False):
            self._gravar(request, response, ms, contador.total)
        return response

    @staticmethod
    def _gravar(request, response, ms, consultas):
        try:
            from .models import TelaLenta

            match = getattr(request, 'resolver_match', None)
            rota = (match.view_name if match and match.view_name else '(sem rota)')[:150]
            TelaLenta.objects.create(
                rota=rota, metodo=request.method[:10], status=response.status_code,
                milissegundos=min(ms, 2_147_483_647), consultas=consultas,
            )
        except Exception:                                   # noqa: BLE001
            logger.warning('telas lentas: não foi possível registrar', exc_info=True)


def apagar_antigas():
    """Apaga os registros com mais de `RETENCAO_DIAS`. Devolve quantos."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import TelaLenta

    corte = timezone.now() - timedelta(days=RETENCAO_DIAS)
    apagados, _ = TelaLenta.objects.filter(criada_em__lt=corte).delete()
    return apagados


def resumo(dias=7):
    """Por rota, nos últimos `dias`: ocorrências, mediana, p95, máximo, consultas.

    Calculado em Python sobre poucas linhas (só o que passou do limite), para
    não depender de `percentile_cont` nem de extensão no banco.
    """
    from collections import defaultdict
    from datetime import timedelta

    from django.utils import timezone

    from .models import TelaLenta

    desde = timezone.now() - timedelta(days=dias)
    por_rota = defaultdict(list)
    for rota, metodo, ms, consultas, quando in (
        TelaLenta.objects.filter(criada_em__gte=desde)
        .values_list('rota', 'metodo', 'milissegundos', 'consultas', 'criada_em')
    ):
        por_rota[(rota, metodo)].append((ms, consultas, quando))
    linhas = []
    for (rota, metodo), itens in por_rota.items():
        tempos = sorted(i[0] for i in itens)
        n = len(tempos)
        linhas.append({
            'rota': rota, 'metodo': metodo, 'ocorrencias': n,
            'mediana': tempos[n // 2], 'p95': tempos[min(n - 1, int(n * 0.95))], 'maximo': tempos[-1],
            'consultas': round(sum(i[1] for i in itens) / n),
            'ultima': max(i[2] for i in itens),
        })
    linhas.sort(key=lambda linha: (linha['ocorrencias'], linha['p95']), reverse=True)
    return linhas
