# 2026-11-22 — Lista curta do SNCR e o lugar no Dashboard

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc, na mesma rodada que o ProntDoc |
| Tipo | mudança (pedido do titular) |
| Publicado | não — junto com a campanha em HTML |

**SNCR.** O cartão "Pedidos" do painel crescia um item por tentativa de
login no Gov.br. Agora mostra no máximo seis pedidos comuns, os mais
recentes, e **sempre** os incertos — o único que pede ação (conferir no
portal ou dar por perdido) e que barra o pedido novo daquele tipo; cortar
por data o esconderia. O resto vai para o histórico paginado
(`/app/sncr/historico/`), com os mesmos botões (`templates/sncr/_pedido.html`).

**Dashboard.** O município era agrupado pela grafia: "Sao Paulo" e "São
Paulo" contavam como dois. Agora soma pelo nome sem acento e sem caixa,
com a UF, e mostra o nome do catálogo do IBGE (ou a grafia acentuada mais
frequente, com "do/da/de" em minúscula). Quem mora fora do Brasil caía em
"Não informado" ou numa sigla que não é UF: agora entra em "Exterior" no
gráfico de UF, aparece como Cidade/País no município, e há o cartão e o
CSV de **País**, com a mesma regra de célula pequena (menos de 5 vai para
"Outros países").

Feito igual nos dois lados (código idêntico). Roteiros:
`check_sncr_lista_de_pedidos` (novo) e `check_painel` (seção 9).
