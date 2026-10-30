"""Telas da guia TISS.

**A tela da guia não carrega prontuário.** O contexto é a guia, os itens, o
nome do paciente e a carteira — nada do atendimento além da ligação
administrativa (de que horário a guia nasceu). A indicação clínica é o
único campo clínico, vai à operadora na guia, e só o médico a escreve
(`guias.registrar_indicacao`); a recepção a vê porque é ela quem imprime e
envia a guia.

GET nunca cria nem muda: gerar, fechar, cancelar e revisar são POST.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from audit.services import record_audit_event
from patients.models import Patient
from tenancy.permissions import Capability

from . import guias, lotes, terminologia
from .forms_guia import GuiaForm, IndicacaoForm, ItemForm, NovaGuiaForm
from .models import EstadoGuia, Guia, ItemGuia, TipoGuia
from .views import TissView


def _guia(request, pk):
    return get_object_or_404(
        Guia.objects.select_related(
            'paciente', 'cobertura__plan__insurer', 'credenciamento__prestador', 'credenciamento__operadora',
            'executante', 'solicitante', 'indicacao_por',
        ),
        id=pk, tenant_id=request.access_context.tenant_id,
    )


def _uuid(texto):
    import uuid

    try:
        uuid.UUID(str(texto))
        return True
    except ValueError:
        return False


def _horarios_do_paciente(tenant_id, paciente):
    from scheduling.models import Appointment

    desde = timezone.now() - timezone.timedelta(days=120)
    return list(
        Appointment.objects.filter(tenant_id=tenant_id, patient=paciente, starts_at__gte=desde)
        .exclude(status__in=['cancelled', 'no_show']).order_by('-starts_at')[:30]
    )


class GuiaListaView(TissView):
    """As guias da clínica, com filtro e paginação."""

    def get(self, request):
        qs = (
            Guia.objects.filter(tenant_id=request.access_context.tenant_id)
            .select_related('paciente', 'credenciamento__operadora')
            .annotate(total=Sum('itens__valor_total'))
            .order_by('-data_emissao', '-created_at')
        )
        estado = request.GET.get('estado', '')
        if estado in EstadoGuia.values:
            qs = qs.filter(estado=estado)
        tipo = request.GET.get('tipo', '')
        if tipo in TipoGuia.values:
            qs = qs.filter(tipo=tipo)
        paciente = None
        pid = request.GET.get('paciente')
        if pid:
            paciente = Patient.objects.filter(id=pid, tenant_id=request.access_context.tenant_id).first()                 if _uuid(pid) else None
            if paciente is None:
                raise Http404
            qs = qs.filter(paciente=paciente)
        termo = (request.GET.get('q') or '').strip()
        if termo:
            from patients.naming import normalizar_nome

            qs = qs.filter(Q(numero_prestador=termo) | Q(carteira=termo)
                           | Q(paciente__full_name__icontains=normalizar_nome(termo)))
        pagina = Paginator(qs, 25).get_page(request.GET.get('pagina'))
        total = sum((g.total or 0 for g in pagina), 0)
        return render(request, 'tiss/guias.html', {
            'pagina': pagina, 'estados': EstadoGuia.choices, 'tipos': TipoGuia.choices,
            'filtro': {'estado': estado, 'tipo': tipo, 'q': termo}, 'total_pagina': total,
            'paciente': paciente,
        })


class GuiaNovaView(TissView):
    """Escolher o tipo e o atendimento de origem; o POST cria a guia."""

    required_capability = Capability.TISS_PREPARE

    def _paciente(self, request):
        pid = request.GET.get('paciente') or request.POST.get('paciente')
        if not pid:
            from scheduling.models import Appointment

            aid = request.GET.get('appointment') or request.POST.get('appointment')
            appt = Appointment.objects.filter(id=aid, tenant_id=request.access_context.tenant_id).first() if aid else None
            if appt is None:
                raise Http404
            return appt.patient
        return get_object_or_404(Patient, id=pid, tenant_id=request.access_context.tenant_id)

    def get(self, request):
        try:
            paciente = self._paciente(request)
        except Exception:                                          # noqa: BLE001 - id inválido
            raise Http404
        horarios = _horarios_do_paciente(request.access_context.tenant_id, paciente)
        form = NovaGuiaForm(horarios=horarios, initial={'appointment': request.GET.get('appointment', '')})
        return render(request, 'tiss/guia_nova.html', {'form': form, 'paciente': paciente})

    def post(self, request):
        try:
            paciente = self._paciente(request)
        except Exception:                                          # noqa: BLE001
            raise Http404
        horarios = _horarios_do_paciente(request.access_context.tenant_id, paciente)
        form = NovaGuiaForm(request.POST, horarios=horarios)
        if not form.is_valid():
            return render(request, 'tiss/guia_nova.html', {'form': form, 'paciente': paciente})
        appt = next((a for a in horarios if str(a.id) == form.cleaned_data['appointment']), None)
        try:
            guia = guias.criar_guia(request.access_context, request.user, paciente,
                                    form.cleaned_data['tipo'], appointment=appt)
        except guias.GuiaRecusada as exc:
            form.add_error(None, str(exc))
            return render(request, 'tiss/guia_nova.html', {'form': form, 'paciente': paciente})
        messages.success(request, f'{guia.get_tipo_display()} nº {guia.numero_prestador} criada. Confira as pendências.')
        return redirect('tiss:guia', pk=guia.id)


class GuiaView(TissView):
    """Ver e preencher a guia."""

    def _contexto(self, request, guia, form=None, item_form=None, indicacao_form=None, item_em_edicao=None):
        ctx = request.access_context
        pode_preparar = ctx.can(Capability.TISS_PREPARE) and guia.editavel
        if form is None:
            form = GuiaForm(guia=guia)
        if item_form is None:
            item_form = ItemForm(versao=guia.versao_efetiva, tipo=guia.tipo,
                                 initial={'data_execucao': guia.data_emissao, 'tabela': '22'})
        pend = guias.pendencias(guia) if guia.editavel else []
        return {
            'guia': guia, 'itens': guia.itens.select_related('recebivel').order_by('sequencial'),
            'form': form, 'item_form': item_form,
            'indicacao_form': indicacao_form or IndicacaoForm(initial={'indicacao_clinica': guia.indicacao_clinica}),
            'item_em_edicao': item_em_edicao,
            'pendencias': pend, 'pode_fechar': guia.editavel and not [p for p in pend if p.impede],
            'pode_preparar': pode_preparar,
            'pode_fechar_cap': ctx.can(Capability.TISS_CLOSE),
            'pode_indicar': ctx.can(Capability.READ_CLINICAL) and guia.editavel,
            'total': sum((i.valor_total for i in guia.itens.all()), 0),
            'revisoes': Guia.objects.filter(revisa=guia).order_by('-created_at'),
            'lote_ativo': lotes.lote_ativo_da_guia(guia),
            'pode_exportar': ctx.can(Capability.TISS_EXPORT),
            'rotulo': terminologia.rotulo,
        }

    def get(self, request, pk):
        guia = _guia(request, pk)
        return render(request, 'tiss/guia.html', self._contexto(request, guia))

    def post(self, request, pk):
        if not request.access_context.can(Capability.TISS_PREPARE):
            raise Http404
        guia = _guia(request, pk)
        if not guia.editavel:
            messages.error(request, 'Guia fechada não muda. Para corrigir, abra uma revisão.')
            return redirect('tiss:guia', pk=guia.id)
        form = GuiaForm(request.POST, guia=guia)
        if not form.is_valid():
            return render(request, 'tiss/guia.html', self._contexto(request, guia, form=form))
        alterada = form.save(commit=False)
        cob = alterada.cobertura
        if cob is not None and 'cobertura' in form.changed_data:
            # Trocar o convênio troca a carteira, que vem dele; a validade
            # também. Quem quiser outra, edita depois.
            alterada.carteira = (cob.member_number or '')[:20]
            alterada.validade_carteira = cob.ends_on
        alterada.save()
        record_audit_event(
            request.user, guia.tenant_id, 'tiss.guia_alterada', object_type='guia_tiss', object_id=guia.id,
            outcome='success', integrity_metadata={'campos': sorted(form.changed_data)},
        )
        messages.success(request, 'Guia gravada.')
        return redirect('tiss:guia', pk=guia.id)


class ItemView(TissView):
    """Incluir, alterar ou remover um procedimento realizado."""

    required_capability = Capability.TISS_PREPARE

    def post(self, request, pk, item_id=None):
        guia = _guia(request, pk)
        item = get_object_or_404(ItemGuia, id=item_id, guia=guia) if item_id else None
        if request.POST.get('acao') == 'remover' and item is not None:
            try:
                guias.remover_item(request.access_context, request.user, guia, item)
                messages.success(request, 'Procedimento removido.')
            except guias.GuiaRecusada as exc:
                messages.error(request, str(exc))
            return redirect('tiss:guia', pk=guia.id)
        form = ItemForm(request.POST, versao=guia.versao_efetiva, tipo=guia.tipo)
        if form.is_valid():
            try:
                guias.gravar_item(request.access_context, request.user, guia, form.cleaned_data, item=item)
                messages.success(request, 'Procedimento gravado.')
                return redirect('tiss:guia', pk=guia.id)
            except guias.GuiaRecusada as exc:
                form.add_error(None, str(exc))
        return render(request, 'tiss/guia.html',
                      GuiaView()._contexto(request, guia, item_form=form, item_em_edicao=item))


class IndicacaoView(TissView):
    """A indicação clínica — só quem lê prontuário (o médico) escreve."""

    def post(self, request, pk):
        if not request.access_context.can(Capability.READ_CLINICAL):
            raise Http404
        guia = _guia(request, pk)
        if not guia.editavel:
            raise Http404
        form = IndicacaoForm(request.POST)
        if form.is_valid():
            guias.registrar_indicacao(request.access_context, request.user, guia,
                                      form.cleaned_data['indicacao_clinica'])
            guia.save(update_fields=['indicacao_clinica', 'indicacao_por', 'indicacao_em', 'updated_at'])
            record_audit_event(
                request.user, guia.tenant_id, 'tiss.indicacao_registrada', object_type='guia_tiss',
                object_id=guia.id, outcome='success',
                integrity_metadata={'preenchida': bool(guia.indicacao_clinica)},
            )
            messages.success(request, 'Indicação clínica gravada.')
        return redirect('tiss:guia', pk=guia.id)


class TransicaoView(TissView):
    """Fechar, cancelar ou abrir revisão — quem fecha guia."""

    required_capability = Capability.TISS_CLOSE

    def post(self, request, pk, acao):
        guia = _guia(request, pk)
        ctx = request.access_context
        try:
            if acao == 'fechar':
                guias.fechar(ctx, request.user, guia)
                messages.success(request, f'Guia nº {guia.numero_prestador} fechada.')
            elif acao == 'cancelar':
                guias.cancelar(ctx, request.user, guia, request.POST.get('motivo'))
                messages.success(request, f'Guia nº {guia.numero_prestador} cancelada.')
            elif acao == 'revisar':
                nova = guias.abrir_revisao(ctx, request.user, guia)
                messages.success(request, f'Revisão aberta: guia nº {nova.numero_prestador}.')
                return redirect('tiss:guia', pk=nova.id)
            else:
                raise Http404
        except guias.GuiaRecusada as exc:
            messages.error(request, str(exc))
        return redirect('tiss:guia', pk=guia.id)


class ImprimirView(TissView):
    """O PDF da guia no modelo oficial em papel da ANS."""

    def get(self, request, pk):
        from .impressao import pdf_da_guia

        guia = _guia(request, pk)
        conteudo = pdf_da_guia(guia)
        record_audit_event(
            request.user, guia.tenant_id, 'tiss.guia_impressa', object_type='guia_tiss', object_id=guia.id,
            outcome='success', integrity_metadata={'estado': guia.estado},
        )
        resposta = HttpResponse(conteudo, content_type='application/pdf')
        resposta['Content-Disposition'] = f'inline; filename="guia-{guia.numero_prestador}.pdf"'
        resposta['Cache-Control'] = 'private, no-store'
        resposta['X-Content-Type-Options'] = 'nosniff'
        return resposta
