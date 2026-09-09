"""Para onde cada notificação leva.

`Notification` sempre guardou `target_type` e `target_id`, e nada os
usava: a caixa avisava que havia algo a fazer e não dizia onde. Quem
recebia "Entrega pendente — verifique o cadastro de contato do paciente"
tinha de adivinhar qual paciente e procurá-lo na lista.

O destino é resolvido **na leitura**, e não gravado como URL na criação:
uma rota gravada num banco envelhece junto com as rotas, e o dia em que um
caminho muda transforma a caixa inteira numa lista de links quebrados.

Cada tipo declara também o modelo, para a tela distinguir "o alvo sumiu"
de "o link está errado". Documento descartado, pedido apagado e exportação
vencida acontecem, e o aviso continua na caixa de quem o recebeu.
"""

from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class Target:
    #: Rota nomeada, com o identificador como único argumento posicional.
    url_name: str
    #: `app_label.ModelName` do que a rota abre. Usado só para conferir se
    #: o alvo ainda existe.
    model: str
    #: O que o botão diz. Específico por tipo porque "Abrir" não informa:
    #: o verbo é a diferença entre revisar um pedido e baixar um arquivo.
    action: str


REGISTRY = {
    'document_request': Target(
        'documents:request-detail', 'documents.DocumentRequest', 'Revisar solicitação',
    ),
    'medical_document': Target(
        'documents:medical-detail', 'documents.MedicalDocument', 'Abrir documento',
    ),
    'chat_session': Target(
        'ai:chat-session-detail', 'ai.ChatSession', 'Abrir conversa',
    ),
    'report_export': Target(
        'reporting:export-detail', 'reporting.ReportExport', 'Abrir exportação',
    ),
    # O aviso de contato faltando aponta para a **ficha do paciente**, e não
    # para o horário ou o documento que não puderam ser entregues: a ação
    # pedida é cadastrar telefone ou e-mail, e é ali que ela acontece. O que
    # falhou fica no `context`, para a linha dizer o que ficou por entregar.
    'patient': Target(
        'patients:detail', 'patients.Patient', 'Abrir ficha do paciente',
    ),
}


def target_for(notification):
    return REGISTRY.get(notification.target_type)


def url_for(notification):
    """Endereço do alvo, ou `None` quando não há para onde ir.

    `None` em três casos, e a tela trata os três igual: tipo desconhecido
    (notificação antiga, de um tipo que saiu do produto), sem
    identificador, ou rota que não resolve.
    """
    target = target_for(notification)
    if target is None or notification.target_id is None:
        return None
    try:
        return reverse(target.url_name, args=[notification.target_id])
    except NoReverseMatch:
        return None


def exists(notification):
    """Se o alvo ainda está no banco, no inquilino da notificação.

    Uma consulta, feita só quando alguém clica — não ao montar a lista. A
    alternativa seria uma consulta por linha em toda página, para
    responder uma pergunta que quase sempre é "sim".
    """
    target = target_for(notification)
    if target is None or notification.target_id is None:
        return False
    from django.apps import apps

    model = apps.get_model(target.model)
    return model.objects.filter(
        id=notification.target_id, tenant_id=notification.tenant_id,
    ).exists()
