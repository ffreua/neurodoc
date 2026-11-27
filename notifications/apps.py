from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = 'notifications'

    def ready(self):
        from django.contrib.auth.signals import user_logged_out

        user_logged_out.connect(_sair_tira_o_aparelho, dispatch_uid='notifications.push.sair')


def _sair_tira_o_aparelho(sender, request, user, **kwargs):
    """Quem sai por "Sair" para de receber avisos naquele aparelho.

    O `nd-pwa.js` cancela a inscrição no navegador e manda o endereço dela
    junto com o formulário de sair (`nd_push_endpoint`); aqui sai a linha.
    Só do próprio usuário, e só a daquele endereço: os outros aparelhos da
    pessoa continuam recebendo. A sessão que **vence** sem "Sair" não passa
    por aqui, de propósito — senão a pessoa teria de religar os avisos a
    cada sessão vencida, e o aviso não traz dado de paciente.
    """
    endpoint = request.POST.get('nd_push_endpoint', '') if request is not None else ''
    if user is None or not endpoint:
        return
    from .models import PushSubscription

    PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()
