# Comunicado às clínicas — Receita controlada com a numeração da Anvisa no ar

**Pedido pelo proprietário em 2026-10-29**, depois do primeiro bloco real do
SNCR pedido em produção e da primeira Receita de Controle Especial eletrônica
numerada, assinada e conferida no portal da Anvisa
([`docs/sncr/ESTADO_EXECUCAO.md`](../sncr/ESTADO_EXECUCAO.md)). Encerra o
que o [comunicado de 2026-10-21](comunicado-2026-10-sncr.md) prometia
("quando a integração estiver concluída, avisaremos").

**Envio:** de `contato@neurodoc.app.br`, pelo SMTP da instalação (no worker),
um e-mail por clínica, ao responsável (papel *owner*) das clínicas de
terceiros, com cópia oculta para `contato@neurodoc.app.br`. O registro do
envio fica no fim deste arquivo.

---

**Assunto:** NeuroDoc — Receita controlada eletrônica com a numeração da Anvisa já disponível

Prezado(a) responsável pela {clínica},

Como prometemos no comunicado de 21/10, a integração do NeuroDoc com o
Sistema Nacional de Controle de Receituários (SNCR) da Anvisa está
concluída e em funcionamento. O NeuroDoc segue as novas regras da RDC
nº 1.000/2025 para as receitas controladas eletrônicas.

**O que muda para os médicos da sua clínica:**

- **Cada médico pede o próprio bloco de números**, uma vez: no menu,
  **Numeração SNCR** → **Pedir bloco com o Gov.br**. Ele entra com a conta
  Gov.br dele e a Anvisa entrega 1.000 números, que são do médico e valem
  em todas as clínicas em que ele atende.
- **No atendimento**, em **Conduta**, o botão **Receita controlada (SNCR)**
  abre a receita eletrônica: Receita de Controle Especial (listas C1 e C5)
  ou Receita Sujeita à Retenção (antimicrobianos, agonistas de GLP-1). O
  nome do medicamento é buscado na lista da Anvisa, e o NeuroDoc confere a
  classificação pela Portaria 344.
- **Cada medicamento sai na sua folha, com o seu número SNCR**, no modelo
  oficial da Anvisa, assinado digitalmente com o certificado ICP-Brasil do
  médico. A farmácia confere o número em sncr.anvisa.gov.br.
- **A receita impressa continua** existindo, para assinar e carimbar, para
  quem preferir ou estiver sem certificado.

O passo a passo está no manual: https://neurodoc.app.br/ajuda/receita-sncr/

Nenhuma ação é necessária da sua parte além de avisar os médicos da equipe.
Em caso de dúvida, basta responder a este e-mail.

Atenciosamente,

Dr. Fernando Freua
NeuroDoc — contato@neurodoc.app.br

---

## Registro do envio

*(preenchido depois do envio)*
