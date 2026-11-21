# 2026-11-20 — Compressão do HTML e o diagnóstico da vitrine lenta

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc, na mesma rodada que o ProntDoc |
| Tipo | mudança (desempenho); sem versão nova (correção sem funcionalidade) |
| Escolha | do titular, entre cinco opções: só a compressão |

O registro de telas lentas apontou a vitrine com ~1,4 s no servidor. Medido
dentro do contêiner de produção, ela monta em ~25 ms: o tempo era a
distância (~0,4 s, servidor nos EUA), o HTML sem compressão até a
Cloudflare (+0,25 a 0,45 s conforme o tamanho) e o aquecimento de cada
processo depois de um deploy (1,2 a 1,6 s, só a primeira visita).

Feito igual nos dois lados: `base/compressao.py` (gzip do Django com a
proteção BREACH; só texto; nunca stream) logo depois do
`SecurityMiddleware`, e o roteiro `check_compressao`. No navegador, a
vitrine passou de 124 KB a ~21 KB transferidos.

Não feito, por escolha: aquecer os processos ao subir, guardar a vitrine
na Cloudflare (quebraria o CSRF do formulário e o nonce da CSP), ler a
configuração do checkout uma vez só, e o estudo de servidor no Brasil.

A CPU da VPS nova é ~2x mais lenta que a do computador das medidas: a
estimativa de capacidade foi corrigida em `docs/operations/capacidade.md`.
