# Vigência por período e renovação pelo sistema (1.47)

Pedido do Dr. Fernando em 2026-11-13: o trimestral e o semestral deixam de
ser parcelas de um contrato de 12 meses. **Cada forma de pagamento é um
período** — 3, 6 ou 12 meses —, pago de uma vez com o desconto dele, e
**nada renova sozinho**. Quinze dias antes do fim, o responsável é avisado e
renova pelo próprio sistema.

Exige o **contrato 2.2** (minuta em `docs/governance/contrato-2.2-minuta.md`):
a 2.1 diz que todo plano pago tem vigência de 12 meses.

## Como funciona

| Etapa | Onde | O que acontece |
| --- | --- | --- |
| Contratar | página de vendas ou convite | o aceite vence ao fim do período (`ContractAcceptance.expires_at`: +3, +6 ou +12 meses) e abre a primeira `contratacao.Vigencia` |
| 15 dias antes | toda tela de `/app/`, só para o responsável | faixa amarela "O plano da clínica vence em…", com **Renovar** |
| 15 dias antes | e-mail ao responsável, 08h15 | uma vez por período (`aviso_antes_em`) |
| Renovar | Organização → **Plano e renovação** (`/app/org/plano/`) | escolhe 12, 6 ou 3 meses; o pedido nasce com a clínica; o worker abre um checkout da Asaas; a página espera e leva à Asaas |
| Pago | aviso `CHECKOUT_PAID` | o período seguinte começa no **fim do atual** (pagar antes não encurta nada), ou agora, se já venceu; e-mail a quem pagou e ao console |
| Venceu sem renovar | faixa vermelha; e-mail ao responsável e aos superadministradores | **nada é bloqueado nem rebaixado** — a cláusula 5 pede aviso antes de restringir; o console decide |

## Por que um checkout gerado no clique

Três caminhos da API da Asaas foram estudados (documentação de 2026-11-13):

- **Link de pagamentos** (`/v3/paymentLinks`): anônimo e reutilizável, feito
  para muitos pagadores; não diz de que clínica veio o dinheiro. Recusado.
- **Cobrança** (`/v3/payments`, a "fatura" com `invoiceUrl`): exige criar o
  cliente na Asaas com CPF/CNPJ mandados daqui — o Anexo II do contrato diz
  que a Asaas recebe os dados na página dela —, e nunca foi testada contra a
  conta real. Vantagem: o link vale até o vencimento e pode ir por e-mail.
  Fica como alternativa se um dia o link no e-mail for indispensável.
- **Checkout** (`/v3/checkouts`, o da 1.46): já provado em produção, casado
  pelo `checkout.id` gravado no pedido. Vence em uma hora — por isso é
  gerado no clique, e o e-mail leva à tela de renovar (logado como
  responsável: quem paga é quem pode).

## Decisões

- **A vigência não liga nem desliga nada.** `Tenant.plan` continua
  decidindo o que a clínica pode; a vigência é o registro do que foi pago e
  a base do aviso.
- **Sem período por migração.** Entre as clínicas anteriores à 1.47 há
  cortesia e condição combinada; um "renove" na tela de quem não paga seria
  pior que nenhum. O console registra o período de cada pagante à mão.
- **Renovar mantém o plano**, pelo preço de tabela do dia. Mudar de plano e
  condição combinada (residência, Personalizado) continuam sendo conversa.
- **Dois pagamentos são dois períodos**, emendados um no outro (pago é pago),
  com aviso ao console. O segundo clique em Renovar dentro de 90 minutos
  reaproveita o pedido aberto, para isso não acontecer por engano.
- **Plano trocado no console cala o aviso**: o período pago deixou de
  descrever o que a clínica tem.
- **Clínica suspensa** não consegue renovar pela tela (o `TenantMiddleware`
  bloqueia escrita); a renovação dela é pelo console.

## Verificação

`check_renovacao` (novo), `check_contratacao` e `check_periodicidade`
(atualizados para o pagamento único e o vencimento por período).
