# Comunicado às clínicas — OpenRouter como provedor de IA reserva

**Decidido pelo controlador em 2026-10-22.** Comunica a inclusão de um
suboperador, como manda a cláusula 8.4 do contrato de adesão, **antes** de
a reserva ser ligada. A relação atualizada está em
[`suboperadores.md`](suboperadores.md).

**Envio:** de `contato@neurodoc.app.br`, pelo SMTP da instalação (no
worker), um e-mail por clínica de terceiros, ao responsável (papel
*owner*), com cópia oculta para `contato@neurodoc.app.br`, que guarda o
registro. O parágrafo "Na sua clínica" muda conforme a clínica seja ou não
atendida pela IA da instalação. O registro do envio fica no fim.

---

**Assunto:** NeuroDoc — inclusão da OpenRouter como provedor de IA reserva

Prezado(a) responsável pela {clínica},

Comunicamos, nos termos da cláusula 8 do Contrato de Adesão ao NeuroDoc, a
inclusão de um novo suboperador: a **OpenRouter, Inc.** (EUA), como
provedor **reserva** do apoio clínico por inteligência artificial.

**O que muda.** O apoio por IA da instalação continua sendo feito pela
NVIDIA. A partir de agora, se a chamada à NVIDIA **falhar** — serviço fora
do ar, tempo esgotado ou modelo descontinuado —, o pedido passa a ser
atendido pela OpenRouter, em vez de o médico receber um erro. Em outubro, o
modelo da NVIDIA deixou de responder sem aviso; a reserva existe para que
isso não interrompa o atendimento.

**O que ela recebe.** Exatamente o que iria à NVIDIA: o texto clínico
**desidentificado** no próprio servidor do NeuroDoc antes de sair (nome,
CPF, telefone e e-mail retirados). A resposta volta como rascunho, que o
médico revisa antes de qualquer uso. Cada vez que a reserva atende, isso
fica registrado na trilha de auditoria.

**Onde.** A OpenRouter fica nos Estados Unidos e repassa o pedido a um
provedor de infraestrutura que executa o modelo. O NeuroDoc **exige**, em
todo pedido, que esse provedor **não retenha os dados**, **não os use para
treinamento** e **não seja sediado na China**. A transferência
internacional já existia com a NVIDIA e com o servidor, também nos EUA.

**Na sua clínica.** {aplicacao}

A relação completa e atualizada dos suboperadores está em:
https://github.com/ffreua/neurodoc/blob/main/docs/governance/suboperadores.md

**Seus direitos.** Se a clínica tiver oposição fundamentada a este
suboperador, responda a este e-mail. Buscaremos uma alternativa — inclusive
manter a reserva desligada para a sua clínica — e, não havendo alternativa
razoável, a clínica pode rescindir o contrato sem multa, com restituição
proporcional do período pago e não utilizado, conforme as cláusulas 8.5 e
8.6.

Nenhuma ação é necessária da sua parte.

Atenciosamente,

Dr. Fernando Freua
NeuroDoc — contato@neurodoc.app.br

---

**Texto de `{aplicacao}`:**

- *Clínica no plano com IA, usando o padrão da instalação:* "Sua clínica
  usa o apoio por IA da instalação, e por isso poderá ser atendida pela
  reserva quando a NVIDIA falhar."
- *Clínica em plano sem IA:* "O plano atual da sua clínica não inclui o
  apoio clínico por IA, e por isso nenhum dado dela é enviado à NVIDIA nem
  à OpenRouter. Este aviso vale para o caso de a clínica passar a um plano
  com IA."

---

## Registro do envio

*Preenchido depois do envio.*
