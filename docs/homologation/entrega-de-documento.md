# A entrega do documento ao paciente

**Roteiros:** `checks/check_entrega_documento.py`, `checks/check_links_de_mensagem.py` ·
**Módulos:** `communications/services.py`, `communications/mail_backend.py`,
`communications/smsdev.py`, `communications/tasks.py`, `documents/views.py`

---

## 1. O que aconteceu

O médico emitiu um relatório com certificado digital e clicou em enviar ao
paciente. Recebeu **`Server Error (500)`** — com o documento já assinado,
que é o pior momento possível para uma falha, porque a parte irreversível
já tinha acontecido.

Depois o e-mail chegou. E o link dentro dele dizia **"inválido ou
expirado"**.

Eram dois sintomas da mesma cadeia, e quatro defeitos empilhados.

## 2. Os quatro defeitos

### 2-A. A mensagem não cabia no SMS

O mesmo texto servia aos dois canais. No e-mail ficava bem; no SMS dava
**221 caracteres** contra um limite de 160.

**Nunca coube.** Só não aparecia porque os pacientes anteriores tinham
apenas e-mail cadastrado — o primeiro paciente com telefone verificado
encontrou o defeito.

Agora há um texto por canal. O de SMS é **sem acento**, e isso não é
desleixo: um SMS só cabe em 160 caracteres enquanto estiver em GSM-7, e
basta um acento para a operadora passar a mensagem a UCS-2, onde o
segmento cai para **70** — com um link de 70 caracteres no corpo, a versão
acentuada não caberia em segmento nenhum.

A escolha entre o texto completo e o mínimo é feita medindo **o link
real**. `PUBLIC_BASE_URL` muda por instalação, e uma contagem fixa
quebraria na primeira que tivesse um domínio mais longo.

### 2-B. O erro era `ValueError`, que ninguém trata

Subiu por `_send`, por `deliver_document` e pela view até virar a tela de
erro.

Duas correções, e as duas são necessárias:

- `smsdev.send_sms` levanta `SmsSendFailed` — que o chamador já sabe
  tratar — em vez de `ValueError`;
- `_send` ganhou uma **rede final**: qualquer exceção inesperada vira
  entrega marcada como falha, registrada no log. Entrega é efeito
  colateral do que o sistema faz, nunca a coisa em si: uma falha ali tem
  de virar linha vermelha na lista de entregas, para alguém reenviar —
  nunca uma tela de erro sobre uma operação que já deu certo.

### 2-C. A transação envolvia todos os canais

`deliver_document` era atômica em volta de tudo. Quando o SMS estourou, o
`rollback` levou junto a linha do e-mail **já aceito**: o paciente não
recebia nada, e a lista de entregas não mostrava sequer a tentativa.

Agora a transação é **por entrega**. Um canal que falha aparece falhando,
sozinho.

### 2-D. O link que não valia

Este é o mais traiçoeiro, porque o e-mail chega — e a mensagem acusa o
paciente de ter um link velho.

A causa não estava no link: estava na **ordem**. O token era gravado
dentro de uma transação, e o e-mail enfileirado dentro da mesma transação,
com `.delay()`. A tarefa ia para a fila na hora, e o worker é mais rápido
que o resto da requisição. Dois desfechos, os dois ruins:

- o worker manda o e-mail **antes** de o token estar visível para outra
  conexão; ou
- a transação falha depois do envio e o token **nunca chega a existir** —
  foi o que aconteceu aqui.

Duas correções, porque são dois caminhos:

| Correção | Cobre |
| --- | --- |
| `on_commit` no backend de e-mail | **todo** e-mail do produto: verificação de endereço, convite, recuperação de senha, descadastro |
| Token gravado em transação curta, mensagem enviada depois dela | o SMS, que não passa por backend nenhum |

A primeira mora no backend e não em cada chamador justamente porque cada
chamador teria de lembrar sozinho.

## 3. O envio é automático — e já era

**O primeiro envio não passa pelo botão.** Assinar grava um `OutboxEvent`
no tópico `documents.document_issued`; `communications/apps.py` registra o
consumidor, e `events.tasks.dispatch_outbox` o executa **no worker**.

O que o médico viu como "não enviou" foi o evento ficando em `failed` pela
cadeia acima. Com ela corrigida, o automático volta a funcionar — e o
botão da tela é o que sempre foi: **reenvio**.

| Canal | Quando sai |
| --- | --- |
| **E-mail** | sempre, em todos os planos |
| **SMS** | só nos planos que o incluem (Básico para cima) |

O corte de SMS por plano já existia, em `smsdev.resolve_api_key`, e vira
`SmsChannelDisabled` — que `_send` trata sem derrubar o e-mail.

**Documento emitido em papel não é entregue automaticamente.** O PDF do
sistema, nesse caminho, não tem assinatura nenhuma: nem digital, nem a da
caneta, que só existe no papel impresso. Enviá-lo ao paciente entregaria
um arquivo que ele poderia apresentar no lugar do documento válido. O
envio manual continua disponível para ele, por decisão de quem assina.

## 4. A entrega sai pelo worker

`app` não tem saída para a internet — quem a tem é o `celery_worker`
(`docker-stack.yml`, e o comentário de `EMAIL_BACKEND` em
`core/settings.py`).

O envio automático já nascia no lugar certo. O **reenvio pela tela** não:
chamava `deliver_document` dentro da requisição. O e-mail escapava porque
o backend dele enfileira sozinho; o SMS fazia a requisição na hora, e na
rede do `app` ela só pode terminar em timeout. Em desenvolvimento
funcionava — ali tudo alcança tudo, que é o formato clássico do defeito
que só aparece em produção.

Agora a view enfileira `communications.tasks.deliver_document_task`. A
consequência para a tela é que o resultado não existe no instante da
resposta; em troca, a tela deixa de poder quebrar por causa de uma
entrega.

A falta de contato continua conferida **na view**: é o único desfecho que
a pessoa ali pode resolver agora, e descobri-lo numa lista de entregas
minutos depois é descobrir tarde.

## 5. O que os roteiros cobram

`rodar_roteiros entrega_documento links_de_mensagem`

| Seção | Asserções |
| --- | --- |
| entrega 1–3 | a mensagem de SMS cabe num segmento com o link real, sem acento; a de e-mail continua completa; e o texto antigo de 221 caracteres é nomeado como o que não cabia |
| entrega 4 | **o e-mail sai mesmo com o SMS quebrado** — a asserção que teria evitado o estrago |
| entrega 5–6 | falha inesperada vira entrega marcada, não exceção; `send_sms` não levanta mais erro cru |
| entrega 7–9 | a entrega sai pelo worker; o envio automático está ligado ao evento; o SMS segue o plano |
| links 1 | **nenhum e-mail é enfileirado antes do commit**, e transação desfeita não manda nada |
| links 2–4 | o link é extraído **do texto que sairia** e aberto de verdade; o reenvio troca o link e revoga o anterior |
| links 5–7 | verificação de e-mail, convite e descadastro respondem — e o descadastro preserva a prova do consentimento |
| links 8 | token forjado nunca abre |
