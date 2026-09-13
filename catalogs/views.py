"""Busca de códigos: CID-10 e TUSS, do catálogo local.

As duas ficam na mesma tela porque é a mesma tarefa — descobrir o código
para escrever num pedido, num laudo ou numa hipótese —, e separá-las
obrigaria o médico a lembrar qual das duas abas do navegador tinha qual.

**As duas leem o catálogo local**, e a tela diz de onde ele veio. O
CID-10 é uma carga versionada da OMS; a TUSS é espelhada da ANS pelo
worker, semanalmente (`catalogs.tasks.sync_tuss`).

A alternativa — consultar a ANS a cada busca — foi tentada e descartada:
em produção o processo web não tem saída para a internet (o `app` está em
`traefik_public` e `neurodoc_v1_internal`; quem tem egresso é o worker).
Uma chamada síncrona a partir daqui não falharia em desenvolvimento;
falharia no primeiro dia de produção, por timeout, com o médico esperando.

O espelho ainda resolve a desatualização melhor do que a consulta ao vivo:
a data da última sincronização fica visível na tela, e a busca continua
respondendo quando a ANS está fora.

Quem pode: qualquer vínculo ativo. Não há dado de paciente aqui — é
catálogo público —, e exigir capacidade clínica impediria a secretária de
conferir um código que o convênio pediu por telefone.
"""

from django.http import JsonResponse
from django.shortcuts import render

from tenancy.permissions import CapabilityRequiredView

from . import selectors
from .models import CatalogSystem


class CodeSearchView(CapabilityRequiredView):
    """A tela. A busca em si acontece nos dois endpoints abaixo."""

    required_capability = None

    def get(self, request):
        cid = selectors.active_release(CatalogSystem.CID10)
        tuss = selectors.active_release(CatalogSystem.TUSS)
        return render(request, 'catalogs/search.html', {
            'cid_release': cid,
            'cid_total': cid.diagnosis_codes.filter(active=True).count() if cid else 0,
            'tuss_release': tuss,
            'tuss_total': tuss.procedure_codes.count() if tuss else 0,
            # A release de amostra da semeadura tem seis linhas e nao e a
            # tabela da ANS. Dizer isso na tela evita que uma busca legitima
            # que nao acha nada seja lida como defeito.
            'tuss_sample': bool(tuss and tuss.version.startswith('SAMPLE')),
            'termo': request.GET.get('q', ''),
            'aba': 'tuss' if request.GET.get('aba') == 'tuss' else 'cid',
        })


class DiagnosisSearchAPI(CapabilityRequiredView):
    """CID-10, da carga local. Responde em milissegundos e sem rede."""

    required_capability = None

    def get(self, request):
        resultados = selectors.search_diagnosis_codes(request.GET.get('q', ''))
        return JsonResponse({'ok': True, 'results': resultados})


class ProcedureSearchAPI(CapabilityRequiredView):
    """TUSS, do espelho local sincronizado da ANS.

    Sem release sincronizada, responde `ok: false` com a instrução — e não
    uma lista vazia, que se leria como "esse código não existe".
    """

    required_capability = None

    def get(self, request):
        if selectors.active_release(CatalogSystem.TUSS) is None:
            return JsonResponse({
                'ok': False,
                'error': 'A tabela TUSS ainda não foi sincronizada nesta instalação. '
                         'Peça ao administrador do sistema para executar a sincronização.',
            })
        return JsonResponse({
            'ok': True, 'results': selectors.search_procedure_codes(request.GET.get('q', '')),
        })
