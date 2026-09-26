from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import render

from .context import build_access_context
from .models import TenantStatus

#: Métodos que só leem. A regra da organização congelada é sobre escrita,
#: e o verbo é o critério certo: a alternativa seria marcar view por view,
#: e a view esquecida é justamente a que ninguém percebe.
SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})

#: Caminhos que continuam abertos numa clínica congelada, apesar de
#: escreverem. Marcar uma notificação como lida é estado do **usuário**,
#: não da clínica: trancá-lo encheria o sino de avisos que a pessoa não
#: tem como baixar, sem proteger dado nenhum.
#:
#: Entrar, sair e trocar de organização não aparecem aqui porque vivem em
#: `/accounts/`, fora do alcance deste middleware — quem está numa clínica
#: congelada continua tendo como sair dela.
#: `/app/mensagens/lida/` entra pela mesma razão, e só ela: marcar a
#: conversa como lida zera um contador do **usuário**. O envio de mensagem
#: (`/app/mensagens/<id>/enviar/`) fica de fora de propósito — é escrita de
#: dado da clínica, e numa clínica congelada nada é criado. A separação de
#: prefixo no `teamchat/urls.py` existe exatamente para permitir esta
#: distinção aqui.
ALWAYS_ALLOWED_PREFIXES = ('/app/notifications/', '/app/mensagens/lida/')


class TenantMiddleware:
    """Resolves and attaches request.access_context for the `/app/` area.

    Every other path is left alone here: `/health/`, `/static/`, `/admin/`
    and `/technical-docs/` have their own dedicated protection, and public
    routes (landing, auth, onboarding) do not need a tenant.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.access_context = None
        if not request.path_info.startswith('/app/'):
            return self.get_response(request)
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        # Cadastrou-se e ainda nao clicou no link do e-mail.
        #
        # Esta pessoa caia no `raise Http404` de tres linhas abaixo, porque
        # a condicao seguinte exigia `email_verified_at is not None` para
        # oferecer a saida: quem mais precisava de orientacao era
        # exatamente quem nao a recebia. O sintoma enganava --  a senha
        # funciona, o login responde 302, e a primeira tela depois de
        # entrar e um "Not Found" cru, que nao diz que falta uma etapa nem
        # como cumpri-la. Quem recebeu isso concluiu que a conta nao tinha
        # sido criada.
        #
        # 403 e nao 404: aqui a recusa e sobre o estado da conta, e
        # escondar a existencia de `/app/` de alguem que acabou de se
        # cadastrar nao protege nada.
        if request.user.email_verified_at is None:
            return render(request, 'accounts/email_verification_required.html', status=403)
        if not request.session.get('tenant_id'):
            # Autenticado e verificado, mas sem organizacao escolhida nesta
            # sessao do navegador (login novo, ou link profundo aberto
            # antes de escolher uma) -- manda escolher e volta para ca, em
            # vez de um 404 sem saida.
            return redirect_to_login(request.get_full_path(), login_url='accounts:tenant-picker')
        context = build_access_context(request)
        if context is None:
            raise Http404
        request.access_context = context

        # ------------------------------------------ organização inativa
        #
        # Encerrada: a porta fecha, e a tela **explica**. Um 404 aqui seria
        # tecnicamente suficiente e humanamente inútil: quem está do outro
        # lado é um médico cuja clínica foi desligada, e ele precisa saber
        # que o prontuário continua guardado e a quem pedir a exportação.
        if context.tenant_status == TenantStatus.CLOSED:
            return render(request, 'tenancy/tenant_closed.html', status=403)

        # Suspensa: congela. Ler segue livre; escrever é recusado aqui, num
        # lugar só, e não em cada view -- a view que esquecesse a
        # verificação seria a que ninguém testaria.
        if (
            context.tenant_status == TenantStatus.SUSPENDED
            and request.method not in SAFE_METHODS
            and not request.path_info.startswith(ALWAYS_ALLOWED_PREFIXES)
        ):
            return render(request, 'tenancy/tenant_suspended.html', status=403)

        return self._sem_cache(self.get_response(request))

    @staticmethod
    def _sem_cache(response):
        """Nenhuma tela de `/app/` fica guardada no navegador.

        Sem cabeçalho, o navegador aplica cache heurístico e o botão
        Voltar reexibe a página **depois do logout** — a lista de
        pacientes do médico anterior aparece para quem sentar no mesmo
        computador do consultório. `Vary: Cookie`, que a sessão já põe,
        resolve o cache compartilhado e não resolve este: o histórico do
        navegador é do navegador.

        Aqui, e não em cada view, pelo mesmo motivo do congelamento da
        clínica suspensa logo acima: a view que esquecesse a linha seria
        justamente a que ninguém testaria. Respostas que já declararam a
        própria política passam intactas — a foto do paciente é servida
        com `private, max-age=300` de propósito, e sobrescrevê-la aqui
        faria o navegador rebaixar a mesma imagem a cada rolagem da
        lista.
        """
        if not response.has_header('Cache-Control'):
            response['Cache-Control'] = 'private, no-store, max-age=0'
        return response
