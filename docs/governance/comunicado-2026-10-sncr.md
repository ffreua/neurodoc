# Comunicado às clínicas — Receita de Controle Especial a partir de 31/10/2026

**Decidido pelo proprietário em 2026-10-21** (decisão D1,
[`docs/sncr/DECISOES.md`](../sncr/DECISOES.md)). Informa a mudança da
NeuroDoc 1.21.1, que antecipa no sistema a exigência da Anvisa.

**Envio:** de `contato@neurodoc.app.br`, pelo SMTP da instalação, um
e-mail por clínica, ao responsável (papel *owner*) das clínicas de
terceiros, com cópia oculta para `contato@neurodoc.app.br`, que guarda o
registro. O registro do envio, com data e destinatários, fica no fim
deste arquivo.

---

**Assunto:** NeuroDoc — Receita de Controle Especial a partir de 31/10/2026 (SNCR/Anvisa)

Prezado(a) responsável pela {clínica},

A partir de 31 de outubro de 2026, a Anvisa passa a exigir a numeração do
Sistema Nacional de Controle de Receituários (SNCR) em toda Receita de
Controle Especial (RCE) e Receita Sujeita à Retenção (RET) **emitida
eletronicamente** (RDC nº 1.000/2025; Perguntas e Respostas da RDC 1.000,
2ª edição, perguntas 30 e 50).

O NeuroDoc está implantando a integração com o SNCR. Até ela entrar em
funcionamento, o sistema passa a funcionar assim:

- **Receita de Controle Especial:** a partir de 31/10, deixa de ser
  assinada digitalmente e sai pelo botão "Emitir para assinar e
  carimbar" — o médico imprime, assina à mão e carimba. A receita
  impressa continua válida, no leiaute da clínica.
- **Antimicrobianos e agonistas de GLP-1** (receita sujeita à retenção):
  a versão eletrônica também passa a exigir a numeração. O NeuroDoc avisa
  na tela da receita; nesses casos, emita para assinar e carimbar.
- **Receitas simples dos demais medicamentos, relatórios, pedidos de exame
  e encaminhamentos** continuam sendo assinados digitalmente, como hoje.

A tela de cada receita já mostra um aviso explicando a regra. Quando a
integração estiver concluída, avisaremos: a receita eletrônica voltará a
ser assinada digitalmente, já com a numeração oficial — cada médico com
o próprio bloco de números, obtido com o login no Gov.br.

Nenhuma ação é necessária da sua parte agora. Em caso de dúvida, basta
responder a este e-mail.

Atenciosamente,

Dr. Fernando Freua
NeuroDoc — contato@neurodoc.app.br

---

## Registro do envio

**Enviado em 2026-10-21**, depois da publicação da 1.21.1, de
`contato@neurodoc.app.br`, pelo SMTP da instalação (no worker), um e-mail
por clínica, com a saudação ao nome da clínica e cópia oculta para
`contato@neurodoc.app.br`. O servidor aceitou os cinco:

> Os endereços dos responsáveis saíram deste arquivo em 2026-10-30: o
> repositório é público, e e-mail de pessoa é dado pessoal. O registro com
> os endereços fica na cópia oculta guardada em `contato@neurodoc.app.br`.

| Clínica |
| --- |
| Caldas, Rego e Urbano Serviços Médicos |
| Caixeta Serviços Médicos (C e N Serviços Médicos LTDA) |
| Luca SB |
| Santos Dias Medical Care |
| Schalch Serviços Médicos |

As duas clínicas do próprio titular (Freua Serviços Médicos e FK Freua)
não receberam, por ele ser o autor da mudança. Em produção, as 5 RCE
assinadas digitalmente até esta data são todas da clínica do titular.
