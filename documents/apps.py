from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    name = 'documents'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        user_logged_in.connect(_encerra_identificacao_do_portal, dispatch_uid='documents.portal_no_login')


def _encerra_identificacao_do_portal(sender, request, user, **kwargs):
    """Entrar no sistema encerra a identificação aberta no portal.

    O `login` do Django preserva os dados da sessão quando não havia
    usuário antes, e por isso a identificação do paciente sobrevivia ao
    login de quem trabalha na clínica, no mesmo navegador. Em 2026-10-18
    isso apareceu no uso real: o médico testou o portal com o próprio
    cadastro, entrou no sistema noutra aba, e a página do portal continuou
    dizendo "Paciente identificado" -- enquanto o envio, feito com o
    formulário aberto antes do login, era recusado pelo token CSRF, que o
    login troca. Quem entra no sistema é outra pessoa, ou a mesma noutro
    papel, e nenhuma das duas deve herdar a identificação do paciente.
    """
    from . import portal

    if request is not None and hasattr(request, 'session'):
        portal.clear(request)
        request.session.pop('portal_exames_enviados', None)
