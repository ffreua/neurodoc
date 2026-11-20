# 2026-11-20 — Grafo do código e o traçado do vínculo

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc, na mesma rodada que o ProntDoc |
| Tipo | documentação e ferramenta de contexto; nada no produto mudou |
| Pedido | do titular: o grafo (graphify) e o mapa (Cartographer) existem para trazer contexto da forma certa a quem coda |

O que entrou, igual nos dois lados (com os números de cada um):

- `docs/GRAFO.md`: onde o grafo entra entre regras, mapa e código; como
  reconstruir e consultar; as armadilhas de leitura; as espinhas; o
  traçado do `Membership` até a permissão, conferido linha a linha; a
  lista de conferência ao codar; e a comparação entre os dois sistemas.
- `scripts/grafo_codigo.py`: reconstrói o grafo só do código, sem tokens,
  com o recorte e os nomes de comunidade fixos. `graphify-out/` fica no
  `.git/info/exclude`.

Achado do traçado: os nove arquivos da cadeia vínculo → permissão
(`tenancy/middleware.py`, `tenancy/context.py`, `tenancy/permissions.py`,
`ai/context.py`, `ai/sse.py`, `teamchat/sse.py`,
`accounts/dispositivo_confiavel.py`, `reporting/painel.py`,
`notifications/services.py`) são **idênticos** nos dois sistemas. Mudança
num deles vale, sem adaptação, no outro — e deve ser conferida lá.
