# 2026-11-20 — Registro de telas lentas e a estimativa de capacidade

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc 1.54, na mesma rodada que o ProntDoc 1.8.0 |
| Tipo | mudança (operação) |

Feito igual nos dois lados: `base/lentidao.py` (middleware, limpeza e
resumo), `base.TelaLenta` com a migração `0005_telalenta`, a tarefa diária
`base.tasks.apagar_telas_lentas`, a tela do console `superadmin:telas-lentas`,
a chave opcional `TELAS_LENTAS_MS` (em `ops/make_runtime.py`) e o roteiro
`check_telas_lentas`. A estimativa de capacidade medida está em
`docs/operations/capacidade.md` de cada lado, com a carga real de cada um.

Conclusão registrada: o teste de carga (Locust) não é necessário agora; o
registro de telas lentas é a medida contínua, e ele diz quando passar a ser.
