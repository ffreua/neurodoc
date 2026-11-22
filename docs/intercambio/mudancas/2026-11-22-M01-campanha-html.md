# 2026-11-22 — Campanha em HTML com CSS, cliques e exclusão

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc 1.55, na mesma rodada que o ProntDoc |
| Tipo | mudança (funcionalidade, pedido do titular) |
| Publicado | não — aguarda outras mudanças pequenas antes do deploy |

A comunicação em massa passa a aceitar o corpo em HTML com CSS, ao lado do
texto simples. Feito igual nos dois lados (o código de `communications/`
era idêntico, fora o nome do produto):

- `communications/email_html.py`: limpeza por **lista de permissão** com o
  `nh3` (já instalado), o CSS limpo à parte (bloco `<style>` e `style=`), o
  rodapé de descadastro montado **depois** e fora do HTML de quem escreve,
  e a versão em texto gerada do HTML quando não há uma.
- `MarketingCampaign.body_html` (migração `0012`), `body_text` opcional
  quando há HTML; o formulário grava o HTML já limpo e recusa o que passa
  de 90 mil caracteres (o Gmail corta acima de ~102 KB, e o rodapé fica no
  fim).
- O envio manda as duas partes, limpando de novo o que está no banco. O
  teste manda o HTML com um link de descadastro de exemplo.
- Prévia (`campanhas/<id>/previa/`) num quadro `sandbox`, com política
  própria (sem script, imagem `https:`, só o próprio site emoldura), e a
  **alteração do rascunho** (`campanhas/<id>/editar/`), com trilha sem
  conteúdo.

Decisão registrada: imagem remota permitida. O HTML é o mesmo para todos
(não há campo de mesclagem), então uma imagem não identifica quem abriu —
a regra de não medir abertura por paciente continua de pé.

Na mesma rodada, também pedidos pelo titular (com autorização da Dra.
Karina, sem mudança no contrato):

- **Cliques por link** (`CampaignLink`, migração `0013`; no ProntDoc a
  dependência do `tenancy` é a `0025`): no envio, os links do HTML e do
  texto viram `/c/<token>/`, **o mesmo para todos os destinatários** — a
  contagem é do link, nunca da pessoa, e nem IP nem navegador são
  guardados (o IP entra só no cache, embaralhado, por 30 min, para o mesmo
  visitante contar uma vez). Robô, antivírus, mensageiro e `HEAD` não
  contam. O destino é o gravado no envio, nunca parâmetro da requisição.
  Prévia e teste não passam pela contagem.
- **Excluir a campanha** de verdade, com a lista e os links; recusado
  enquanto envia (pausar antes). A trilha guarda os números, não o
  conteúdo; os links já entregues passam a responder "não está mais
  disponível".

Roteiro: `check_campanha_html`, passando nos dois.
