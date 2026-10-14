# O tipo de consulta no modal, e o CRM que já está em outra conta

**Versão:** 1.10 · **Data:** 2026-10-08 ·
**Roteiros:** `check_tipo_de_consulta.py`, `check_crm_em_outra_conta.py`,
`check_idioma.py` §6

## 1. Trocar o tipo de um horário marcado

### O pedido

No modal do horário marcado, "Primeira consulta" era só um rótulo. A
secretária marca primeira consulta, o paciente liga dizendo que já veio
antes, e o único caminho era cancelar e marcar de novo, perdendo o
horário para quem estivesse olhando a agenda.

### O que entrou

O rótulo do tipo virou botão, e há também **Alterar o tipo de consulta**
na lista de ações. Os dois abrem o mesmo painel no próprio modal (modal
sobre modal perde o foco), com o seletor já no tipo atual.
`POST /app/scheduling/<id>/tipo/` → `services.change_appointment_type`.

### As duas travas

**Só antes do check-in.** O tipo escolhe o preço: é com ele que
`finance.receivables._price_for` acha a linha da tabela de honorários, e
a cobrança nasce no check-in. Trocar depois deixaria a cobrança com o
preço de um tipo e o agendamento dizendo outro. Agendado e confirmado
aceitam a troca. Chegou, em atendimento, concluído, falta e cancelado
recusam, no servidor; o JS só esconde o botão. Depois da chegada, o
lugar de corrigir é o financeiro, com ajuste e motivo.

**O horário não muda** (regra substituída na 1.13: a duração passou a acompanhar o tipo — ver `agenda-duracao-e-horario-extra.md`). A duração vem do tipo na hora de marcar, mas
trocar o tipo não estica nem encolhe a consulta. Esticar podia invadir o
horário seguinte, já ocupado. Encolher liberaria uma sobra que ninguém
pediu. O seletor mostra os tipos **sem** os minutos, de propósito, e o
painel diz: "Se a consulta precisar de mais tempo, use Remarcar".
Remarcar muda o quando; isto muda o quê.

O ato vai para a trilha (`scheduling.appointment_type_changed`, com o
tipo anterior e o novo). Trocar pelo mesmo tipo não grava nada.

A rota `tipo/` está declarada **antes** da genérica `<id>/<action>/`.
Depois dela, "tipo" seria lido como ação desconhecida e daria 404. O
roteiro confere a resolução.

## 2. O CRM que já está em outra conta

### O que aconteceu

O médico abriu uma segunda clínica, no plano Gratuito e para testar, com
um e-mail diferente do da conta onde já atende. Ao cadastrar o próprio
CRM na clínica nova, recebeu:

> Physician profile com este Crm number e Crm state já existe.

### Por que a recusa fica

O registro profissional (`PhysicianProfile`) é da **pessoa**: mora na
conta, e uma conta atende em quantas clínicas tiver vínculo. O CRM é
único no sistema inteiro, e essa unicidade é o que impede alguém de
abrir uma clínica gratuita, cadastrar o CRM de outro médico, validar a
si mesmo (quem valida é o responsável pela clínica) e **assinar documento
no nome dele**. Afrouxá-la para resolver o caso de quem tem duas contas
abriria esse caminho para qualquer um.

### O que estava errado

A recusa tinha dois defeitos:

- **estava em inglês.** A frase não está escrita em lugar nenhum: o
  Django a monta na hora, com os nomes do modelo e dos campos, que não
  têm tradução. Nenhuma varredura do `check_idioma` a via;
- **não dizia o caminho, que já existia.** Convidar para a clínica a
  conta onde o CRM está. O aceite por conta existente
  (`accept_collaborator_invitation_for_user`) cria o vínculo sem conta
  duplicada, e o registro vem junto.

### O que entrou

`PhysicianProfileForm.validate_unique` diz a recusa com as próprias
palavras, em duas variantes:

- **a outra conta é de fora da clínica:** "já está registrado em outra
  conta do NeuroDoc. Cada médico tem uma conta só, e ela pode atender em
  várias clínicas: convide para esta clínica o e-mail da conta onde ele
  está, com o papel de médico...";
- **a outra conta já é da equipe:** "dê o papel de médico ao vínculo
  dela, em Acesso".

**A mensagem não diz de quem é a outra conta.** O CRM é público, mas o
e-mail de quem o tem não é. A tela viraria uma consulta "CRM → e-mail"
aberta a qualquer responsável de clínica, inclusive à do Gratuito,
criada sem falar com ninguém.

### Para não voltar

`check_idioma.py` §6 é uma varredura, e não uma lista. Todo `ModelForm`
que expõe **todos** os campos de uma restrição de unicidade (o único caso
em que o Django a confere no formulário), num modelo sem nome em
português, tem de sobrescrever `validate_unique`. Hoje há um caso, este.
O `PatientForm` não entra porque não expõe `tenant`. Com a sobrescrita
removida, a seção reprova.

## Evidência

- `check_tipo_de_consulta.py`, oito seções: troca com horário intacto e
  trilha; mesmo tipo sem ato; confirmado aceita; os cinco estados
  posteriores recusam; tipo inventado recusado; rota própria e POST da
  secretária; POST direto depois da chegada; outra clínica com 404; o
  modal com o seletor e as três visões da agenda levando o código do
  tipo.
- `check_crm_em_outra_conta.py`, cinco seções: recusa em português, com
  o caminho e sem revelar o e-mail; a variante da equipe; a unicidade
  intacta no banco; editar o próprio registro passa; e o caminho
  recomendado funcionando de ponta a ponta.
