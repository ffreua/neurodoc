# SNCR — estado de execução

Registro de continuidade da integração NeuroDoc × SNCR (Anvisa). Leia
antes de retomar o trabalho, **e confira contra o código atual**: este
arquivo resume, não substitui a inspeção.

| Campo | Valor |
| --- | --- |
| Sprint / gate | **Sprint 0 — auditoria e prova de comunicação.** Gate 0 aguardando o proprietário |
| Branch | `sncr/sprint-0` (local; **sem push**) |
| Commit-base | `2af8a17` — `main`, NeuroDoc 1.21 |
| Código funcional alterado | **nenhum** |
| Produção | **não alterada**; nenhuma chamada à API de produção do SNCR |
| Relatório da sprint | [SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md) |

## Decisões aprovadas

Nenhuma ainda. As decisões pendentes estão no relatório, seção 9.

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

Aguardar a decisão do proprietário sobre as **sete perguntas** do
relatório (seção 9). As duas primeiras bloqueiam tudo o mais:

1. o que fazer com a RCE **assinada digitalmente** a partir de
   **31/10/2026**, quando ela passa a exigir numeração SNCR;
2. qual **CNPJ de mantenedora** o NeuroDoc informará ao SNCR.

Depois, com autorização, a prova de comunicação completa (Gov.br de
treinamento do médico + um bloco de RCE em homologação).

## Pendências

- Consulta em produção (só leitura) de quantas RCE foram assinadas
  digitalmente: a VPS não aceitou SSH a partir da rede em uso em
  2026-10-21 (porta 22 bloqueada na saída). Repetir de outra rede.
- Ler o texto vigente da Portaria SVS/MS 344/1998 e da Portaria 6/1999
  sobre o número máximo de medicamentos por receita, por lista.
- Obter a lista oficial de substâncias controladas em formato processável.

## Riscos registrados

Ver relatório, seção 8.
