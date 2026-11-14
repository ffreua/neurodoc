# Checkout da Asaas — operação

O módulo é `contratacao/`. Fluxo e decisões em
`docs/releases/1.46-checkout-asaas.md`; aqui está o que se faz no servidor e
no painel da Asaas.

## Segredos

| Segredo | Quem recebe | O que é |
| --- | --- | --- |
| `NEURODOC_ASAAS_API_KEY` | só o worker | a chave da API (`$aact_prod_…`), criada em **Integrações > Chaves de API** |
| `NEURODOC_ASAAS_WEBHOOK_TOKEN` | app e worker | o token que a Asaas devolve em `asaas-access-token`; 32 a 255 caracteres, sem espaço |

Os dois são `external` no `docker-stack.yml`: precisam existir **antes** do
deploy. Numa instalação que não usa o checkout, a chave fica `DISABLED`.

```bash
# token do webhook (uma vez)
openssl rand -hex 32 | tr -d '\r\n' | docker secret create NEURODOC_ASAAS_WEBHOOK_TOKEN -
# chave da API (cole sem quebra de linha)
printf '%s' '$aact_prod_...' | docker secret create NEURODOC_ASAAS_API_KEY -
```

**Trocar a chave da API.** Segredo do Swarm não se edita: cria-se um com
outro nome e se aponta o serviço para ele, ou se remove o serviço do stack
antes de recriar o segredo. O caminho mais simples, numa janela calma:

```bash
docker service update --secret-rm NEURODOC_ASAAS_API_KEY neurodoc_v1_celery_worker
docker secret rm NEURODOC_ASAAS_API_KEY
printf '%s' '$aact_prod_NOVA' | docker secret create NEURODOC_ASAAS_API_KEY -
bash scripts/deploy.sh --skip-build
```

Depois de trocar, desative a chave antiga no painel da Asaas.

## Registrar o webhook

Depois do primeiro deploy com os segredos, **no worker**:

```bash
W=$(docker ps -q -f name=neurodoc_v1_celery_worker | head -1)
docker exec "$W" python manage.py asaas_webhook            # lista o que há
docker exec "$W" python manage.py asaas_webhook --gravar   # cria ou atualiza
```

Grava `https://<PUBLIC_BASE_URL>/asaas/webhook/`, envio **sequencial**, API
versão 3, o token do segredo e os eventos de `contratacao/asaas.py::EVENTOS_DO_WEBHOOK`.
Não digite o webhook no painel: o token copiado à mão é o que um dia não bate.

**Fila interrompida** (15 falhas seguidas): corrija a causa e rode
`--gravar` de novo — ele grava `interrupted: false`. Os avisos ficam guardados
na Asaas por 14 dias.

## Antes de ligar

1. **Chave Pix** cadastrada na conta Asaas. Sem ela, o checkout anual (Pix
   ou cartão) é recusado inteiro — testado em 2026-11-12.
2. **Contrato 2.1** publicado (`tenancy/contract.py::VERSAO`). O console
   recusa ligar com a 2.0.
3. Webhook registrado e um aviso de teste recebido (o console mostra os
   últimos avisos).
4. Ligar em `/instalacao/contratacao/`: código recente, `LIGAR` e o motivo.

## Segurança no painel da Asaas

- **Whitelist de IPs** (Integrações > Mecanismos de segurança): cadastre o IP
  da VPS. A chave só funciona de lá; vazada, não serve em outro lugar.
  Chamadas de outro IP recebem 403.
- **Evento crítico em requisições de saque**: deixe ligado. O NeuroDoc não
  faz saque nem transferência; com isso, nem a chave vazada move dinheiro
  sem aprovação manual.
- A chave **expira após 6 meses sem uso** (desativada aos 3). O checkout a
  usa a cada pedido; numa instalação parada, o webhook avisa
  (`ACCESS_TOKEN_EXPIRING_SOON`) por e-mail aos superadministradores.

## Quando algo dá errado

| Sintoma | Onde olhar |
| --- | --- |
| Pedido "Não abriu" | console, coluna de falha: a recusa da Asaas vem escrita (chave Pix, chave da API, conta) |
| Pago e sem convite | "Pagamento com valor diferente do pedido": conferir na Asaas; emitir o convite à mão no console de convites |
| Pago e o e-mail não saiu | console, "e-mail do link não saiu"; o botão continua na página do pedido para quem pagou |
| Avisos pendentes | console, "avisos com erro"; a varredura tenta de novo a cada 5 minutos |

## Desistência em 7 dias

A devolução é feita no painel da Asaas (cobrança > estornar). O aviso
`PAYMENT_REFUNDED` chega ao console; a clínica **não** é suspensa nem
rebaixada sozinha — isso é decisão no console de organizações.


## Renovação e vigências (1.47)

Desde a 1.47 cada período (12, 6 ou 3 meses) é pago de uma vez, e a clínica
renova em **Organização → Plano e renovação**, pelo mesmo checkout: o
pedido nasce com a clínica (`Pedido.tenant`) e o `CHECKOUT_PAID` abre o
período seguinte em vez de emitir convite. Nada muda no webhook nem nos
segredos.

- **Clínicas anteriores à 1.47** não têm período: registre o de cada
  pagante em `/instalacao/contratacao/` → Vigências (clínica, período,
  início, valor, de onde vem). Sem período registrado, a clínica não recebe
  aviso nem vê o botão Renovar.
- **Quem pagou por Pix ou transferência** fora do site: registre o período
  do mesmo jeito.
- **Vencida sem renovação**: chega e-mail "Vigência vencida sem renovação".
  Nada foi bloqueado; decida no console (trocar o plano, suspender ou
  esperar), com o aviso da cláusula 5.
- **Renovação paga com o plano trocado no meio**: o e-mail "Renovação paga"
  traz o aviso; o período foi aberto com o plano pago, e o plano da clínica
  não foi mexido.
