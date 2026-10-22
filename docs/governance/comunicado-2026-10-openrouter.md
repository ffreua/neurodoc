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

**Enviado em 2026-10-22**, depois da publicação da exigência de roteamento
(`04afb1e`) e **antes** de a reserva ser ligada, de `contato@neurodoc.app.br`,
pelo SMTP da instalação (no worker), com cópia oculta para
`contato@neurodoc.app.br`. O servidor aceitou os cinco:

| Clínica | Responsável (*owner*) | Plano | "Na sua clínica" |
| --- | --- | --- | --- |
| Caldas, Rego e Urbano Serviços Médicos | jcc.urbano@gmail.com | Completo | usa a IA da instalação |
| Caixeta Serviços Médicos (C e N Serviços Médicos LTDA) | saracaixetadesouza@gmail.com | Completo | usa a IA da instalação |
| Luca SB | suzano.luca@gmail.com | Gratuito | plano sem IA |
| Santos Dias Medical Care | amandaselvatici.consultorio@gmail.com | Gratuito | plano sem IA |
| Schalch Serviços Médicos | alexandre.schalch@gmail.com | Gratuito | plano sem IA |

Não receberam: a Freua Serviços Médicos (do titular, autor da mudança, que
usa a própria chave da OpenRouter e por isso nunca é atendida pela reserva)
e a FK Freua (do titular, plano sem IA).

**Ponto aberto a acompanhar:** o texto oferece, diante de oposição, manter a
reserva desligada para a clínica. Isso ainda **não existe por clínica** — a
reserva é da instalação inteira. Se alguma clínica se opuser, a resposta
imediata é desligar a reserva no console (um clique) enquanto a opção por
clínica é construída.
