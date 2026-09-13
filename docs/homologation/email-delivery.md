# O e-mail sai pelo worker, e dá para testar sem mandar nada a ninguém

Evidências: `checks/check_email.py`, `manage.py testar_email`.

## O relato e o defeito real

O relato foi: criar uma clínica pelo convite funciona, mas o e-mail de
ativação não chega. A causa aparente era `EMAIL_ENABLED=False`, que troca
o backend por `locmem` — a mensagem é gerada e descartada na memória.

A causa real é outra, e mais séria: **o e-mail de conta não funcionaria em
produção nem com o SMTP ligado.**

`send_email_verification` chamava `send_mail` dentro da requisição, no
processo `app`. No Swarm o `app` está em `traefik_public` +
`neurodoc_v1_internal`; quem alcança a internet é o `celery_worker`, em
`neurodoc_v1_egress` (`docker-stack.yml`). Cada cadastro e cada "esqueci
minha senha" travaria dez segundos no `EMAIL_TIMEOUT` e falharia — no
primeiro dia, para todo mundo.

O desenho já sabia disso. `NEURODOC_SMTP_PASSWORD` só é entregue ao
worker, e `core/settings.py` só a exige quando `SERVICE_ROLE == 'worker'`.
O caminho de envio é que nunca foi construído.

## Um backend, e não uma tarefa em cada ponto

`communications/mail_backend.py::WorkerEmailBackend` enfileira; a entrega
acontece em `communications.tasks.deliver_installation_email`, no worker.

A alternativa seria uma tarefa em cada lugar que envia. Um backend resolve
também os lugares que não são nossos: o `PasswordResetForm` do próprio
Django, o e-mail de erro para `ADMINS`, e a próxima tela que alguém
escrever chamando `send_mail` sem saber de nada disto. A seção 4 do
roteiro verifica exatamente esse caso — recuperação de senha não passa por
código nosso e mesmo assim atravessa a fila.

Dois detalhes que não são acessórios:

**A tarefa pede o backend SMTP explicitamente.** Se lesse `EMAIL_BACKEND`,
encontraria o backend que enfileira e a mensagem daria voltas na fila para
sempre. A seção 5 lê o código-fonte da tarefa e falha se a linha sair — o
sintoma dessa regressão (fila crescendo) só apareceria em produção.

**Anexo é recusado, não descartado.** Nada anexa hoje: a entrega de
documento manda um link com token, não o PDF. Manter assim tem duas
razões — um PDF de prontuário no corpo de uma mensagem do broker é dado de
paciente atravessando mais um salto, e mensagem grande é a forma clássica
de entupir a fila. Falhar com uma explicação é melhor do que entregar um
e-mail sem o anexo que alguém achou que estava lá.

## Testar sem mandar e-mail para ninguém

`ops/local_compose.py` passou a subir um **Mailpit** no ambiente local:
SMTP na 1025, caixa de entrada em <http://127.0.0.1:8025>. Ele aceita
qualquer coisa e não entrega a ninguém.

Isso importa mais do que parece. O banco de demonstração tem contatos com
endereços de e-mail, e exercitar "reenviar documento ao paciente" contra
um SMTP de verdade manda e-mail de verdade. O capturador é a diferença
entre testar o fluxo e descobrir que testou.

Para ligar:

```
# .env
EMAIL_ENABLED=True
```

```
python -m ops.local_compose
docker compose up -d
```

O gerador grava um marcador em `.secrets/NEURODOC_SMTP_PASSWORD` se ele
estiver `DISABLED` — o worker exige a senha quando o envio está ligado, e o
Mailpit não pede nenhuma; sem isso o worker nem sobe, que é uma falha de
configuração disfarçada de falha de código.

`EMAIL_ENABLED` deixou de ser fixado pelo gerador e passou a vir do `.env`.
O padrão do `.env.example` continua `False`.

## O comando de diagnóstico

`manage.py testar_email <endereço>` existe porque "não estamos enviando
e-mails" tem cinco causas possíveis e a mensagem de erro do Django não
distingue nenhuma: envio desligado, processo sem egresso, senha que não
chegou ao worker, servidor recusando, ou mensagem parada numa fila sem
worker de pé.

O comando imprime a configuração antes de tentar (nunca a senha, só se ela
existe) e diz por onde a mensagem saiu. `--direto` ignora a fila e fala com
o SMTP do processo atual — é o que separa "o SMTP está errado" de "o worker
não está de pé".

## A suíte não depende do modo

Quatro roteiros afirmam sobre `mail.outbox`, que só existe no backend
`locmem`. Com o envio ligado, a caixa fica vazia e eles falhariam por
configuração do ambiente, não por regressão. Os quatro passaram a fixar o
próprio backend no topo — um roteiro deve controlar seu ambiente, não
herdá-lo. Os 36 roteiros passam com o envio ligado e com ele desligado.

`check_email` faz o contrário: precisa do envio ligado, e quando não está,
diz o que falta e sai sem falhar. Não há o que verificar quando o backend
é a caixa em memória.

## O que ainda sai do processo web

Honestidade sobre o alcance desta correção: ela cobre o **SMTP da
instalação**. O SMTP próprio de uma clínica ou de um médico
(`communications/email.py::resolve_sender`) monta uma conexão explícita, e
conexão explícita não passa por backend nenhum.

Na maior parte dos casos isso não importa, porque esses envios nascem de
eventos despachados por `events.tasks.dispatch_outbox`, que **já roda no
worker** — entrega de documento na emissão, lembrete de consulta, campanha
em lotes. O que sobra são três disparos feitos direto de uma view:

| Onde | O quê |
| --- | --- |
| `documents/views.py:326` | Reenviar documento ao paciente |
| `scheduling/views.py:705` | Confirmar consulta por e-mail |
| `communications/admin_views.py:342` | Botão "enviar e-mail de teste" |

Os três funcionam quando a clínica usa o SMTP da instalação (cai no
backend padrão, vai para a fila). Falham em produção apenas para a clínica
que configurou **servidor próprio**.

Não foram corrigidos aqui porque a correção muda semântica, não só
encanamento: as três esperam a falha de forma síncrona para marcar a
entrega como falhada e responder ao usuário na mesma tela. Passá-las para a
fila exige decidir o que a tela mostra enquanto não se sabe o resultado. É
uma decisão de produto, e fica registrada aqui para ser tomada, não
resolvida pela metade.

## O que foi verificado

`checks/check_email.py`, seis seções, todas verdes, de ponta a ponta
(RabbitMQ → worker → Mailpit):

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | O processo web enfileira em vez de falar com o SMTP? | Sim |
| 2 | A mensagem atravessa a fila e chega? | Chega |
| 3 | Verificação de conta usa o caminho? | Chega, com o assunto certo |
| 4 | Recuperação de senha usa o caminho? | Chega, com o link |
| 5 | A tarefa realimenta a fila? | Não — backend SMTP explícito |
| 6 | Anexo some em silêncio? | Recusado com explicação |
