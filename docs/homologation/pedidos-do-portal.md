# Pedidos do portal pelos caminhos do sistema

Versão **1.40** (2026-11-09). Roteiro: `checks/check_portal_unissono.py`.
Código: `documents/pedidos_do_portal.py`, `documents/request_views.py`,
`templates/documents/_campos_da_receita.html`,
`templates/documents/request_detail.html`, `ai/views.py` (relatório com o
pedido vinculado) e `sncr/receita.py::formato_sugerido`.

## O que estava errado

O médico pediu, pelo portal, uma receita de controle especial a si mesmo,
como teste, e não conseguiu emiti-la. A tela de atender o pedido desenhava só
dois campos da receita: o formato e o texto livre. Ele escolheu o formato
eletrônico do SNCR, e o servidor passou a exigir os medicamentos
estruturados (nome, concentração, forma farmacêutica, quantidade e
posologia), que a tela não tinha. A recusa voltava como "Confira o conteúdo
do documento antes de gerar o rascunho", sem nenhum campo marcado.

Era o sintoma de um desenho: o pedido do portal tinha **caminhos próprios**,
paralelos aos do resto do sistema. A receita não chegava à receita do SNCR,
e o relatório não chegava ao relatório com apoio de IA.

Dois defeitos menores apareceram junto:

- a **recusa sem motivo** voltava à mesma tela, com um aviso só no alto da
  página, e o pedido continuava na fila sem dizer por quê;
- a coluna **"Por"** da fila mostrava "—" em todas as linhas: o template lia
  `user.full_name`, que não existe (o certo é `get_full_name`).

## A regra

**O pedido entra pelos caminhos que já existem, em vez de ter os seus.** O
que é do pedido — o ponto de partida que ele sugere e o registro de que foi
atendido — mora em `documents/pedidos_do_portal.py`; o resto é o do sistema.

### Receita

- A tela do pedido usa o **mesmo bloco** da tela de emissão
  (`_campos_da_receita.html`, incluído pelas duas), com o mesmo JavaScript
  (`documents/medical_form.js` e a busca da CMED). Um bloco só é o que impede
  as duas telas de divergirem de novo.
- Os itens do SNCR já vêm preenchidos com o que o paciente escreveu: **o nome
  vira o medicamento, a dose vira a concentração e o modo de usar vira a
  posologia**. Forma farmacêutica e quantidade ficam em branco: o paciente não
  as informa, e inventá-las seria escrever na receita o que ninguém disse.
  Até 3 medicamentos (`receita.LIMITE_MEDICAMENTOS`); se o pedido tiver mais,
  a tela diz quantos ficaram de fora.
- **O formato inicial**, com a numeração do SNCR ligada, é o que a **lista
  oficial da Portaria 344** indica para os nomes pedidos
  (`sncr.receita.formato_sugerido`): clonazepam (B1) abre na Notificação de
  Receita B, e sertralina (C1) abre na RCE. O pedido de "receita simples" de
  um controlado também abre no formato do controlado, porque controlado nunca
  vai em receita simples (FAQ de Integração, P48). Quando os nomes pedem
  receituários diferentes, nada é escolhido sozinho: o controle especial abre
  na RCE, e a simples, na simples. Com o SNCR desligado, nada muda: o formato
  é o do pedido.
- **É só o valor inicial.** O seletor continua aberto, e a classificação de
  verdade, com a confirmação do médico quando a lista não decide, acontece na
  emissão (`receita.preparar`), como em qualquer receita.
- **Os erros ficam no formulário.** O que falta fica marcado no próprio campo.
  A recusa da lista oficial (o tipo errado, o endereço, o CPF) volta com o que
  foi digitado, em vez de redirecionar e apagar a receita da tela.

### Relatório

- Em planos com IA, a tela do pedido de relatório tem **Redigir com IA**, que
  abre o relatório com IA (`ai:relatorio-novo?pedido_portal=<id>`) já com a
  finalidade sugerida e o pedido do paciente na caixa. Escrever à mão
  continua na mesma tela.
- A finalidade do portal sugere a da IA (`FINALIDADE_DA_IA`): INSS, plano de
  saúde, e trabalho ou escola. As terapias e "Outro" vão para a livre, e o
  médico troca a escolha na tela.
- O id do pedido é conferido por inteiro a cada passo: da clínica, do
  paciente, de relatório e ainda aberto. Um id que não confere não dá erro; o
  relatório segue, só sem responder a nenhum pedido.
- Pedir à IA põe o pedido **em revisão**, que continua aberto. A fila mostra
  *rascunho com IA em andamento*, e a tela do pedido lista os rascunhos.
- **Aprovar o rascunho atende o pedido** com o relatório, na mesma transação
  que cria o documento. A trilha registra `documents.portal_request_drafted`
  com `via_ia`. Se o pedido teve outro desfecho enquanto a IA escrevia (por
  exemplo, se foi recusado), o relatório sai do mesmo jeito e o pedido fica
  como estava.
- **O pedido vai desidentificado ao provedor.** O texto do pedido do
  relatório ia à IA como foi digitado, sem passar pela desidentificação, que
  só tratava o contexto. Com o texto do paciente vindo do portal, onde nome,
  CPF e telefone aparecem com naturalidade, isso deixou de ser aceitável:
  agora ele passa por `deidentify_text`, como o resto
  (`ai/services.py::_gather_patient_report_context`).

### Atendido, num lugar só

`pedidos_do_portal.marcar_atendido` é a única porta para dar o pedido como
atendido, com duas entradas: o rascunho criado na tela do pedido e o relatório
da IA aprovado. Ela relê a linha com trava e só atende o pedido que ainda está
aberto. Na tela do pedido, o rascunho e a marca de atendido estão na mesma
transação: se outro médico tiver respondido no meio, nada é criado.

### Recusa

O campo diz **Motivo da recusa (obrigatório)**, o navegador barra o envio
vazio (`required`), e o servidor confere de novo, inclusive o motivo só com
espaços. Nesse caso a tela é desenhada de novo com o erro no próprio campo, e
o pedido continua na fila.

## O que ficou de fora, de propósito

- **O pedido de exames** continua virando o pedido genérico
  (`requested_procedure`), e não o pedido de exames por modelo (`PEX-`). A
  emissão por modelo é do atendimento e escreve na conduta
  (`modelos/emissao.py`), e o pedido do portal não nasce de atendimento.
  Ligá-los é trabalho à parte.
- **O pedido do paciente não é editado** em nenhum dos caminhos.
  `DocumentRequest.payload` é o registro do que foi pedido.

## Homologação

`check_portal_unissono.py`, dentro de uma transação desfeita (o provedor de
IA nunca é chamado), cobre as dez partes listadas no topo do roteiro. A
bateria inteira continua verde. `check_resto.py` (a seção 5, o pedido
editável) e `check_receitas.py` (a caixa de busca, que mudou para
`_campos_da_receita.html`) continuam passando.
