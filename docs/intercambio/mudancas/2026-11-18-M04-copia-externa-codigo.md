---
id: MD-2026-11-18-01
data: 2026-11-18
origem: sessao-unica
tipo: operacao
sigiloso: nao
estado_aqui: corrigido
commit_aqui: ver `git log --grep "2026-11-18"`
roteiro_aqui: execução do script com disco ausente (código 2) e com destino válido (código 0)
no_outro: corrigido-na-mesma-rodada
---

# Cópia externa: disco ausente sai com código 2, como o script pretendia

`scripts/puxar_backups.ps1` dizia `exit 2` para o disco não montado, mas
chamava `Write-Error` antes, com `$ErrorActionPreference = 'Stop'`: o script
terminava ali mesmo, com código 1. No agendador, "SSD fora da tomada" (que se
resolve plugando) ficava igual a "uma cópia não conferiu com o manifesto"
(que pede investigação). Em 2026-11-17 a tarefa do NeuroDoc saiu com 1, e o
`D:` não estava montado.

**Correção:** a mensagem sai por `Write-Host` e o `exit 2` é alcançado.
Conferido: destino num disco inexistente → código 2, nada copiado.
`docs/operations/copia-externa.md` passa a listar os três códigos.

**No ProntDoc:** o script é o mesmo (só os caminhos mudam); corrigido e
conferido na mesma rodada, com os códigos 2 e 0.

**Cópia e prova de restauração (2026-11-18):** com o SSD plugado, a tarefa
trouxe 32 backups (49 no disco), todos conferidos; a última cópia era de
08/10. O backup de 17/11 foi restaurado num PostgreSQL descartável, sem
erro e com as contagens da produção (`docs/operations/restore.md`,
"Terceira prova").

**Também conferido nesta rodada, sem mudança aqui:** HSTS
(`max-age=31536000; includeSubDomains`) e CSP em modo bloqueio continuam
ligados na produção do NeuroDoc, e `APP_WORKERS`/`WORKER_CONCURRENCY` estão
em 4 e 6, como os documentos dizem.
