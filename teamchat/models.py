"""Mensagens internas da equipe — a janela que abre ao lado do sino.

**Por que um app novo, e não `communications`.** Aquele app fala com quem
está *fora*: paciente por e-mail e SMS, com consentimento, outbox,
reconciliação de entrega e credencial de provedor por clínica. Aqui não
sai nada da instalação — é conversa entre pessoas que já entraram no
sistema, e a entrega é a própria tela. Juntar os dois obrigaria toda
mensagem de corredor a passar pelo outbox, e todo ajuste no outbox a
arriscar o chat.

**Não é prontuário, e a tela diz isso.** O que se escreve aqui não entra
no `Encounter`, não é assinado e não tem guarda de vinte anos. O risco é
real e conhecido: gente vai digitar nome de paciente e conduta no chat. O
que o sistema faz a respeito, e o que deliberadamente não faz:

- o conteúdo **nunca** aparece no sino nem em `Notification`. O
  cabeçalho mostra um número, não um trecho — `notifications.services`
  já proíbe conteúdo clínico ali, e a razão é a mesma: aquela linha é
  lida em toda requisição.
- o conteúdo fica no PostgreSQL como qualquer dado da clínica, isolado
  por inquilino pelas mesmas duas camadas do resto (`TenantModel` e a
  checagem de vínculo ativo em cada view).
- nada é apagado por conta própria. Retenção e expurgo são decisão de
  quem responde pela LGPD na clínica (P-06/P-07 em `docs/decisions.md`),
  e inventar um prazo aqui seria escolher no lugar deles.

**Só conversa de duas pessoas, por enquanto.** É o que foi pedido:
médico com secretária, médico com médico, secretária com secretária,
gestor com quem for. O esquema já é N-ário — a conversa tem uma tabela de
participantes, não duas colunas —, então grupo com nome entra depois
preenchendo `title` e deixando `direct_key` vazio, sem migração de dados.
Modelar como par de colunas hoje é o que obrigaria a reescrever tudo
amanhã.
"""

from django.db import models

from base.models import TenantModel

#: Teto do corpo da mensagem. Recado de corredor, não laudo: o campo é
#: `TextField` para não truncar acento em contagem de bytes, e o limite
#: existe para que um texto colado sem querer não vire uma linha de
#: megabytes replicada no stream de todo mundo.
MAX_BODY = 4000


def direct_key_for(user_a_id, user_b_id):
    """A chave canônica da conversa entre duas pessoas.

    Ordenada, e não "quem abriu primeiro": sem isso, o médico abrindo a
    secretária e a secretária abrindo o médico criariam duas conversas
    diferentes, cada um escrevendo numa que o outro não lê. O defeito não
    aparece em teste de uma pessoa só — aparece no primeiro dia de uso.
    """
    a, b = sorted([str(user_a_id), str(user_b_id)])
    return f'{a}:{b}'


class Conversation(TenantModel):
    #: `user_a:user_b` em ordem crescente para conversa de duas pessoas;
    #: vazio para grupo (que ainda não existe). Único por inquilino
    #: **quando preenchido** — a condição no índice é o que permite os
    #: dois usos na mesma coluna sem um segundo modelo.
    direct_key = models.CharField(max_length=73, blank=True)
    title = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    #: Denormalizado para ordenar a lista de conversas sem um `MAX` por
    #: linha. Escrito junto da mensagem, na mesma transação.
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'direct_key'],
                condition=~models.Q(direct_key=''),
                name='teamchat_conversation_direct_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'last_message_at'], name='teamchat_conv_recent_idx'),
        ]

    def __str__(self):
        return self.title or self.direct_key or str(self.id)


class ConversationMember(TenantModel):
    """Quem participa, e quanto falta ler.

    `unread_count` é denormalizado de propósito. A alternativa —
    `COUNT(*) WHERE created_at > last_read_at` — roda no processador de
    contexto, que monta o cabeçalho de **toda** requisição de `/app/`:
    seria uma varredura da tabela de mensagens por página aberta. Assim a
    badge do cabeçalho é uma soma sobre as poucas linhas desta tabela que
    são do usuário, por índice.

    O preço é o de todo denormalizado: um número que pode divergir da
    contagem real se alguém escrever mensagem fora de `services.send`.
    Por isso só `services` escreve aqui — e `checks/check_mensagens.py`
    confere que a soma bate com a contagem de verdade.

    A linha não é apagada quando o vínculo é revogado. Quem autoriza a
    leitura é o vínculo ativo, verificado a cada requisição
    (`tenancy.context`), e não esta linha; apagá-la destruiria o outro
    lado da conversa de quem continua na clínica.
    """

    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='members')
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='teamchat_memberships')
    unread_count = models.PositiveIntegerField(default=0)
    last_read_at = models.DateTimeField(null=True, blank=True)
    #: Até quando esta pessoa apagou a conversa. O que veio antes some da
    #: janela **dela**; a do colega continua igual até as 72 horas apagarem
    #: de vez (`services.RETENCAO_HORAS`). Apagar a cópia do outro por um
    #: clique seu seria decidir pelo histórico de outra pessoa.
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['conversation', 'user'], name='teamchat_member_conv_user_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'user'], name='teamchat_member_user_idx'),
        ]

    def __str__(self):
        return f'{self.user_id}@{self.conversation_id}'


class Message(TenantModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='messages')
    sender = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    body = models.TextField(max_length=MAX_BODY)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'conversation', 'created_at'], name='teamchat_msg_thread_idx'),
        ]
        # `id` como critério de desempate, e não só `created_at`: o
        # carimbo tem microssegundo e o empate é improvável, mas uma
        # ordenação sem desempate é instável entre consultas — a mesma
        # página recarregada pode trocar duas linhas de lugar, e num chat
        # isso é a conversa mudando de sentido.
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.sender_id}: {self.body[:40]}'
