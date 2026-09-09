from django.contrib import messages
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render

from tenancy.permissions import CapabilityRequiredView

from . import targets
from .models import Notification
from .services import mark_all_read, mark_read


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
        return render(request, 'notifications/list.html', {
            'rows': _rows(notifications),
            'unread_count': self._mine().filter(read_at__isnull=True).count(),
        })


class NotificationMarkReadView(TenantScopedView):
    def post(self, request, notification_id):
        notification = get_object_or_404(self._mine(), id=notification_id)
        mark_read(notification)
        return redirect('notifications:list')


class NotificationMarkAllReadView(TenantScopedView):
    def post(self, request):
        quantas = mark_all_read(request.access_context.tenant_id, request.user)
        if quantas:
            messages.success(
                request, f'{quantas} notificação(ões) marcada(s) como lida(s).',
            )
        else:
            messages.info(request, 'Não havia notificação não lida.')
        return redirect('notifications:list')


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
            return redirect('notifications:list')
        if not targets.exists(notification):
            # O alvo pode ter sido descartado depois do aviso — rascunho
            # apagado, exportação vencida. Mandar para um 404 seria pior
            # que dizer o que houve.
            mark_read(notification)
            messages.warning(
                request,
                'O que este aviso apontava não existe mais. Foi marcado como lido.',
            )
            return redirect('notifications:list')
        mark_read(notification)
        return redirect(url)
