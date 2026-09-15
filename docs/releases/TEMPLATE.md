# Release `<SHA-de-40-caracteres>`

| Campo | Valor |
| --- | --- |
| SHA Git | `<40 caracteres, `git rev-parse HEAD`>` |
| Data da homologação | `<AAAA-MM-DD>` |
| Responsável que assinou | `<nome e papel>` |
| Ambiente homologado | `<local / staging ACME / produção>` |
| Imagem publicada | `ghcr.io/ffreua/neurodoc:<SHA>@sha256:<digest>` |

## Gates de homologação (seção 21 do PRD)

| Gate | Situação | Evidência |
| --- | --- | --- |
| H-01 … H-23 | `<aprovado / aprovado com ressalva / não exercitado>` | `<caminho em docs/homologation/>` |

## Mudança de schema

- Migrations novas nesta release: `<lista, ou "nenhuma">`
- Natureza: `<expand / contract>` — `NEURODOC_SCHEMA_CHANGE=expand` é o
  único valor que o preflight aceita. Migration que remove coluna, tabela ou
  restrição é *contract* e exige janela de manutenção própria.
- Reversível sem perda de dado? `<sim / não — e por quê>`

## Pendências externas ainda abertas (P-01 a P-10)

| Pendência | Continua bloqueando o quê nesta release |
| --- | --- |
| `<P-xx>` | `<o que fica desligado ou proibido enquanto durar>` |

## Rollback

- Release anterior: `<SHA>`
- Procedimento: `docs/operations/rollback.md`
- Testado nesta release? `<sim / não>`
