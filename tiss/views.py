"""Telas do faturamento TISS.

**Três chaves, conferidas aqui a cada requisição.** A capacidade
(`TISS_*`) já carrega duas — o plano inclui o TISS e a clínica foi liberada
(`tenancy.context`) —, e esta base confere a terceira, a da instalação
(`tiss.models.Configuracao`). Faltando qualquer uma, 404: quem não tem o
módulo não precisa saber que a tela existe (`CapabilityRequiredView`).

**Dez minutos sem uso pedem o segundo fator de novo — só nesta área.**
Requisito 83 do componente de Segurança e Privacidade do TISS (A9,
nov/2025). Decidido em 30/10/2026: vale na área TISS e não no NeuroDoc
inteiro, onde o prontuário aberto ao lado do paciente não pode cair a cada
dez minutos. A sessão do resto do sistema não é derrubada; a reconfirmação
é a mesma tela de `accounts:mfa-confirm`, que volta para onde se estava.
"""

from django.contrib import messages
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts import mfa
from audit.services import record_audit_event
from tenancy.permissions import Capability, CapabilityRequiredView

from . import versoes
from .forms import CredenciamentoForm, PrestadorForm, ProfissionalForm
from .models import Configuracao, Credenciamento, Prestador, ProfissionalTiss

#: Requisito 83 do A9: inatividade máxima na área TISS, em segundos.
INATIVIDADE_MAXIMA_SEGUNDOS = 600
ULTIMO_USO_SESSAO = 'tiss_ultimo_uso'


def _segundos_desde(iso):
    if not iso:
        return None
    instante = timezone.datetime.fromisoformat(iso)
    if timezone.is_naive(instante):
        instante = timezone.make_aware(instante)
    return (timezone.now() - instante).total_seconds()


class TissView(CapabilityRequiredView):
    required_capability = Capability.TISS_VIEW

    def dispatch(self, request, *args, **kwargs):
        context = request.access_context
        if context is None or not context.can(self.required_capability):
            raise Http404
        if not Configuracao.objects.filter(ativo=True).exists():
            raise Http404
        ocioso = _segundos_desde(request.session.get(ULTIMO_USO_SESSAO))
        reconfirmou = mfa.mfa_verified_recently(request, INATIVIDADE_MAXIMA_SEGUNDOS)
        if (ocioso is None or ocioso > INATIVIDADE_MAXIMA_SEGUNDOS) and not reconfirmou:
            request.session.pop(ULTIMO_USO_SESSAO, None)
            destino = None if request.method == 'GET' else _volta_segura(request)
            return mfa.redirect_to_mfa_confirm(request, destino)
        request.session[ULTIMO_USO_SESSAO] = timezone.now().isoformat()
        return super().dispatch(request, *args, **kwargs)


def _volta_segura(request):
    from django.urls import reverse

    return reverse('tiss:inicio')


class InicioView(TissView):
    def get(self, request):
        tenant_id = request.access_context.tenant_id
        return render(request, 'tiss/inicio.html', {
            'prestadores': Prestador.objects.filter(tenant_id=tenant_id).order_by('-ativo', 'nome'),
            'credenciamentos': (
                Credenciamento.objects.filter(tenant_id=tenant_id)
                .select_related('prestador', 'operadora').order_by('-ativo', 'operadora__name')
            ),
            'profissionais': ProfissionalTiss.objects.filter(tenant_id=tenant_id).order_by('-ativo', 'nome'),
            'pode_configurar': request.access_context.can(Capability.TISS_CONFIGURE),
            'versoes': versoes.VERSOES.values(),
        })


class _CadastroView(TissView):
    """Criar e editar um cadastro de configuração. Só quem configura."""

    required_capability = Capability.TISS_CONFIGURE
    modelo = None
    formulario = None
    titulo = ''
    evento = ''

    def _objeto(self, request, pk):
        if pk is None:
            return None
        return get_object_or_404(self.modelo, id=pk, tenant_id=request.access_context.tenant_id)

    def _render(self, request, form, objeto):
        return render(request, 'tiss/form.html', {
            'form': form, 'titulo': self.titulo, 'objeto': objeto,
        })

    def get(self, request, pk=None):
        objeto = self._objeto(request, pk)
        form = self.formulario(instance=objeto, tenant_id=request.access_context.tenant_id)
        return self._render(request, form, objeto)

    def antes_de_gravar(self, request, form, obj):
        pass

    def post(self, request, pk=None):
        objeto = self._objeto(request, pk)
        form = self.formulario(request.POST, instance=objeto, tenant_id=request.access_context.tenant_id)
        if not form.is_valid():
            return self._render(request, form, objeto)
        obj = form.save(commit=False)
        obj.tenant_id = request.access_context.tenant_id
        self.antes_de_gravar(request, form, obj)
        try:
            obj.save()
        except IntegrityError:
            form.add_error(None, 'Não foi possível gravar: já existe um cadastro igual nesta clínica.')
            return self._render(request, form, objeto)
        record_audit_event(
            request.user, request.access_context.tenant_id,
            f'{self.evento}_{"updated" if objeto else "created"}',
            object_type=self.modelo._meta.model_name, object_id=obj.id, outcome='success',
        )
        messages.success(request, f'{self.titulo} gravado.')
        return redirect('tiss:inicio')


class PrestadorView(_CadastroView):
    modelo, formulario, titulo, evento = Prestador, PrestadorForm, 'Prestador', 'tiss.prestador'


class ProfissionalView(_CadastroView):
    modelo, formulario, titulo, evento = (
        ProfissionalTiss, ProfissionalForm, 'Profissional', 'tiss.profissional',
    )


class CredenciamentoView(_CadastroView):
    modelo, formulario, titulo, evento = (
        Credenciamento, CredenciamentoForm, 'Credenciamento', 'tiss.credenciamento',
    )

    def antes_de_gravar(self, request, form, obj):
        """O aceite da versão histórica: quem declarou, quando e o motivo.

        Trocar para uma versão vigente apaga o aceite — ele dizia respeito
        àquela versão; voltar a uma histórica pede o aceite de novo.
        """
        motivo = (form.cleaned_data.get('aceite_motivo') or '').strip()
        if versoes.versao(obj.versao).historica:
            if motivo != obj.aceite_versao_motivo or not obj.aceite_versao_em:
                obj.aceite_versao_motivo = motivo[:255]
                obj.aceite_versao_em = timezone.now()
                obj.aceite_versao_por = request.user
        else:
            obj.aceite_versao_motivo, obj.aceite_versao_em, obj.aceite_versao_por = '', None, None
