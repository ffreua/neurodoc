# TISS e agenda de exames — ativação, reversão e homologação

Para quem opera a instalação e para a clínica-piloto. O que foi construído
em cada sprint está em `ESTADO_EXECUCAO.md`; a revisão e as fontes, em
`REVISAO_SPRINT1.md`.

## 1. O que está pronto, e em que grau

A classificação é a do pedido do módulo, e cada grau é diferente do
seguinte.

| Item | Implementado | Validado por XSD | Validado por regras | Aceito em homologação da operadora | Liberado em produção |
| --- | --- | --- | --- | --- | --- |
| Guia de Consulta, versões 3.04.00 a 4.03.00 | sim | sim (as sete) | sim | **não** | **não** |
| Guia SP/SADT, versões 3.04.00 a 4.03.00 | sim | sim (as sete) | sim | **não** | **não** |
| Hash do epílogo | sim | — | vetor próprio | **não** — três detalhes que o manual da ANS não decide (topo de `tiss/xml.py`) | **não** |
| Agendas de exame (EEG, ENMG, PSG) | sim | — | sim | — | **não** |

As versões 3.04.00 e 3.05.00 só geram arquivo de cobrança com o aceite
da operadora registrado no credenciamento. Nenhuma operadora foi
homologada; nada foi enviado a portal nenhum.

## 2. Ativar numa clínica

Pré-requisito: a versão publicada é a 1.30 ou posterior.

1. **No worker**, a lista de operadoras da ANS:
   `python manage.py import_operadoras_ans` (ou esperar a tarefa de
   segunda-feira, 05h).
2. **Console → Operação → Faturamento TISS**: digitar `LIGAR` e o motivo.
   Esta chave vale para a instalação inteira e só para o faturamento.
3. **Console → Organizações → a clínica** (plano Completo ou
   Personalizado) → **TISS** → motivo → **Liberar TISS**. A liberação
   abre também a **Agenda de exames** da clínica.
4. Na clínica, o responsável ou o gestor:
   - **Convênios e planos**: as operadoras, com o registro ANS (pela busca
     da lista da ANS);
   - **Faturamento TISS**: prestador, credenciamento por operadora (código
     do prestador, versão, ciclo, portal) e profissionais;
   - **Agenda de exames → Configurar agendas**: uma agenda por equipamento,
     com horários e código TUSS;
   - **Convênios e valores**: o honorário de cada procedimento por plano
     (sem ele, o exame realizado não gera cobrança e a guia pede o valor).

## 3. Desligar e reverter

| O que | Como | O que acontece |
| --- | --- | --- |
| Parar o faturamento na instalação inteira | Console → Operação → Faturamento TISS → **Desligar** (um clique) | Nenhuma tela do TISS abre e nenhum arquivo é gerado. A **agenda de exames continua** — os exames marcados não somem da recepção. Nada é apagado |
| Tirar o módulo de uma clínica | Console → Organizações → a clínica → TISS → **Recolher** | Some o TISS **e** a agenda de exames dessa clínica. Guias, lotes, arquivos, exames e cobranças ficam no banco |
| Rebaixar o plano | o de sempre | Igual a retirar: congela, nada é apagado |
| Voltar a versão do produto | `docker service rollback` nos três serviços (`docs/operations/rollback.md`) | As migrações da 1.30 são só de expansão: a 1.29 ignora as tabelas e colunas novas. **Atenção:** a 1.29 não conhece a cobrança de exame (`reserva_exame`) — ela continua no banco e aparece no financeiro sem origem legível até a 1.30 voltar |

Cobrança já criada por um exame realizado **não** é desfeita por nenhum
desses caminhos: ela é financeiro, e se ajusta no financeiro, com motivo.

## 4. O que vigiar nas primeiras semanas

- **Lotes em falha**: `Faturamento TISS → Lotes`, filtro "Falha na
  geração". A mensagem diz o campo e a guia. Lote parado em "gerando" por
  mais de 10 minutos é reenviado sozinho ao worker.
- **Trilha**: `tiss.lote_falhou`, `tiss.lote_arquivo_invalido` (arquivo
  diferente do SHA-256 gravado — **não enviar** o lote) e
  `finance.receivable_pricing_missing` com `object_type=reserva_exame`
  (exame realizado sem honorário cadastrado).
- **Lembretes de exame**: na tela de entregas, "Exame — dd/mm hh:mm".

## 5. Roteiro de homologação com a clínica-piloto

O que só a clínica real prova. Cada passo registra a data, quem fez e o
resultado aqui embaixo — inclusive o que der errado.

1. **Configuração.** Os credenciamentos com a versão que cada operadora
   aceita **hoje** (perguntar à operadora, não supor pela versão que outro
   sistema usava). Para versão 3.x, registrar no credenciamento quem da
   operadora confirmou e quando.
2. **Uma guia de cada.** Uma Consulta (de um check-in real) e uma SP/SADT
   de exame realizado, conferidas campo a campo contra a guia que a
   clínica emitiria no sistema atual (GuiasTiss) para o mesmo atendimento.
3. **O primeiro arquivo.** Um lote de **uma** guia, enviado ao ambiente de
   homologação (ou de teste) do portal de cada operadora, com dado
   autorizado pela clínica. Anotar se o portal aceitou o arquivo, e, se
   recusou, a mensagem exata. Uma recusa por **hash** decide os três
   detalhes em aberto de `tiss/xml.py` — corrigir lá, com o vetor da
   operadora no `check_tiss_lotes`.
4. **Um lote real pequeno**, depois do aceite do passo 3, e o retorno da
   operadora registrado no lote.
5. **Agenda de exames por uma semana**, em paralelo com a agenda atual da
   clínica, incluindo pelo menos uma polissonografia noturna. Conferir que
   o lembrete chegou e que a cobrança do exame bate com a tabela.
6. Só então: o credenciamento passa a ser usado no faturamento do mês, e a
   linha da operadora vai para "Aceito em homologação" na tabela do §1.

### Registro da homologação

| Data | Operadora | Versão | Passo | Resultado | Quem |
| --- | --- | --- | --- | --- | --- |
| — | — | — | — | (nenhum ainda) | — |
