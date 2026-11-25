# Teleatendimento: link do vídeo, e-mail ao paciente e termo de consentimento

Registro das decisões do recurso de teleatendimento por vídeo (1.58), para
quando alguém (ou algo) chegar depois e precisar saber **por quê** está assim.

## O que o recurso faz

O horário já podia ser marcado como **teleatendimento** (1.43, marca de
agenda). A 1.58 acrescenta, no horário por vídeo:

1. **Link do vídeo** (`Appointment.teleatendimento_link`): a secretária ou o
   médico cola o link da chamada — Meet, Teams, cockpit do Einstein, o que a
   clínica usar. É informação de agenda, como a marca: não muda duração,
   preço, lembrete nem prontuário, e não mexe em `row_version`.
2. **Botão "Enviar link"**: manda ao e-mail do paciente o link, as orientações
   e o aviso do termo. Sai **pelo worker** (o `app` não tem SMTP, §2), como a
   confirmação manual do horário.
3. **Página pública do termo** (`/termo-teleconsulta/`): o texto do
   consentimento, que o paciente lê sem conta.

## Decisões e o porquê

- **O e-mail do teleatendimento é à parte do aviso comum de horário.** O link
  e as orientações do vídeo **só saem quando alguém clica em "Enviar link"** —
  nunca junto com a confirmação de marcação/remarcação/cancelamento. A maioria
  das consultas é presencial, e o aviso de sempre não deve mudar. No código,
  é uma entrega própria (`communications.enviar_link_teleconsulta` +
  `enviar_link_teleconsulta_task`), separada de `deliver_appointment_notice` e
  `send_appointment_confirmation`.

- **Aceite por participação, sem assinatura por paciente.** O próprio termo diz
  que "participar da teleconsulta implica em concordar com este termo". Por
  isso a página é **pública e genérica** (sem nome de paciente, de clínica nem
  do médico): o paciente, o representante legal, o médico responsável (CRM/UF)
  e a plataforma são os do convite que a clínica enviou. Não se grava
  assinatura nem aceite por paciente — seria um depósito novo de dado pessoal
  para sustentar um aceite que o próprio texto dispensa.

- **O link não vai para a trilha de auditoria.** Um link de sala de vídeo pode
  carregar um token que dá acesso à chamada; a trilha não é lugar de
  credencial. O audit event registra só **se** o campo foi preenchido
  (`scheduling.appointment_teleatendimento_link_changed`) e, no envio,
  contato/status/tentativa — nunca o link (`communications.teleconsulta_link_sent`).

- **O nome da plataforma é por conveniência, não por permissão.** O e-mail diz
  "Google Meet", "Microsoft Teams" etc. quando reconhece o domínio do link
  (`communications.plataforma_do_link`); qualquer outra plataforma é aceita e
  enviada igual, só sem o nome por extenso. Não há lista de permissão de
  domínios — a clínica escolhe a ferramenta.

- **Exige a marca e o link.** Guardar o link exige o horário marcado como
  teleatendimento e ainda da agenda (não concluído/cancelado/falta). Enviar
  exige link preenchido e um contato de e-mail do paciente; a falta de um ou
  de outro é dita na tela, não descoberta tarde numa lista.
  O link precisa ser endereço web (`http`/`https`) de até 500 caracteres
  (`scheduling.services._conferir_link_de_video`): o serviço grava sem
  `full_clean`, e sem essa conferência um `javascript:` ou um texto qualquer
  iria ao paciente como "link do vídeo", e um link enorme estourava a coluna
  com erro 500. Vazio é permitido — é como se retira o link.

## O texto do termo

A redação é da **Dra. Karina Albuquerque Freua (OAB/SP nº 450.476)**, a mesma
que redige o contrato de adesão. **Correção de texto passa por ela** — texto
novo é versão nova do termo, como no contrato. A **autorização da redação não
consta na página** (ela é vinculada ao NeuroDoc e ao ProntDoc, e o termo que o
paciente lê é só o consentimento). O texto vigente está em
`templates/onboarding/termo_teleconsulta.html`, com as cinco cláusulas:
distância e limites do exame; direito de recusar/interromper; riscos de conexão
e privacidade; autorização de transmissão de dados sem gravação sem
consentimento específico; e urgência/emergência presencial.

## Verificação

`checks/check_teleconsulta_link.py`: o campo guardado e exigindo a marca; o
envio pelo worker com o link e o endereço do termo no corpo, só ao e-mail do
paciente; o nome da plataforma pelo domínio; a página pública abrindo; as
recusas (horário concluído/cancelado, outra clínica, sem link, sem e-mail); e
a trilha sem o link. A secretária **pode** enviar o link — é tarefa de
recepção, como marcar o teleatendimento —, e por isso não é recusa.
