# WhatsApp pela Twilio da própria clínica (BYO)

Registro das decisões do canal de WhatsApp automático (2026-11-25), para
quando alguém (ou algo) chegar depois e precisar saber **por quê** está assim.
O tutorial para as clínicas está no manual (`/ajuda/whatsapp-twilio/`, fonte
em `base/ajuda_whatsapp.py`); este arquivo é o lado de dentro.

## A decisão de 2026-11-08, revista

`docs/homologation/whatsapp-da-recepcao.md` recusou a API oficial porque ela
**exigia o NeuroDoc credenciado como provedor (Tech Provider) na Meta**, com o
cartão de cada clínica na conta dela. O modelo **BYO Twilio** muda a premissa:

- a **clínica** abre a própria conta na Twilio, cadastra o próprio número pelo
  *Self Sign-up* (cliente direto) e paga a Twilio e a Meta;
- o NeuroDoc só guarda as credenciais **da clínica**, cifradas, e chama a API
  em nome dela.

A Twilio documenta que "direct customers can register a WhatsApp sender using
Self Sign-up", e que o programa de Tech Provider é para o ISV que registra o
número com as credenciais **da subconta que ele mesmo atribui ao cliente**
(<https://www.twilio.com/docs/whatsapp/self-sign-up>,
<https://www.twilio.com/docs/whatsapp/isv/tech-provider-program>). **Nenhuma
página trata expressamente** do caso do SaaS que guarda credenciais de contas
de clientes diretos; a leitura acima é inferência da documentação, e o risco
está registrado em "Pendências".

O botão do WhatsApp da recepção (`wa.me`, 1.39) **continua igual e em todos os
planos**: é outra coisa (uma pessoa enviando pelo WhatsApp da clínica).

## O que o canal faz, e o que não faz

**Faz:** envia, pelo número da clínica, **modelos aprovados pela Meta** em
cinco ocasiões, cada uma ligável à parte:

| Ocasião (`evento`) | Variáveis do modelo, nesta ordem |
| --- | --- |
| `lembrete` — lembrete de consulta (24 h e 2 h antes) | `{{1}}` clínica, `{{2}}` data, `{{3}}` hora |
| `marcado` — horário marcado | idem |
| `remarcado` — horário remarcado | idem |
| `cancelado` — horário cancelado | idem |
| `documento` — documento disponível | `{{1}}` clínica, `{{2}}` link seguro |

O lembrete de exame da agenda de recursos usa o modelo do `lembrete`.

**Não faz, de propósito:**

- **Nada clínico na mensagem.** Nem nome do médico, nem especialidade, nem tipo
  de consulta, nem nome do exame, nem o nome do paciente (quem recebe pode ser
  um parente). A política do WhatsApp proíbe "enviar ou solicitar informações
  relacionadas à saúde" quando a lei aplicável proíbe distribuí-las a sistemas
  sem os requisitos necessários (<https://whatsappbusiness.com/pt-br/policy/>),
  e de uma clínica de neurologia a simples consulta já é dado de saúde. O
  documento **nunca** vai anexado: vai o link opaco de sempre (`/d/<token>/`),
  que pede os 4 últimos dígitos do CPF.
- **O nome da clínica vai na mensagem** e pode dizer a especialidade
  ("… Neurologia Ltda"). Usa-se o **nome fantasia** quando há
  (`Tenant.trade_name`), que a clínica escolhe. O titular considerou aceitável
  (2026-11-25): é a identidade da própria clínica, que o paciente conhece.
- **Não lê respostas.** O sistema não recebe mensagem do paciente (não há
  webhook de entrada): um canal que recebe texto livre vira prontuário paralelo
  sem dono, e o paciente acharia que alguém leu. O modelo diz que a mensagem é
  automática e manda falar com a clínica pelos canais habituais.
- **Não confirma consulta por botão.** Exigiria ler a resposta e mexer na
  agenda a partir dela — fora deste escopo pelos dois motivos acima.
- **Não manda o link do teleatendimento.** O link da sala pode carregar
  credencial de acesso; segue só por e-mail.
- **Não substitui o e-mail.** Onde o contato aceita WhatsApp, o WhatsApp
  **substitui o SMS** daquela ocasião (não os dois, que seria a mesma pessoa
  avisada duas vezes pelo celular); o e-mail continua. **Se o WhatsApp não sai
  na hora** (recusa da Twilio, número inválido, credencial trocada, canal
  suspenso no meio), o contato com SMS habilitado recebe o **SMS de reserva**
  na mesma rodada (`services._reserva_sms`). A falha que chega depois, pelo
  aviso de status, não tem reserva: a mensagem saiu, e reenviar por outro
  canal mandaria o mesmo aviso duas vezes.

## Consentimento

O WhatsApp exige *opt-in* próprio: só se fala com quem deu o número **e**
autorizou receber mensagens (<https://whatsappbusiness.com/pt-br/policy/>).
Por isso o contato do paciente ganhou um consentimento **à parte**
(`PatientContact.whatsapp_opt_in_at`, `whatsapp_opt_in_evidence`,
`whatsapp_opt_out_at`), no molde do consentimento de divulgação: data, como
foi obtido (obrigatório) e revogação. "Aceita SMS" **não** vale como aceite de
WhatsApp. O contato encerrado tem o aceite revogado junto.

## Arquitetura

Nada de infraestrutura nova: o canal é um valor a mais de `DeliveryChannel`
(`whatsapp`) e passa pelo mesmo `Delivery`/`DeliveryAttempt`, pela mesma posse
`PENDING→SENDING`, pelas mesmas chaves de idempotência e pela mesma fila do
worker que o SMS e o e-mail.

- `communications/whatsapp_twilio.py` — o cliente da API (HTTP com `httpx`, que
  já é dependência; o SDK da Twilio não entrou), a validação da assinatura, os
  eventos e as variáveis, e a tradução de erros.
- `WhatsAppTwilio` (uma linha por clínica) — Account SID, **Auth Token
  cifrado** (`base.crypto`, envelope), número, Messaging Service opcional, o
  interruptor da clínica, o resultado da última verificação e o token aleatório
  da URL de status. `WhatsAppModelo` — um modelo (ContentSid) por ocasião, com
  o estado da aprovação conferido na Twilio.
- `InstallationSettings.whatsapp_twilio_liberado` — a chave da **instalação**,
  no console. Nasce desligada: o canal só envia a paciente com ela ligada
  (ver "Pendências"). Desligar é um clique e para todo envio na hora.

### Estados mostrados à clínica

| Estado | Quando |
| --- | --- |
| Não configurado | sem credenciais |
| Pendente | credenciais salvas e ainda não verificadas (ou trocadas depois da última verificação) |
| Inválido | a última verificação falhou (credencial recusada, conta suspensa, número fora do ar) |
| Validado | conta ativa e número `ONLINE` na Twilio, mas nada ligado para enviar |
| Operacional | validado, ativado pela clínica, liberado pela instalação e com ao menos uma ocasião ligada com modelo aprovado |
| Desativado | a clínica suspendeu o envio (as credenciais ficam) |

Preencher os campos **nunca** mostra "Operacional": só a verificação na
Twilio, feita pelo worker, leva adiante.

### Envio

`POST /2010-04-01/Accounts/{AccountSid}/Messages.json` com `To`/`From`
`whatsapp:+E164` (ou `MessagingServiceSid`), `ContentSid`, `ContentVariables`
(JSON) e `StatusCallback`
(<https://www.twilio.com/docs/content/send-templates-created-with-the-content-template-builder>).
Fora da janela de 24 h só modelo aprovado sai (erro 63016,
<https://www.twilio.com/docs/api/errors/63016>), e por isso **o canal nunca
manda texto livre**.

Recusa da Twilio (4xx) vira entrega **Falhou** com o código, sem nova
tentativa (repetir não conserta número inválido nem modelo recusado). 401 marca
a configuração como inválida. Erro de rede e 5xx devolvem a entrega à fila,
como no SMS (`tentar_de_novo_se_o_transporte_falhar`).

### Situação da entrega

Duas fontes, porque a Twilio não garante a ordem nem a chegada do aviso:

1. **Aviso de status** (`/whatsapp/status/<token>/`, público, `csrf_exempt`).
   A URL vai em cada mensagem, então a clínica não configura nada. O token
   aleatório só **acha** a clínica; quem autentica é a assinatura
   `X-Twilio-Signature` (HMAC-SHA1 da URL + parâmetros, com o Auth Token
   principal, <https://www.twilio.com/docs/usage/security>), conferida contra
   a URL montada de `PUBLIC_BASE_URL` — nunca do `Host:`. Depois, o
   `AccountSid` do aviso tem de ser o da clínica, e o `MessageSid` tem de ser
   de uma entrega **dela**. A atualização é um `UPDATE` condicional que só
   avança (aceita → entregue/falhou): aviso repetido ou fora de ordem não
   regride nada.
2. **Consulta periódica** (`reconcile_pending_whatsapp`): a entrega aceita sem
   aviso é consultada (`GET .../Messages/{Sid}.json`) depois de 15 min e 1 h;
   sem resposta final, fica "Sem confirmação". Cobre o aviso perdido e a
   janela em que a clínica trocou o Auth Token na Twilio e ainda não aqui.

### Verificação ("Verificar agora")

No worker (o `app` não fala com provedor, CLAUDE.md §2):
`GET /2010-04-01/Accounts/{Sid}.json` (conta ativa? `Trial` ou `Full`?),
`GET https://messaging.twilio.com/v2/Channels/Senders?Channel=whatsapp` (o
número está lá e `ONLINE`?) e, para cada ocasião,
`GET https://content.twilio.com/v1/Content/{Sid}` e
`.../ApprovalRequests` (aprovado pelo WhatsApp? o número de variáveis bate?)
(<https://www.twilio.com/docs/iam/api/account>,
<https://www.twilio.com/docs/whatsapp/api/senders>,
<https://www.twilio.com/docs/content/content-api-resources>). A tela recarrega
sozinha enquanto a verificação corre.

### Segurança

- Auth Token cifrado em repouso, mostrado só mascarado, nunca na trilha, no log
  ou na resposta; entra na rotação da chave-mestra
  (`rotate_secrets_master_key`). Campo em branco ao salvar mantém o atual.
- Trocar credencial ou número volta o estado a **Pendente**: o envio para até
  uma verificação nova.
- A trilha registra quem configurou, verificou, ativou, suspendeu, testou e
  removeu — sem token, sem telefone, sem texto.
- O canal entra na varredura que proíbe envio de dentro de view
  (`check_provedor_e_sms`).

## Por que o Auth Token, e não uma API Key

A Twilio autentica a assinatura dos avisos com o **Auth Token principal**
("make sure you are using your primary AuthToken",
<https://www.twilio.com/docs/usage/security>); nenhuma página confirma que uma
API Key sirva para isso, e sem validar a assinatura o aviso de status não pode
ser aceito. Pedir API Key **e** Auth Token dobraria o que a clínica precisa
copiar sem reduzir o que fica guardado. A troca do token é a rotação da própria
Twilio (token secundário, depois "promover"); a tela diz isso.

**Alternativa registrada:** a assinatura por chave compartilhada que a Twilio
passou a oferecer e chama de preferida em produção
(<https://www.twilio.com/docs/usage/webhooks/webhooks-security>). Ficou para
depois: exige configurar a chave no Console por conta, e o caminho padrão é o
que a clínica consegue seguir sozinha.

## Custos e plano

Em **todos os planos**: quem paga é a conta Twilio da clínica (a taxa da Twilio
mais a da Meta, repassada). A Meta cobra por mensagem entregue, e o modelo de
utilidade dentro da janela deixou de ser grátis em 2026-10-01
(<https://developers.facebook.com/docs/whatsapp/pricing>,
<https://www.twilio.com/en-us/whatsapp/pricing>). O sistema não mostra preço:
ele muda, e o vigente é o das páginas oficiais, que o tutorial aponta.

## Jurídico

**Parecer da Dra. Karina (2026-11-25): nada a mudar** — nem o contrato, nem o
Anexo II, nem o Aviso de Privacidade. A Twilio e a Meta entram como
operadoras **da clínica**, que as contrata (DPA, item 7.2), como já acontece
com a chave própria de SMS e o servidor de e-mail da clínica.

## Pendências (antes de liberar no console)

1. **Homologação com uma conta real.** O Sandbox da Twilio não aceita modelos
   próprios (<https://www.twilio.com/docs/whatsapp/sandbox>), então o envio de
   modelo só se prova com um número de verdade: a conta da clínica do titular,
   com o canal liberado no console só durante o teste. Pontos a confirmar: se
   o envio direto pelo `From` dispensa Messaging Service (a página é ambígua —
   por isso o campo opcional existe) e o código de idioma do modelo (`pt_BR`).
2. **Leitura de quem guarda credencial de cliente direto** no programa da Meta
   (ver o início). Se a Meta ou a Twilio entenderem que o SaaS precisa ser Tech
   Provider, o canal fica recolhido na instalação até isso se resolver; nada
   além disso depende da resposta.
