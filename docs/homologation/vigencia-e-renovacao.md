# Vigência por período e renovação pelo sistema (1.47)

Pedido do Dr. Fernando em 2026-11-13: o trimestral e o semestral deixam de
ser parcelas de um contrato de 12 meses. **Cada forma de pagamento é um
período** — 3, 6 ou 12 meses —, pago de uma vez com o desconto dele, e
**nada renova sozinho**. O responsável é avisado com 30 e com 15 dias e
renova pelo próprio sistema, com novo aceite.

Exige o **contrato 2.2** (`tenancy/contrato/contrato-2.2.md`), escrito sobre a
2.1 com as decisões da Dra. Karina sobre a minuta
(`docs/governance/contrato-2.2-minuta.md`, 2026-11-14).

## Como funciona

| Etapa | Onde | O que acontece |
| --- | --- | --- |
| Contratar | página de vendas ou convite | o aceite vence ao fim do período (`ContractAcceptance.expires_at`: +3, +6 ou +12 meses), com os 7 dias de arrependimento, e abre a primeira `contratacao.Vigencia` |
| 30 dias antes | toda tela de `/app/`, só para o responsável | faixa amarela "O plano da clínica vence em…", com **Renovar**; o botão abre |
| 30 dias antes | e-mail ao responsável, 08h15 | uma vez por período (`aviso_30_em`) |
| 15 dias antes | e-mail ao responsável, 08h15 | uma vez por período (`aviso_15_em`); o período registrado já dentro dos 15 dias ganha só este |
| Renovar | Organização → **Plano e renovação** (`/app/org/plano/`) | escolhe 12, 6 ou 3 meses, marca **"li e aceito"** (versão do contrato, sem arrependimento) e **"tenho poderes"**; o pedido grava o aceite; o worker abre um checkout da Asaas |
| Pago | aviso `CHECKOUT_PAID` | o período seguinte começa no **fim do atual** (pagar antes não encurta nada), ou agora, se já venceu; e-mail a quem pagou (com a versão aceita) e ao console |
| Venceu sem renovar | faixa vermelha; e-mail ao responsável (com a data do Gratuito) e aos superadministradores | o plano continua por **15 dias** — é o aviso prévio da cláusula 5.2 |
| 15 dias depois do fim | tarefa das 08h15 (`vigencias.rebaixar`) | a clínica **passa ao Gratuito**: nada é apagado, o que excede o limite só impede novos cadastros, e os médicos além do limite perdem o papel (fica o mais antigo; quem não tinha outro papel é suspenso). E-mail ao responsável e ao console; a faixa fica 30 dias |
| Renovar depois | o mesmo botão, pelo plano de antes | o pagamento devolve o plano e os papéis médicos retirados, até o limite (`vigencias.restabelecer`) |

## O aceite da renovação

A Dra. Karina pediu novo "li e aceito" a cada renovação (cláusula 3.2 da
2.2). Ele fica **no pedido** (`Pedido.aceite_em`, `aceite_sha256`,
`aceite_texto`, `aceite_user_agent`, `poderes_declarados`, `contrato_versao`,
`origem_ip`), e não num segundo `ContractAcceptance`: aquele é único por
clínica e por versão, e a clínica que renova duas vezes na 2.2 aceitaria a
mesma versão duas vezes. O texto inteiro vai junto, como no cadastro
(cláusula 2.2). A caixa diz que **não há arrependimento na renovação**
(13.1), para a pessoa ler isso antes de pagar.

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
  responsável: quem paga e aceita é quem pode).

## Decisões

- **As clínicas que já existiam não mudam** (Dra. Karina e Dr. Fernando,
  2026-11-14). Nenhuma ganha período por migração; sem período, não há
  aviso nem passagem ao Gratuito, e quem aceitou a 2.1 ou antes continua
  nela. O console registra o período de uma clínica antiga só quando se
  decide que ela entra na regra.
- **O Gratuito sai da tarefa das 08h15**, e não à meia-noite: ninguém perde
  o plano enquanto dorme, e quem pagou de madrugada já está renovado. Como
  na degustação, os médicos além do limite perdem o papel — sem isso, não
  renovar seria a porta para vários médicos no Gratuito. A regra é a mesma
  função (`tenancy.degustacao.retirar_medicos_excedentes`).
- **Renovar mantém o plano** do último período, pelo preço de tabela do
  dia — que a PRONTDOC muda a seu critério, sem índice (cláusula 4.5).
  Mudar de plano e condição combinada (residência, Personalizado)
  continuam sendo conversa.
- **Dois pagamentos são dois períodos**, emendados um no outro (pago é pago),
  com aviso ao console. O segundo clique em Renovar dentro de 90 minutos
  reaproveita o pedido aberto, para isso não acontecer por engano.
- **Plano trocado no console cala o aviso** e a passagem ao Gratuito: o
  período pago deixou de descrever o que a clínica tem.
- **Registrar período no console para a clínica que passou ao Gratuito**
  devolve o plano e os médicos (pagamento por Pix fora do site). Clínica no
  Gratuito que não venceu é recusada: troque o plano antes.
- **Clínica suspensa** não consegue renovar pela tela (o `TenantMiddleware`
  bloqueia escrita); a renovação dela é pelo console. Clínica encerrada não
  é rebaixada.

## Verificação

`check_renovacao` (o aceite, os avisos de 30 e 15, o Gratuito e a volta),
`check_contratacao`, `check_periodicidade`, `check_contrato` (as cláusulas
da 2.2) e `check_degustacao` (a regra dos médicos, agora compartilhada).
