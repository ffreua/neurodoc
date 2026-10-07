"""Busca de códigos: CID-10 e TUSS, do catálogo local.

As duas ficam na mesma tela porque é a mesma tarefa — descobrir o código
para escrever num pedido, num laudo ou numa hipótese —, e separá-las
obrigaria o médico a lembrar qual das duas abas do navegador tinha qual.

**As duas leem o catálogo local**, e a tela diz de onde ele veio. O
CID-10 é uma carga versionada da OMS; a TUSS é espelhada da ANS pelo
worker, semanalmente (`catalogs.tasks.sync_tuss`).

A alternativa — consultar a ANS a cada busca — foi tentada e descartada:
a ANS leva ~80 segundos por página de 25 itens. Uma chamada síncrona a
partir daqui não falharia em desenvolvimento, onde a busca é uma só;
prenderia a tela no tempo da ANS em produção, com o médico esperando.
Quem fala com serviço externo é o worker, que pode tentar de novo.

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


class CatalogView(CapabilityRequiredView):
    """Base das views de catálogo.

    `required_capability = None` é decisão, e não esquecimento: CID-10, TUSS
    e CMED são **catálogos públicos**, iguais para toda clínica, sem nenhum
    dado de paciente. Exigir capacidade clínica aqui tiraria da secretária a
    conferência de apresentação que ela faz com a farmácia ao telefone, e do
    gestor a consulta de código para faturamento — sem proteger nada, porque
    não há o que proteger nestas tabelas.

    A porta que ainda vale é a do `TenantMiddleware`: `/app/` devolve 404 a
    quem não tem vínculo ativo. Quem **prescreve** com o código continua
    sendo quem tem capacidade clínica; isto aqui só procura texto.
    """

    required_capability = None


class CodeSearchView(CatalogView):
    """A tela. A busca em si acontece nos dois endpoints abaixo."""

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


class DiagnosisSearchAPI(CatalogView):
    """CID-10, da carga local. Responde em milissegundos e sem rede."""

    def get(self, request):
        resultados = selectors.search_diagnosis_codes(request.GET.get('q', ''))
        return JsonResponse({'ok': True, 'results': resultados})


class ProcedureSearchAPI(CatalogView):
    """TUSS, do espelho local sincronizado da ANS.

    Sem release sincronizada, responde `ok: false` com a instrução — e não
    uma lista vazia, que se leria como "esse código não existe".
    """

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


class MedicationSearchAPI(CatalogView):
    """Autocomplete de medicamento, da lista da CMED/Anvisa.

    A secretária confere apresentação ao atender o telefone da farmácia; o
    motivo de não exigir capacidade está em `CatalogView`.
    """

    def get(self, request):
        return JsonResponse({'results': selectors.search_medications(request.GET.get('q', ''))})


class MunicipalitySearchAPI(CatalogView):
    """Autocomplete de município, do catálogo do IBGE.

    Serve à naturalidade do paciente, que a secretária preenche no
    cadastro — daí não exigir capacidade clínica, pelo mesmo motivo de
    `CatalogView`.

    Devolve lista vazia quando o catálogo não foi importado, e a tela
    continua aceitando texto digitado: o autocomplete é conveniência, e
    paciente nascido fora do Brasil não cabe em lista nenhuma.
    """

    def get(self, request):
        return JsonResponse({'results': selectors.search_municipalities(
            request.GET.get('q', ''), uf=request.GET.get('uf', ''),
        )})
