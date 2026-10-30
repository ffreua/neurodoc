"""Telas da agenda de exames.

**Fora da área TISS de propósito.** A agenda é da recepção, o dia
inteiro: ela não pede o segundo fator a cada dez minutos (o requisito 83 do
A9 é do faturamento) e não some quando o TISS é desligado na instalação. O
que ela exige é o contrato — plano com o módulo e clínica liberada —, que
chega como a capacidade `EXAMES_AGENDAR`.

GET nunca muda nada. A tela da reserva mostra o mínimo administrativo:
paciente, horário, procedimento, cobrança. Nada do prontuário.
"""

from datetime import date, timedelta

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from patients.models import Patient, PatientCoverage
from tenancy.permissions import Capability, CapabilityRequiredView

from . import services
from .forms import BloqueioForm, JanelaForm, RecursoForm, RemarcarForm, ReservaForm
from .models import Bloqueio, Cobranca, EstadoReserva, Janela, Recurso, Reserva


class ExamesView(CapabilityRequiredView):
    required_capability = Capability.EXAMES_AGENDAR


def _data(texto, padrao):
    try:
        return date.fromisoformat(texto) if texto else padrao
    except ValueError:
        return padrao


def _uuid_ok(texto):
    import uuid

    try:
        uuid.UUID(str(texto))
        return True
    except ValueError:
        return False


class AgendaView(ExamesView):
    def get(self, request):
        tenant_id = request.access_context.tenant_id
        recursos = list(services.recursos_da_clinica(tenant_id))
        rid = request.GET.get('recurso')
        recurso = next((r for r in recursos if str(r.id) == rid), recursos[0] if recursos else None)
        dia = _data(request.GET.get('dia'), timezone.localdate())
        contexto = {
            'recursos': recursos, 'recurso': recurso, 'dia': dia,
            'anterior': dia - timedelta(days=1), 'proximo': dia + timedelta(days=1),
            'hoje': timezone.localdate(),
            'pode_configurar': request.access_context.can(Capability.EXAMES_CONFIGURAR),
            # Vindo da ficha ("Agendar exame"), o paciente segue nos links
            # dos horários livres e o formulário já abre com ele.
            'paciente': Patient.objects.filter(id=request.GET.get('paciente'), tenant_id=tenant_id).first()
            if _uuid_ok(request.GET.get('paciente')) else None,
        }
        if recurso is not None:
            reservas = list(services.reservas_do_dia(recurso, dia))
            for r in reservas:
                r.da_vespera = timezone.localtime(r.inicio).date() < dia
                r.ate_amanha = timezone.localtime(r.fim).date() > dia
            contexto.update({
                'janelas': services.janelas_que_cruzam(recurso, dia),
                'reservas': reservas,
                'livres': services.horarios_livres(recurso, dia),
                'bloqueios': Bloqueio.objects.filter(recurso=recurso, inicio__lt=timezone.make_aware(
                    timezone.datetime.combine(dia + timedelta(days=1), timezone.datetime.min.time())),
                    fim__gt=timezone.make_aware(timezone.datetime.combine(dia, timezone.datetime.min.time()))),
            })
        return render(request, 'agenda_exames/agenda.html', contexto)


def _recurso(request, pk):
    return get_object_or_404(Recurso, id=pk, tenant_id=request.access_context.tenant_id)


class ReservaNovaView(ExamesView):
    def _contexto(self, request, recurso, form, paciente):
        return {'recurso': recurso, 'form': form, 'paciente': paciente}

    def _paciente(self, request, pid):
        if not pid or not _uuid_ok(pid):
            return None
        return Patient.objects.filter(id=pid, tenant_id=request.access_context.tenant_id).first()

    def get(self, request, pk):
        recurso = _recurso(request, pk)
        paciente = self._paciente(request, request.GET.get('paciente'))
        inicio = request.GET.get('inicio', '')
        inicial = {'duracao': recurso.duracao_padrao, 'codigo_tuss': recurso.codigo_tuss,
                   'descricao': recurso.descricao_tuss, 'paciente': paciente.id if paciente else None}
        if inicio:
            try:
                instante = timezone.localtime(timezone.datetime.fromisoformat(inicio))
                inicial.update({'data': instante.date(), 'hora': instante.time().replace(second=0)})
            except ValueError:
                pass
        form = ReservaForm(initial=inicial, tenant_id=recurso.tenant_id, paciente=paciente)
        return render(request, 'agenda_exames/reserva_nova.html', self._contexto(request, recurso, form, paciente))

    def post(self, request, pk):
        recurso = _recurso(request, pk)
        paciente = self._paciente(request, request.POST.get('paciente'))
        form = ReservaForm(request.POST, tenant_id=recurso.tenant_id, paciente=paciente)
        if not form.is_valid() or paciente is None:
            if paciente is None:
                form.add_error(None, 'Escolha o paciente.')
            return render(request, 'agenda_exames/reserva_nova.html', self._contexto(request, recurso, form, paciente))
        d = form.cleaned_data
        cobertura = None
        if d['cobertura']:
            cobertura = PatientCoverage.objects.filter(id=d['cobertura'], patient=paciente,
                                                       tenant_id=recurso.tenant_id).first()
        try:
            reserva = services.reservar(
                request.access_context, request.user, recurso, paciente, form.inicio(), duracao=d['duracao'],
                codigo_tuss=d['codigo_tuss'], descricao=d['descricao'], solicitante=d['solicitante'],
                cobranca=d['cobranca'], cobertura=cobertura, observacao=d['observacao'],
                encaixe=d['encaixe'], motivo_encaixe=d['motivo_encaixe'],
            )
        except services.ReservaRecusada as exc:
            form.add_error(None, str(exc))
            return render(request, 'agenda_exames/reserva_nova.html', self._contexto(request, recurso, form, paciente))
        messages.success(request, f'{recurso.nome} marcado para {timezone.localtime(reserva.inicio):%d/%m às %H:%M}.')
        return redirect('agenda_exames:reserva', pk=reserva.id)


class ReservaView(ExamesView):
    def _reserva(self, request, pk):
        return get_object_or_404(
            Reserva.objects.select_related('recurso', 'paciente', 'executante', 'solicitante',
                                           'cobertura__plan__insurer'),
            id=pk, tenant_id=request.access_context.tenant_id,
        )

    def get(self, request, pk):
        from finance.models import Receivable
        from tiss.models import Configuracao, Guia, ProfissionalTiss

        reserva = self._reserva(request, pk)
        ctx = request.access_context
        local = timezone.localtime(reserva.inicio)
        return render(request, 'agenda_exames/reserva.html', {
            'reserva': reserva,
            'cobranca_financeira': Receivable.objects.filter(reserva_exame=reserva).first(),
            'guias': Guia.objects.filter(reserva_exame=reserva).order_by('-created_at'),
            'profissionais': ProfissionalTiss.objects.filter(tenant_id=ctx.tenant_id, ativo=True).order_by('nome'),
            'coberturas': reserva.paciente.coverages.select_related('plan__insurer').order_by('-starts_on'),
            'remarcar_form': RemarcarForm(initial={'data': local.date(), 'hora': local.time().replace(second=0)}),
            'pode_guia': ctx.can(Capability.TISS_PREPARE) and Configuracao.objects.filter(ativo=True).exists(),
            'pode_faltar': reserva.inicio <= timezone.now(),
            'formas': Cobranca.choices,
        })

    def post(self, request, pk):
        from tiss.models import ProfissionalTiss

        reserva = self._reserva(request, pk)
        ctx, acao, dados = request.access_context, request.POST.get('acao'), request.POST
        try:
            if acao in ('confirmada', 'chegou', 'faltou', 'cancelada'):
                services.mudar_estado(ctx, request.user, reserva, acao, dados.get('motivo', ''))
                messages.success(request, f'Exame: {EstadoReserva(acao).label.lower()}.')
            elif acao == 'realizar':
                pid = dados.get('executante')
                executante = ProfissionalTiss.objects.filter(id=pid, tenant_id=ctx.tenant_id).first() \
                    if _uuid_ok(pid) else None
                _, cobranca = services.realizar(ctx, request.user, reserva, executante)
                if cobranca is None:
                    messages.warning(request, 'Exame registrado como realizado, mas não há honorário cadastrado para '
                                              'ele: a cobrança não foi criada. Cadastre o valor em Convênios e valores.')
                else:
                    messages.success(request, f'Exame realizado. Cobrança de R$ {cobranca.charged_amount} criada.')
            elif acao == 'remarcar':
                form = RemarcarForm(dados)
                if not form.is_valid():
                    raise services.ReservaRecusada('Informe a nova data e o novo horário.')
                services.remarcar(ctx, request.user, reserva, form.inicio(),
                                  encaixe=form.cleaned_data['encaixe'],
                                  motivo_encaixe=form.cleaned_data['motivo_encaixe'])
                messages.success(request, 'Exame remarcado.')
            elif acao == 'cobranca':
                cid = dados.get('cobertura')
                cobertura = PatientCoverage.objects.filter(id=cid, tenant_id=ctx.tenant_id).first() \
                    if _uuid_ok(cid) else None
                services.definir_cobranca(ctx, request.user, reserva, dados.get('cobranca'), cobertura)
                messages.success(request, 'Forma de cobrança gravada.')
            else:
                raise Http404
        except services.ReservaRecusada as exc:
            messages.error(request, str(exc))
        return redirect('agenda_exames:reserva', pk=reserva.id)


# ------------------------------------------------------------------ configuração

class ConfigView(ExamesView):
    required_capability = Capability.EXAMES_CONFIGURAR


class RecursosView(ConfigView):
    def get(self, request):
        return render(request, 'agenda_exames/recursos.html', {
            'recursos': services.recursos_da_clinica(request.access_context.tenant_id, incluir_inativos=True),
        })


class RecursoView(ConfigView):
    def _render(self, request, recurso, form, janela_form=None, bloqueio_form=None):
        return render(request, 'agenda_exames/recurso.html', {
            'recurso': recurso, 'form': form,
            'janela_form': janela_form or JanelaForm(), 'bloqueio_form': bloqueio_form or BloqueioForm(),
            'janelas': recurso.janelas.all() if recurso else [],
            'bloqueios': recurso.bloqueios.filter(fim__gte=timezone.now()).order_by('inicio') if recurso else [],
        })

    def get(self, request, pk=None):
        recurso = _recurso(request, pk) if pk else None
        return self._render(request, recurso, RecursoForm(instance=recurso, tenant_id=request.access_context.tenant_id))

    def post(self, request, pk=None):
        from audit.services import record_audit_event

        tenant_id = request.access_context.tenant_id
        recurso = _recurso(request, pk) if pk else None
        acao = request.POST.get('acao', 'gravar')
        if acao == 'janela' and recurso:
            jf = JanelaForm(request.POST)
            if jf.is_valid():
                janela = jf.save(commit=False)
                janela.tenant_id, janela.recurso = tenant_id, recurso
                janela.save()
                messages.success(request, 'Horário incluído.')
                return redirect('agenda_exames:recurso', pk=recurso.id)
            return self._render(request, recurso, RecursoForm(instance=recurso, tenant_id=tenant_id), janela_form=jf)
        if acao == 'remover_janela' and recurso:
            Janela.objects.filter(id=request.POST.get('janela'), recurso=recurso).delete() \
                if _uuid_ok(request.POST.get('janela')) else None
            messages.success(request, 'Horário removido. Os exames já marcados continuam.')
            return redirect('agenda_exames:recurso', pk=recurso.id)
        if acao == 'bloqueio' and recurso:
            bf = BloqueioForm(request.POST)
            if bf.is_valid():
                try:
                    _, conflitos = services.criar_bloqueio(request.access_context, request.user, recurso,
                                                           bf.cleaned_data['inicio'], bf.cleaned_data['fim'],
                                                           bf.cleaned_data['motivo'])
                except services.ReservaRecusada as exc:
                    bf.add_error(None, str(exc))
                else:
                    msg = 'Bloqueio gravado.'
                    if conflitos:
                        msg += f' Atenção: {conflitos} exame(s) já marcado(s) nesse período continuam marcados — remarque-os.'
                    messages.success(request, msg)
                    return redirect('agenda_exames:recurso', pk=recurso.id)
            return self._render(request, recurso, RecursoForm(instance=recurso, tenant_id=tenant_id), bloqueio_form=bf)
        if acao == 'remover_bloqueio' and recurso:
            Bloqueio.objects.filter(id=request.POST.get('bloqueio'), recurso=recurso).delete() \
                if _uuid_ok(request.POST.get('bloqueio')) else None
            messages.success(request, 'Bloqueio removido.')
            return redirect('agenda_exames:recurso', pk=recurso.id)
        form = RecursoForm(request.POST, instance=recurso, tenant_id=tenant_id)
        if not form.is_valid():
            return self._render(request, recurso, form)
        obj = form.save(commit=False)
        obj.tenant_id = tenant_id
        obj.save()
        record_audit_event(request.user, tenant_id, f'agenda_exames.recurso_{"alterado" if recurso else "criado"}',
                           object_type='recurso_exame', object_id=obj.id, outcome='success')
        messages.success(request, 'Agenda gravada.' + ('' if recurso else ' Agora inclua os horários de atendimento.'))
        return redirect('agenda_exames:recurso', pk=obj.id)


def reverse_agenda(recurso, dia):
    return f"{reverse('agenda_exames:agenda')}?recurso={recurso.id}&dia={dia.isoformat()}"
