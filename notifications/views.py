from django.contrib import messages
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from tenancy.permissions import CapabilityRequiredView

from . import push, targets
from .models import Notification
from .services import clear_all, mark_all_read, mark_read


class TenantScopedView(CapabilityRequiredView):
    """Notificações do próprio usuário — qualquer vínculo ativo tem as suas.

    `required_capability = None` é decisão, não esquecimento: a consulta já
    é filtrada por `user=request.user`, e o que a caixa mostra é o que o
    sistema mandou para aquela pessoa. Exigir capacidade aqui esconderia do
    médico o aviso de que a IA terminou, e da secretária o de que uma
    entrega falhou.

    Quem decide se a pessoa **recebe** um aviso é `notify_capability`, na
    criação. É lá que a caixa e a tela deixam de divergir.
    """

    required_capability = None

    def _mine(self):
        return Notification.objects.filter(
            tenant_id=self.request.access_context.tenant_id, user=self.request.user,
        )


def _voltar(request):
    """Para onde voltar depois de uma ação feita pelo sino.

    O sino está em toda tela, e quem marca como lida ou limpa a caixa por
    ele quer continuar onde estava — mandar para a central tirava a pessoa
    do atendimento ou da agenda por um clique que não pedia isso. O
    formulário do sino manda o endereço da tela em `next`; a central não
    manda, e continua voltando para si.

    Só caminho do próprio site: `next` vem do cliente, e aceitá-lo cru
    faria do sino um redirecionador aberto.
    """
    destino = request.POST.get('next', '')
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ) and destino.startswith('/') and not destino.startswith('//'):
        return redirect(destino)
    return redirect('notifications:list')


def _rows(notifications):
    """Cada notificação com o endereço e o rótulo do botão.

    Resolvido aqui e não no template porque o destino depende do
    `target_type`, e um template que decide isso vira uma cadeia de `if`
    que ninguém revisa.
    """
    linhas = []
    for n in notifications:
        alvo = targets.target_for(n)
        linhas.append({
            'obj': n,
            'url': targets.url_for(n),
            'action': alvo.action if alvo else '',
        })
    return linhas


class NotificationListView(TenantScopedView):
    def get(self, request):
        # As não lidas primeiro, e não só as mais recentes: uma caixa
        # ordenada só por data enterra o que falta fazer sob o que já foi
        # feito assim que o dia enche.
        #
        # `nulls_first` é obrigatório aqui. No PostgreSQL, `ORDER BY` de
        # coluna anulável põe o `NULL` no **fim** em ordem crescente — e
        # `read_at` nulo é exatamente a não lida. Sem isso a ordenação faz
        # o contrário do que se quer, e o defeito não aparece em teste de
        # conteúdo: as linhas estão todas lá, na ordem errada.
        notifications = self._mine().order_by(
            F('read_at').asc(nulls_first=True), '-created_at',
        )
        contexto = {
            'rows': _rows(notifications),
            'unread_count': self._mine().filter(read_at__isnull=True).count(),
            'push_ligado': push.ligado(),
        }
        if contexto['push_ligado']:
            contexto['push_chave'] = push.chave_publica()
            contexto['push_aparelhos'] = list(
                request.user.push_subscriptions.order_by('-created_at')
            )
        return render(request, 'notifications/list.html', contexto)


class NotificationMarkReadView(TenantScopedView):
    def post(self, request, notification_id):
        notification = get_object_or_404(self._mine(), id=notification_id)
        mark_read(notification)
        return _voltar(request)


class NotificationMarkAllReadView(TenantScopedView):
    def post(self, request):
        quantas = mark_all_read(request.access_context.tenant_id, request.user)
        if quantas:
            messages.success(
                request, f'{quantas} notificação(ões) marcada(s) como lida(s).',
            )
        else:
            messages.info(request, 'Não havia notificação não lida.')
        return _voltar(request)


class NotificationClearAllView(TenantScopedView):
    """Limpa a caixa inteira, lidas e não lidas.

    Só `POST`, e com confirmação na tela (`data-nd-confirm`): é a única
    ação desta caixa que não se desfaz.
    """

    def post(self, request):
        quantas = clear_all(request.access_context.tenant_id, request.user)
        if quantas:
            messages.success(request, f'{quantas} notificação(ões) removida(s) da caixa.')
        else:
            messages.info(request, 'A caixa já estava vazia.')
        return _voltar(request)


class NotificationOpenView(TenantScopedView):
    """Marca como lida e leva ao que precisa ser resolvido.

    Uma ação só, porque são a mesma: quem abre o que o aviso apontava já
    leu o aviso. Separar as duas obrigava a marcar como lida e depois
    procurar o destino à mão — que era o que a caixa pedia antes de
    existir link.

    `POST`, e não um link: marcar como lida altera estado, e um `GET` que
    altera estado é marcado como lido por qualquer coisa que pré-carregue
    endereços — o próprio navegador faz isso.
    """

    def post(self, request, notification_id):
        notification = get_object_or_404(self._mine(), id=notification_id)
        url = targets.url_for(notification)
        if url is None:
            mark_read(notification)
            messages.info(
                request,
                'Este aviso não tem uma tela para abrir. Foi marcado como lido.',
            )
            return _voltar(request)
        if not targets.exists(notification):
            # O alvo pode ter sido descartado depois do aviso — rascunho
            # apagado, exportação vencida. Mandar para um 404 seria pior
            # que dizer o que houve.
            mark_read(notification)
            messages.warning(
                request,
                'O que este aviso apontava não existe mais. Foi marcado como lido.',
            )
            return _voltar(request)
        mark_read(notification)
        return redirect(url)


# ------------------------------------------------------------------ avisos no celular

def _json(request):
    import json

    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


class PushView(TenantScopedView):
    """Base das rotas dos avisos no celular: `POST` de `fetch`, resposta JSON.

    Ficam em `/app/`, atrás do vínculo ativo, e não em `/accounts/`: o
    aviso existe para trabalho de clínica, e quem não tem vínculo nenhum
    não tem o que receber. O CSRF vale como em toda tela (o `fetch` manda o
    cabeçalho).
    """

    def dispatch(self, request, *args, **kwargs):
        if not push.ligado():
            from django.http import Http404

            raise Http404
        return super().dispatch(request, *args, **kwargs)


class PushInscreverView(PushView):
    def post(self, request):
        from django.http import JsonResponse

        from audit.services import record_audit_event

        aparelho = push.aparelho_do_navegador(request.META.get('HTTP_USER_AGENT', ''))
        try:
            push.inscrever(request.user, _json(request), aparelho)
        except push.InscricaoRecusada as exc:
            return JsonResponse({'erro': str(exc)}, status=400)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'notifications.push_ativado',
            integrity_metadata={'aparelho': aparelho},
        )
        return JsonResponse({'ok': True, 'aparelho': aparelho})


class PushRemoverView(PushView):
    """Tira um aparelho: o deste navegador (`endpoint` no corpo) ou um da
    lista (`id`), sempre só da própria pessoa."""

    def post(self, request):
        from django.http import JsonResponse

        from audit.services import record_audit_event

        dados = _json(request)
        consulta = request.user.push_subscriptions.all()
        if dados.get('endpoint'):
            consulta = consulta.filter(endpoint=dados['endpoint'])
        elif dados.get('id') or request.POST.get('id'):
            try:
                consulta = consulta.filter(pk=int(dados.get('id') or request.POST.get('id')))
            except (TypeError, ValueError):
                consulta = consulta.none()
        elif request.POST.get('todos') == '1':
            pass
        else:
            consulta = consulta.none()
        quantos = consulta.delete()[0]
        if quantos:
            record_audit_event(
                request.user, request.access_context.tenant_id, 'notifications.push_desativado',
                integrity_metadata={'aparelhos': quantos},
            )
        if request.content_type == 'application/json':
            return JsonResponse({'ok': True, 'removidos': quantos})
        messages.success(request, 'Avisos desligados no aparelho.' if quantos == 1
                         else f'Avisos desligados em {quantos} aparelhos.')
        return redirect('notifications:list')


class PushTestarView(PushView):
    """Manda um aviso de teste só para este navegador.

    Pelo worker, como todo aviso: o teste prova o caminho inteiro — chave,
    cifra, serviço de push e o worker do aparelho —, e não um atalho.
    """

    def post(self, request):
        from django.http import JsonResponse

        from .tasks import enviar_push_teste

        endpoint = _json(request).get('endpoint') or ''
        inscricao = request.user.push_subscriptions.filter(endpoint=endpoint).first()
        if inscricao is None:
            return JsonResponse({'erro': 'Este aparelho não está com os avisos ligados.'},
                                status=404)
        enviar_push_teste.delay(inscricao.pk)
        return JsonResponse({'ok': True})


class ComunicadoView(TenantScopedView):
    """O comunicado do console, por inteiro.

    Abre para quem o **recebeu** (tem a linha no sino, em qualquer clínica):
    o comunicado pode ser de uma clínica só, e quem não estava no público não
    tem por que lê-lo. Abrir marca como lida a linha desta clínica.
    """

    def get(self, request, comunicado_id):
        from django.http import Http404
        from django.utils import timezone

        from .models import Comunicado

        recebidas = Notification.objects.filter(
            user=request.user, target_type='comunicado', target_id=comunicado_id,
        )
        if not recebidas.exists():
            raise Http404
        comunicado = get_object_or_404(Comunicado, pk=comunicado_id)
        recebidas.filter(
            tenant_id=request.access_context.tenant_id, read_at__isnull=True,
        ).update(read_at=timezone.now())
        return render(request, 'notifications/comunicado.html', {'comunicado': comunicado})
