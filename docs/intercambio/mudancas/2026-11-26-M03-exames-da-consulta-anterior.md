# MD-2026-11-26-03 — Exames da consulta anterior, por escolha do médico

**Data:** 2026-11-26. **Tipo:** mudança (pedido do titular). **Feito nos dois na mesma rodada** (PD-M-2026-11-26-03).

## O pedido

Nas consultas de seguimento, poder trazer da consulta anterior também os **exames**, além
de conduta, impressões, hipóteses e medicação — e o médico escolhe o que traz.

## O desenho: vínculo, não cópia

- `clinical.models.EncounterExamLink` (migração `clinical/migrations/0014_encounterexamlink.py`, só acrescenta uma tabela, com as
  chaves compostas por clínica da `0009`): o exame trazido é o **mesmo** `ExamResult` da
  consulta em que foi lançado. Copiado, o mesmo hemograma apareceria duas vezes na lista do
  paciente, na curva de evolução dos analitos, no contexto da IA e no acervo.
- `clinical/carry_forward.py`: cada exame da consulta de origem (lançado nela **ou** trazido
  para ela) vira um item `exam:<id>`, revisado como os outros (um a um ou "Trazer tudo");
  o que já está na consulta nova não vira item. Aceitar cria o vínculo, procurando o exame
  **no paciente e na clínica desta consulta** (id forjado não vincula nada).
- Tela: "Trazidos de consultas anteriores" no cartão de exames, só leitura, com a consulta de
  origem, o laudo e os analitos; "Retirar desta consulta" apaga só o vínculo (POST, consulta
  aberta, `WRITE_CLINICAL`, trilha `clinical.exam_link_removed` sem o nome do exame). Os
  dois resumos impressos dizem "trazido da consulta de dd/mm/aaaa". Descartar o rascunho leva
  os vínculos e deixa o exame. O hash do atendimento não muda (o vínculo não entra nele,
  como medicação e hipótese).
- **Só no NeuroDoc:** o texto livre ganhou o cartão "Resultados de exames" (como o ProntDoc já tinha), senão o exame aceito ficaria vinculado e invisível; `check_texto_livre` e `check_primeira_e_seguimento` procuravam `tab-exame` por pedaço de texto e passaram a conferir `id="tab-exame"` (o roteiro de exame neurológico), que é o que sempre quiseram barrar.

## Verificação

- `check_exames_da_consulta_anterior` (novo, 38 conferências), nos dois.
- Bateria inteira em quatro blocos (a corrida única foi interrompida por falta de memória no
  computador): só `check_copia_nuvem` falha, o defeito antigo do próprio roteiro.
