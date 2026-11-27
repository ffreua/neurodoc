# MD-2026-11-27-03 — Comunicados do console ao sino e ao celular

**Data:** 2026-11-27. **Tipo:** mudança (pedido do titular). **Feito nos dois na mesma rodada** (PD-M-2026-11-27-03).

## O que mudou

- `/instalacao/comunicados/` (`ops/superadmin.py::ComunicadosView`): o superadministrador escreve
  título, texto e link opcional (só do próprio site), escolhe o tipo (**aviso do sistema** ou
  **propaganda**) e o público (todas as clínicas, um plano, uma clínica, um papel), vê a prévia
  (clínicas, pessoas, aparelhos) e envia com o código do segundo fator recente.
- `notifications/comunicados.py` + `Comunicado` (migração `notifications.0004`): o worker cria uma
  linha no sino por vínculo (tipo `comunicado`) e manda o aviso no celular com o título e o começo
  do texto; a página `/app/notifications/comunicado/<id>/` abre para quem recebeu.
- **Sem recusa**, por decisão do titular.
- **Propaganda travada** até `tenancy.plans.CONTRATO_COM_PROPAGANDA` e, depois, só para a clínica
  cujo último aceite é dessa redação: o contrato vigente cobre o aviso (cláusula 18.1), não a
  publicidade. Minuta em `docs/governance/comunicados-minuta.md`, para a Dra. Karina.

## Diferenças entre os lados

`CONTRATO_COM_PROPAGANDA` é **2.5** no NeuroDoc e **1.4** no ProntDoc (a série de cada contrato);
a minuta de cada lado cita a própria versão. O resto do código é igual.

## Verificação

`check_comunicados`, `check_push`, `check_super`, `check_idioma` e os vizinhos, nos dois.
