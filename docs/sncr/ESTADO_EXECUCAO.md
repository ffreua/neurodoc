# SNCR — estado de execução

Registro de continuidade da integração NeuroDoc × SNCR (Anvisa). Leia
antes de retomar o trabalho, **e confira contra o código atual**: este
arquivo resume, não substitui a inspeção.

| Campo | Valor |
| --- | --- |
| Sprint / gate | **Sprint 0 concluída; decisões D1–D7 tomadas em 2026-10-21.** Sprint 1 liberada, com a numeração real **bloqueada pelo CNPJ** ([PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md)) |
| Commit-base | `2af8a17` (1.21); a Sprint 0 e a 1.21.1 entraram em `main` |
| Código funcional alterado | **1.21.1** — só a transição da D1 (`documents/sncr_transicao.py`); a integração em si ainda não tem código |
| Produção | 1.21.1 publicada com a transição; **nenhuma chamada à API de produção do SNCR** |
| Relatório da Sprint 0 | [SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md) |
| Decisões | [DECISOES.md](DECISOES.md) |

## Decisões aprovadas

Todas em [DECISOES.md](DECISOES.md), em 2026-10-21: D1 (RCE só em papel
a partir de 31/10, com aviso e e-mail às clínicas — **feito, 1.21.1**),
D2 (CNPJ **pendente**, seguir sem ele), D3 (login Gov.br de treinamento e
um bloco em homologação; cada médico com o próprio bloco), D4 (o
servidor chama a API), D5 (escopo RCE + RET), D6 (impressa no leiaute da
clínica, eletrônica no modelo da Anvisa), D7 (importar a lista oficial
da Portaria 344).

## O que a Sprint 0 fez

- Mapa do código: `docs/CODEBASE_MAP.md` (Cartographer, 2026-10-18), mais a
  leitura dirigida do fluxo de receita (`documents/models.py`,
  `documents/issuance.py`, `documents/pdf/prescription.py`,
  `documents/pdf/common.py`, `documents/signing*.py`, `catalogs/`).
- Leitura integral: Manual da API SNCR v5 (16 p., set/2026), Instruções de
  Integração v1.0 (11 p., jul/2026), Perguntas e Respostas — Integração
  (15 p.), Perguntas e Respostas RDC 1.000/2025 — 2ª ed. (30 p., trechos
  pertinentes), aplicação de exemplo oficial (código lido, **não**
  executado), OpenAPI de homologação (`sncr-api` 1.2.1), modelos oficiais
  de RCE eletrônica e física (rev. 2026-03-13).
- Sondagens **sem efeito persistente** no ambiente de homologação (DNS,
  TLS, início do login, recusa sem token).
- Bateria local de referência — resultado no relatório, seção 7.

## Próxima ação exata

1. **Sprint 1**, em branch própria (`sncr/sprint-1`, a partir de `main`):
   catálogo da lista oficial da Portaria 344 (D7, vigente: RDC nº 1.036,
   de 09/07/2026, "Atualização n. 101"), cliente da API, login Gov.br pelo
   servidor (D4), modelo de blocos e números por médico, estado incerto,
   trilha, chave desligada.
2. **Prova de comunicação (D3):** o proprietário faz o login Gov.br de
   treinamento numa página local; o bloco em homologação espera o CNPJ.
3. Quando o CNPJ chegar: seguir a lista de
   [PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md).

## Pendências

- ~~Consulta em produção de quantas RCE foram assinadas digitalmente~~ —
  feita em 2026-10-21: **5**, todas da clínica do proprietário; as outras
  clínicas emitiram RCE só em papel (1).
- **CNPJ da mantenedora** — [PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md).
- Ler o texto vigente da Portaria SVS/MS 344/1998 e da Portaria 6/1999
  sobre o número máximo de medicamentos por receita, por lista.
- Obter a lista oficial de substâncias controladas em formato processável.

## Riscos registrados

Ver relatório, seção 8.
