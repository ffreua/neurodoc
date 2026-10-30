"""Telas dos lotes: a fila do que faturar, o plano, o lote e o arquivo.

**O plano vem antes de qualquer lote.** A seleção — guias marcadas ou
"todas as filtradas" — vira um plano mostrado na tela: quantos lotes, de
qual operadora, tipo e versão, quantas guias e o total de cada um, e as
guias que **não** entram com o motivo. Só a confirmação cria; se a seleção
mudou entre ver e confirmar, nada é criado (`lotes.criar_lotes`).

GET nunca cria, gera nem muda estado. O download devolve o arquivo
gravado, conferido pelo SHA-256 — baixar de novo é o mesmo arquivo.
"""

import logging
from datetime import date

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from audit.services import record_audit_event
from tenancy.permissions import Capability

from . import lotes
from .models import (
    CicloFechamento, Credenciamento, EstadoLote, Guia, Lote, LoteGuia, ResultadoLote, TipoGuia,
)
from .views import TissView

log = logging.getLogger(__name__)

#: "Todas as filtradas" num clique: acima disto, filtre mais. O plano de
#: mil guias já são dez lotes na tela.
MAXIMO_SELECAO = 1000


def _data(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def _filtros(request, fonte):
    tenant_id = request.access_context.tenant_id
    f = {
        'credenciamento': fonte.get('credenciamento', ''), 'tipo': fonte.get('tipo', ''),
        'de': _data(fonte.get('de')), 'ate': _data(fonte.get('ate')),
        'q': (fonte.get('q') or '').strip(),
    }
    qs = lotes.elegiveis(tenant_id).annotate(valor=Sum('itens__valor_total'))
    cred = None
    if f['credenciamento']:
        cred = Credenciamento.objects.filter(tenant_id=tenant_id, id=f['credenciamento']).first() \
            if _uuid(f['credenciamento']) else None
        if cred is None:
            raise Http404
        qs = qs.filter(credenciamento=cred)
    if f['tipo'] in TipoGuia.values:
        qs = qs.filter(tipo=f['tipo'])
    if f['de']:
        qs = qs.filter(data_referencia__gte=f['de'])
    if f['ate']:
        qs = qs.filter(data_referencia__lte=f['ate'])
    if f['q']:
        from patients.naming import normalizar_nome

        qs = qs.filter(Q(numero_prestador=f['q']) | Q(carteira=f['q'])
                       | Q(paciente__full_name__icontains=normalizar_nome(f['q'])))
    return f, cred, qs.order_by('data_referencia', 'numero_prestador')


def _uuid(texto):
    import uuid

    try:
        uuid.UUID(str(texto))
        return True
    except ValueError:
        return False


def _aviso_de_ciclo(guia, inicio):
    """Procedimento de antes do período: a guia não é partida, mas avisa."""
    if not inicio:
        return ''
    datas = [i['data'] for i in guia.snapshot.get('itens', [])]
    if datas and min(datas) < inicio.isoformat():
        return 'tem procedimento antes do período (a guia entra inteira, pelo último dia)'
    return ''


class FilaView(TissView):
    """Guias fechadas que ainda não estão em lote."""

    def get(self, request):
        tenant_id = request.access_context.tenant_id
        f, cred, qs = _filtros(request, request.GET)
        pagina = Paginator(qs, 50).get_page(request.GET.get('pagina'))
        hoje = timezone.localdate()
        ciclos = []
        if cred is not None and cred.ciclo != CicloFechamento.MANUAL:
            atual = lotes.periodo_do_ciclo(cred.ciclo, hoje)
            ciclos = [('Período anterior', lotes.periodo_anterior(cred.ciclo, hoje)), ('Período atual', atual)]
        for g in pagina:
            g.aviso_ciclo = _aviso_de_ciclo(g, f['de'])
            g.recusa = lotes.motivo_de_recusa(g, checar_lote=False)
        return render(request, 'tiss/fila.html', {
            'pagina': pagina, 'filtro': f, 'credenciamento': cred,
            'credenciamentos': Credenciamento.objects.filter(tenant_id=tenant_id)
            .select_related('operadora', 'prestador').order_by('operadora__name'),
            'tipos': TipoGuia.choices, 'ciclos': ciclos,
            'total_filtro': qs.aggregate(t=Sum('itens__valor_total'))['t'] or 0,
            'pode_exportar': request.access_context.can(Capability.TISS_EXPORT),
            'maximo': MAXIMO_SELECAO,
        })


class PlanoView(TissView):
    """POST `ver`: monta o plano. POST `confirmar`: cria os lotes."""

    required_capability = Capability.TISS_EXPORT

    def _ids(self, request):
        if request.POST.get('todas') == '1':
            _, _, qs = _filtros(request, request.POST)
            ids = list(qs.values_list('id', flat=True)[:MAXIMO_SELECAO + 1])
            if len(ids) > MAXIMO_SELECAO:
                messages.error(request, f'Mais de {MAXIMO_SELECAO} guias no filtro. Filtre por operadora ou período.')
                return None
            return ids
        return [i for i in request.POST.getlist('guia') if _uuid(i)]

    def post(self, request):
        periodo = (_data(request.POST.get('de')), _data(request.POST.get('ate')))
        ids = self._ids(request)
        if ids is None:
            return redirect(reverse('tiss:fila'))
        if not ids:
            messages.error(request, 'Marque ao menos uma guia.')
            return redirect(reverse('tiss:fila'))
        if request.POST.get('acao') == 'confirmar':
            try:
                criados = lotes.criar_lotes(request.access_context, request.user, ids,
                                            request.POST.get('assinatura', ''), periodo)
            except lotes.LoteRecusado as exc:
                messages.error(request, str(exc))
            else:
                numeros = ', '.join(lote.numero for lote in criados)
                messages.success(request, f'Lote{"s" if len(criados) > 1 else ""} {numeros} criado'
                                          f'{"s" if len(criados) > 1 else ""}. O arquivo está sendo gerado.')
                if len(criados) == 1:
                    return redirect('tiss:lote', pk=criados[0].id)
                return redirect('tiss:lotes')
        plano = lotes.planejar(request.access_context.tenant_id, ids)
        return render(request, 'tiss/lote_plano.html', {
            'plano': plano, 'ids': [str(g.id) for grupo in plano.grupos for g in grupo.guias]
            + [str(g.id) for g, _ in plano.recusadas],
            'periodo': periodo,
        })


class LoteListaView(TissView):
    def get(self, request):
        qs = (
            Lote.objects.filter(tenant_id=request.access_context.tenant_id)
            .select_related('credenciamento__operadora', 'credenciamento__prestador')
            .order_by('-created_at')
        )
        estado = request.GET.get('estado', '')
        if estado in EstadoLote.values:
            qs = qs.filter(estado=estado)
        situacao = request.GET.get('situacao', '')
        if situacao == 'nao_enviado':
            qs = qs.filter(estado=EstadoLote.PRONTO, enviado_em__isnull=True)
        elif situacao == 'sem_retorno':
            qs = qs.filter(enviado_em__isnull=False, resultado='')
        pagina = Paginator(qs, 25).get_page(request.GET.get('pagina'))
        return render(request, 'tiss/lotes.html', {
            'pagina': pagina, 'estados': EstadoLote.choices,
            'filtro': {'estado': estado, 'situacao': situacao},
        })


def _lote(request, pk):
    return get_object_or_404(
        Lote.objects.select_related('credenciamento__operadora', 'credenciamento__prestador',
                                    'solicitado_por', 'envio_registrado_por', 'resultado_por'),
        id=pk, tenant_id=request.access_context.tenant_id,
    )


class LoteView(TissView):
    def get(self, request, pk):
        lote = _lote(request, pk)
        participacoes = (
            LoteGuia.objects.filter(lote=lote).select_related('guia__paciente')
            .order_by('-ativo', 'guia__data_referencia', 'guia__numero_prestador')
        )
        return render(request, 'tiss/lote.html', {
            'lote': lote, 'participacoes': participacoes,
            'pode_exportar': request.access_context.can(Capability.TISS_EXPORT),
            'resultados': ResultadoLote.choices,
            'hoje': timezone.localdate(),
            'guias_fora': [p.guia for p in participacoes if p.ativo and p.guia.estado != 'fechada'],
        })

    def post(self, request, pk):
        if not request.access_context.can(Capability.TISS_EXPORT):
            raise Http404
        lote = _lote(request, pk)
        ctx, acao, dados = request.access_context, request.POST.get('acao'), request.POST
        try:
            if acao == 'tentar':
                lotes.tentar_de_novo(ctx, request.user, lote)
                messages.success(request, 'Geração reiniciada.')
            elif acao == 'enviar':
                lotes.registrar_envio(ctx, request.user, lote, _data(dados.get('enviado_em')), dados.get('protocolo'))
                messages.success(request, 'Envio registrado.')
            elif acao == 'retorno':
                lotes.registrar_resultado(ctx, request.user, lote, dados.get('resultado'), dados.get('observacao'))
                messages.success(request, 'Retorno registrado.')
            elif acao == 'cancelar':
                lotes.cancelar_lote(ctx, request.user, lote, dados.get('motivo'))
                messages.success(request, f'Lote {lote.numero} cancelado. As guias voltaram para a fila.')
            elif acao == 'liberar':
                guia = get_object_or_404(Guia, id=dados.get('guia'), tenant_id=ctx.tenant_id) \
                    if _uuid(dados.get('guia')) else None
                if guia is None:
                    raise Http404
                lotes.liberar_guia(ctx, request.user, lote, guia, dados.get('motivo'))
                messages.success(request, f'Guia {guia.numero_prestador} liberada para reapresentação.')
            else:
                raise Http404
        except lotes.LoteRecusado as exc:
            messages.error(request, str(exc))
        return redirect('tiss:lote', pk=lote.id)


class LoteArquivoView(TissView):
    """O arquivo gravado. Mesmo lote, mesmos bytes, quantas vezes for."""

    required_capability = Capability.TISS_EXPORT

    def get(self, request, pk):
        lote = _lote(request, pk)
        if lote.estado not in (EstadoLote.PRONTO, EstadoLote.CANCELADO) or not lote.arquivo:
            raise Http404
        try:
            dados = lotes.ler_arquivo(lote)
        except (lotes.ArquivoCorrompido, OSError):
            log.exception('tiss: arquivo do lote %s ilegível ou adulterado', lote.id)
            record_audit_event(request.user, lote.tenant_id, 'tiss.lote_arquivo_invalido',
                               object_type='lote_tiss', object_id=lote.id, outcome='failure')
            messages.error(request, 'O arquivo deste lote não confere com o registro. Avise o suporte; '
                                    'não envie este lote.')
            return redirect('tiss:lote', pk=lote.id)
        record_audit_event(
            request.user, lote.tenant_id, 'tiss.lote_baixado', object_type='lote_tiss', object_id=lote.id,
            outcome='success', integrity_metadata={'numero': lote.numero, 'sha256': lote.sha256},
        )
        resposta = HttpResponse(dados, content_type='application/xml; charset=ISO-8859-1')
        nome = f'lote-{lote.numero}-ans{lote.credenciamento.operadora.ans_registration}-v{lote.versao}.xml'
        resposta['Content-Disposition'] = f'attachment; filename="{nome}"'
        resposta['Cache-Control'] = 'private, no-store'
        resposta['X-Content-Type-Options'] = 'nosniff'
        return resposta
