# Excluir contato da ficha

Versão 1.27. Roteiro: `checks/check_excluir_contato.py`.

A lista de Contatos do paciente tinha "Editar" e não tinha "Excluir". O botão
fica ao lado de "Editar", é `POST` com a pergunta do modal do sistema e usa a
mesma capacidade de quem cadastra (`PATIENT_ADMIN`).

## Apagar ou encerrar

`patients.contacts.remove_contact` decide, e para quem clicou o resultado é o
mesmo — o contato some da ficha e deixa de receber mensagens:

| Situação | O que acontece |
| --- | --- |
| Nenhuma entrega, link de documento ou destinatário de campanha aponta para ele | **apagado** do banco |
| Há histórico de envio | **encerrado**: validade vencida agora, autorizações desligadas, descadastrado da divulgação, links de documento ainda abertos revogados |

O histórico não deixa apagar porque a entrega aponta para o contato com
`PROTECT`, e é o comprovante de **para quem** uma receita foi enviada.

**Encerrar usa a validade (`valid_until`) que já existia**, e não uma coluna
nova "excluído": todo caminho que envia (documento, confirmação, lembrete,
aviso de horário, campanha) já recusa contato vencido. Uma marca nova teria
de ser lembrada em cada um deles.

As telas que mostram contatos — ficha, balcão do dia, retornos previstos e a
gaveta da ficha no atendimento — passam pelo filtro `nd_contatos_vigentes`,
que filtra em Python sobre o que já veio com `prefetch_related` (sem consulta
nova por linha). O contato encerrado também não abre pela URL antiga de
edição (404): editá-lo o traria de volta com as autorizações desligadas.

A trilha (`patients.contact_removed`) guarda o id do contato e o desfecho
(`apagado` ou `encerrado`), nunca nome, telefone ou e-mail.

## Homologação

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | O contato sem histórico sai do banco, com trilha sem dado pessoal? | Sim |
| 2 | O com histórico fica no banco, encerrado, e a entrega continua apontando para ele? | Sim |
| 3 | O encerrado deixa de ser elegível para documento e para a confirmação (SMS e e-mail)? | Sim |
| 4 | Ele volta pela URL de edição, ou é excluído duas vezes? | Não (404) |
| 5 | `GET`, outra clínica, rota de outro paciente? | Não excluem |
| 6 | O filtro das outras telas tira o encerrado e a agenda não oferece o telefone dele? | Sim |
