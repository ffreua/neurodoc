---
id: MD-2026-11-19-03
data: 2026-11-19
origem: sessao-unica
tipo: mudanca
sigiloso: nao
estado_aqui: feito e verificado no ambiente local
roteiro_aqui: checks/check_ordem_exames_e_medicacoes.py
no_outro: feito na mesma rodada — PD-M-2026-11-19-03
---

# Exames do mais recente ao mais antigo, e medicações agrupadas por situação

**Pedido do titular.** Na aba de resultados de exame, o mais recente em
cima e o mais antigo embaixo; nas medicações, as em uso juntas e as
suspensas juntas.

**O que havia.** A ordem dos exames já era `-performed_on`, mas no
PostgreSQL a ordem decrescente põe o **nulo primeiro**: exame sem data subia
ao topo, acima do mais recente (em produção do NeuroDoc eram 5 de 70). A
mesma ordem servia à IA, que lê só os 15 mais recentes — exame sem data
tomava a vaga de um recente. No mesmo dia, desempate por nome. As
medicações saíam só por nome, com a suspensa no meio das em uso.

**O que mudou.** A ordem mora num lugar só, `clinical/ordem.py`:

- exame: data de realização decrescente, **sem data no fim**, e no mesmo
  dia o registrado por último em cima;
- medicação: em uso, depois suspensas, depois concluídas; por nome dentro
  de cada grupo.

Aplicada a toda leitura dessas listas: a aba do atendimento, o resumo do
atendimento e o de todos, a gaveta da consulta anterior, a exportação do
acervo e as ferramentas da IA. Sem migração, sem campo novo.

**Verificação.** `checks/check_ordem_exames_e_medicacoes.py`, pela posição
no HTML, com nomes e datas criados fora de ordem. Contra o código antigo
reprovou em 8 pontos (inclusive a IA lendo o exame sem data no lugar do
mais recente); com a correção, passa nos dois sistemas. Vizinhos que
passaram: medicação (editar), resumo do caso, exportação, chat, o que vai à
IA, prontuário, texto livre e isolamento (e, no NeuroDoc, relatório da IA,
estruturado e intercâmbio).
