# WhatsApp da recepção (1.39)

**Roteiro:** `checks/check_whatsapp_recepcao.py`. **Código:**
`communications/whatsapp.py`, `scheduling/views.py::WhatsAppReminderView`,
`communications/admin_views.py::WhatsAppTextSaveView`.

## O que é

Na agenda (modal do horário, nas visões de semana, dia e mês) e no balcão do
dia, o botão **WhatsApp** abre a conversa com o paciente no **WhatsApp da
própria clínica** — WhatsApp Web, aplicativo de computador ou do celular —
com a mensagem de lembrete já escrita. A secretária confere e aperta enviar.

O texto é da clínica: **Integrações → SMS, e-mail e WhatsApp**, cartão
**WhatsApp da recepção**, com os campos que o sistema preenche:

| Campo | O que entra |
| --- | --- |
| `{primeiro_nome}` | primeiro nome do paciente, sem caixa alta ("Maria") |
| `{paciente}` | nome completo ("Maria da Silva") |
| `{data}` | data da consulta, dd/mm/aaaa, no dia de Brasília |
| `{dia_semana}` | "terça-feira" |
| `{hora}` | "14:30" |
| `{medico}` | nome do médico do horário |
| `{tipo}` | tipo de atendimento (Primeira consulta, Seguimento, Retorno…) |
| `{clinica}` | nome fantasia, ou a razão social |
| `{endereco}` | endereço da Identidade da clínica |
| `{telefone_clinica}` | telefone da Identidade da clínica |

Em branco, vale o **texto padrão** do sistema (com a linha do endereço só se a
clínica tiver endereço cadastrado). A caixa já abre com ele, para editar; salvo
sem mudança, continua sendo o padrão.

## Por que não é envio automático

Estudado em 2026-11-08, com a documentação oficial da Meta:

- **API oficial (WhatsApp Cloud API):** exige o NeuroDoc credenciado como
  provedor (Tech Provider) na Meta, cada texto aprovado como modelo (até 24 h,
  e qualquer edição volta à análise; corpo de até 1.024 caracteres), cartão de
  cada clínica na conta dela e cobrança por mensagem (cerca de R$ 0,035 por
  lembrete no Brasil, desde 01/10/2026). Limite inicial de 250 pacientes
  diferentes por dia, 2.000 com a empresa verificada. Fica para depois, se o
  volume pedir.
- **Conexão por QR Code** (Baileys, Evolution API, Z-API): imita o WhatsApp
  Web, fere os termos do WhatsApp e expõe o número da clínica a bloqueio, além
  de deixar no servidor uma sessão que lê todas as conversas dela. Recusado.

O link `wa.me` é o caminho público do WhatsApp para abrir uma conversa: não
precisa de cadastro nem de aprovação, aceita acento e o texto inteiro, não tem
custo e não põe o número em risco, porque quem envia é uma pessoa.

## Decisões

- **Em todos os planos.** Não é recurso de plano nem consome SMS: o envio é
  da clínica, pelo WhatsApp dela. O resto da mensageria (e-mail e SMS
  automáticos, SMS por plano) não mudou.
- **Quem edita o texto:** quem já configura SMS e e-mail
  (`MANAGE_INTEGRATIONS`: dono e gestor). **Quem usa o botão:** todo vínculo
  com acesso à agenda (`SCHEDULE`).
- **O telefone** é o da confirmação por SMS (`confirmation_contacts`): o
  contato do próprio paciente primeiro, contato vencido fora. O número vai ao
  formato do `wa.me` (só dígitos, com o 55): DDD sem país ganha o 55, "+" de
  outro país vale como veio, e número sem DDD é pulado — sem nenhum que sirva,
  a agenda diz para corrigir a ficha.
- **`GET`, e não `POST`.** A CSP tem `form-action 'self'`, e o navegador
  recusa o salto para o `wa.me` no fim de um formulário (a mesma razão do
  Gov.br no SNCR). O `GET` não muda o horário: só registra na trilha
  `scheduling.whatsapp_aberto`, **sem telefone nem texto**. Se a mensagem foi
  enviada, só o WhatsApp sabe.
- **A rota monta o texto na hora do clique.** O link não vai pronto na grade:
  a semana montaria uma mensagem por horário a cada abertura.
- **Campos numa lista fechada, por expressão regular.** `str.format` deixaria
  `{paciente.__class__}` atravessar atributos; o campo desconhecido é recusado
  ao salvar, com a lista dos válidos.
- **Nada clínico nos campos.** O texto passa pelos servidores do WhatsApp, e a
  política dele manda não trafegar informação de saúde.
- **Balcão:** o botão aparece só antes da chegada (agendado ou confirmado) e
  com telefone. A lista passou a pré-carregar os contatos (`prefetch_related`)
  e não faz mais uma consulta por linha.

## O que o roteiro cobre

Telefone em dez formatos; nome sem caixa alta e com as partículas
minúsculas; a lista fechada de campos (inclusive a tentativa de atravessar
atributo); a mensagem com e sem endereço, o texto da clínica, o dia da semana e
a data de Brasília às 23h30; a escolha do contato; a rota (redireciona com o
texto inteiro e com acento, trilha sem dado pessoal, recusa de cancelado e de
paciente sem celular, 404 de outra clínica, 405 para POST); a tela no plano
Gratuito, a prévia, salvar, recusar sem gravar, voltar ao padrão, a caixa
pré-preenchida e o padrão salvo sem mudança; o botão no modal e no balcão; e o
número de consultas do balcão igual com cinco horários a mais.

## Para usar

No computador, deixe o **WhatsApp Web** (ou o aplicativo) da clínica aberto e
conectado no navegador da recepção: o botão abre uma aba que leva até ele. No
celular, abre o aplicativo do WhatsApp.
