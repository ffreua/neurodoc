# SNCR — Sprint 0: auditoria e prova de comunicação

**Data:** 2026-10-21 · **Base:** `2af8a17` (NeuroDoc 1.21) · **Branch:**
`sncr/sprint-0`, local, sem push · **Produção:** não alterada.

**Status: PARCIAL. Gate 0: BLOQUEADO** por duas decisões do proprietário
(seção 9) e pela parte da prova de comunicação que depende de o médico
entrar no Gov.br.

---

## 1. Resumo

1. **Prazo regulatório em 10 dias.** A partir de **31/10/2026**, toda
   Receita de Controle Especial (RCE) **emitida eletronicamente** precisa
   da numeração do SNCR (FAQ RDC 1.000, perguntas 30 e 50). O NeuroDoc hoje
   **assina digitalmente** a RCE (PAdES/ICP-Brasil), sem numeração SNCR e
   no layout da clínica. Esse caminho deixa de ser válido em 31/10. A RCE
   **impressa e assinada à mão** continua válida no layout da clínica
   (pergunta 7). Isso independe da integração e pede decisão já.
2. **O NeuroDoc não tem CNPJ de mantenedora.** O pedido de numeração de
   RCE/RET exige o CNPJ da empresa responsável pela plataforma, e não o da
   clínica (Manual v5 §2.3.2.3; FAQ Integração, pergunta 34). O contrato de
   adesão qualifica o responsável pela plataforma como **pessoa física**
   (`tenancy/contract.py::CONTRATADO`). Sem um CNPJ de mantenedora, a
   numeração de RCE não pode ser pedida.
3. **A API é viável, e pequena.** São dois serviços de numeração (RCE/RET
   em blocos de 1.000; Notificações de 10 a 50) atrás de login Gov.br. Não
   gera PDF, não assina, não consulta, não cancela. O resto é do NeuroDoc.
4. **A comunicação foi demonstrada até o ponto em que dá sem o médico:**
   DNS, TLS, OpenAPI, o início do login (domínios `.br` e `localhost`
   aceitos, demais recusados) e a recusa sem token. A autenticação real e
   uma numeração em homologação dependem de você (seção 6).

## 2. O NeuroDoc hoje — o fluxo da receita

| Etapa | Onde | Como é |
| --- | --- | --- |
| Formato | `documents/pdf/prescription.py` | O médico escolhe `simple` ou `special_control`. **Nada classifica o medicamento**: a tarja da CMED só avisa ("costumam") na busca (`catalogs/models.py`) |
| Conteúdo | `MedicalDocument.content_snapshot` | `prescription_text` livre; **sem** lista estruturada de medicamentos, concentração, forma, quantidade |
| PDF | `documents/pdf/common.py::build_pdf` | ReportLab. Timbre e rodapé da clínica em toda folha (1.21). Controle especial: 2 vias, quadro de comprador **e fornecedor** |
| Número | `issuance._next_document_number` | Interno, por clínica |
| Emissão digital | `issuance.sign_and_issue` | PAdES com o A1 do médico (`signing.py`, pyHanko), QR para `/verificar/` do NeuroDoc |
| Emissão em papel | `issuance.issue_on_paper` | Sem QR, assinatura à mão |
| Limite de medicamentos | — | **Não existe** |

## 3. O que a API SNCR é, e o que não é

**É** (Manual v5, OpenAPI 1.2.1):

- `GET auth/login?client_url=` → Gov.br (Keycloak) → volta a
  `client_url?session_id=` (uso único, **30 s**);
- `GET auth/token?session_id=` → `access_token` (Bearer, **validade de
  30 s, sem refresh**). O `session_id` fica preso ao `Origin` que iniciou;
- `POST numeracoes/receita-especial-retencao` — RCE ou RET, **1.000
  números por chamada, até 3 chamadas/mês por tipo e inscrição**, exige
  `cnpj` da plataforma; responde `inicio`/`fim`;
- `POST numeracoes/notificacao-receita` — NRA/NRB/NRB2/NRR/NRT, **10 a 50
  por chamada, 50/dia por tipo**, só do saldo **autorizado antes pela
  VISA**.

**Não é:** não gera PDF, não assina, não guarda a receita, **não tem
consulta de bloco nem de saldo** (só o saldo na resposta), **não cancela
nem devolve número** (FAQ 35–36), e **não diz quais números do bloco já
foram usados** — isso é do sistema prescritor (FAQ 38). Número não usado
se perde; a cota conta na entrega do bloco.

## 4. Matriz de rastreabilidade regulatória

| # | Exigência | Fonte (versão, data) | Componente | Implementação proposta | Teste comprobatório |
| --- | --- | --- | --- | --- | --- |
| R1 | RCE/RET eletrônica com numeração SNCR a partir de 31/10/2026 | FAQ RDC 1.000, 2ª ed., P30/P50 | `issuance`, `prescription` | Bloquear assinatura digital de `special_control` sem número SNCR (decisão D1) | roteiro: RCE digital sem número recusada após a data |
| R2 | Modelo eletrônico sem customização, sem logo, cabeçalho ou rodapé comercial | FAQ Integração P40–41; página Receituário Eletrônico (30/06/2026) | novo gerador | PDF próprio fiel ao modelo oficial, separado de `build_pdf` | comparação visual e de campos com o modelo oficial |
| R3 | RCE física: layout distinto permitido com "Receita de Controle Especial" e campos obrigatórios | FAQ RDC 1.000 P7 | `build_pdf` (atual) | Manter a modalidade impressa | roteiro de campos obrigatórios |
| R4 | Novas impressões físicas no modelo versão 2 desde 18/05/2026 | FAQ RDC 1.000 P50 | `build_pdf` | Avaliar ajuste mínimo (quadro de fornecedor → carimbo) — **decisão D6** | comparação com o modelo físico rev. 2026-03-13 |
| R5 | Assinatura qualificada ICP-Brasil para controlados (Lei 14.063/2020, art. 13) | FAQ RDC 1.000 P40–41; FAQ Integração P43 | `signing.py` | Reusar PAdES/A1; recusar avançada (Gov.br) para controlados | validação da cadeia ICP-Brasil |
| R6 | Prescritor autenticado = prescritor da requisição (conselho, UF, número) | Manual v5 §2.3.1.5, §2.3.2.5 | novo `sncr/` | Conferir CRM/UF do `PhysicianProfile` antes; tratar 404 "inscrição diferente" | roteiro: CRM divergente não chama a API |
| R7 | CNPJ da mantenedora, não da clínica | Manual v5 §2.3.2.3; FAQ Integração P34 | configuração da instalação | `InstallationSettings`, nunca em código; recusa sem CNPJ válido | roteiro: sem CNPJ, nada é pedido |
| R8 | Blocos de 1.000, 3/mês; pedir só o necessário | Manual v5 §2.3.2.5; FAQ P33 | numeração | Pedir bloco só com o anterior esgotado, com confirmação do médico | roteiro de concorrência e esgotamento |
| R9 | Sem cancelamento; número não usado se perde | FAQ Integração P35–36 | numeração | Nunca reemitir número; perda registrada na trilha | roteiro: número consumido nunca volta |
| R10 | Controle do uso do bloco é da plataforma | FAQ Integração P38 | numeração | Tabela de números com unicidade e consumo transacional | roteiro: nenhum número em duas receitas |
| R11 | Notificação só com cota da VISA | Manual v5 aviso p. 5; FAQ P29 | — | **Fora do escopo inicial** (D5) | — |
| R12 | Notificação emitida fora de serviço integrado não vale | FAQ RDC 1.000 P49 | — | Nunca permitir NR "à mão" | — |
| R13 | Contingência: indisponível o SNCR, emite-se em papel | FAQ Integração P53 | fluxo | Oferecer a modalidade impressa com confirmação | roteiro de API indisponível |
| R14 | Controlado nunca em receita simples | FAQ Integração P48; FAQ RDC 1.000 P68 | classificação | Lista oficial de substâncias versionada (não a tarja CMED) | roteiro: controlado em receita simples recusado |
| R15 | Endereço completo do paciente | FAQ Integração P45 | já existe | `issuance` já exige na RCE | roteiro existente |
| R16 | Limite de medicamentos por receita | Política do proprietário (3) + Portaria 344 (a confirmar) | validação | `min(3, limite_do_tipo)` no backend | roteiros 1–4 medicamentos |
| R17 | QR da Notificação → `sncr.anvisa.gov.br/receita/consultar?numero=` | página Receituário Eletrônico | PDF | Para NR; **para RCE o destino do QR não está especificado** (lacuna L3) | — |

## 5. Divergências entre fontes e lacunas

| # | Divergência / lacuna | Efeito | Tratamento |
| --- | --- | --- | --- |
| L1 | OpenAPI tem o cabeçalho opcional `X-Jws-Integradora`, ausente do manual | Provável identificação assinada da plataforma ("em breve", Instruções §3) | Não usar até documentado; perguntar a `sncr.integracao@anvisa.gov.br` |
| L2 | `numeracoesReceita`: manual mostra string, OpenAPI mostra lista | Parser | Aceitar os dois, guardar o número como texto íntegro |
| L3 | Destino do QR da **RCE** eletrônica não especificado | Modelo | Perguntar à Anvisa antes de gerar o PDF oficial |
| L4 | Keycloak: manual cita `acesso.apps…/realm anvisa`; homologação usa `acesso.dev…/realm externo` | Só informativo (quem fala com o Keycloak é o SNCR) | Nenhum |
| L5 | Dois hosts de homologação (`api-gateway.hmg…/api-sncr` e `sncr-api.hmg…`) respondem igual | Configuração | Usar o do manual |
| L6 | Timeout depois do POST: sem consulta, um bloco pode ser entregue e perdido (conta 1 das 3 chamadas) | Numeração | Estado "incerto", **sem repetição automática**; procedimento manual (seção 10) |
| L7 | `Origin` exigido no `auth/token` vindo do servidor | Arquitetura | A aplicação de exemplo chama por proxy de servidor (`changeOrigin`) — provar na PoC |
| L8 | Limite de medicamentos por receita na Portaria 344 | R16 | Ler o texto vigente antes da Sprint 2 |

## 6. Prova de comunicação

**Classificação: PARCIAL.**

| Passo | Resultado | Evidência |
| --- | --- | --- |
| Documentação e OpenAPI | acessíveis | `GET /api-sncr/v3/api-docs` 200, `sncr-api` 1.2.1 |
| DNS e TLS (homologação) | ok | `*.hmg.apps.anvisa.gov.br`, Google Trust Services, válido até 07/01/2027 |
| `auth/login`, `client_url=http://localhost:8000/…` | 302 para o Gov.br (Keycloak) | |
| `auth/login`, `client_url=https://neurodoc.app.br/…` | 302 para o Gov.br | o domínio da produção é aceito |
| `auth/login`, `client_url=https://exemplo.com/…` | **403** | a regra `.br` está ativa |
| `auth/token` com sessão inexistente | 401 "Sessão inválida ou expirada" | igual ao manual |
| `POST numeracoes/receita-especial-retencao` sem token | 401 "Token ausente ou expirado" | igual ao manual |
| Login Gov.br do médico (treinamento) | **não feito** | exige você, com uma conta Gov.br de **treinamento** |
| Troca `session_id` → token pelo servidor | **não feito** | depende do login |
| Um bloco de RCE em homologação | **não feito** | **efeito persistente**: consome 1 das 3 chamadas do mês **no treinamento** (sem impacto regulatório, FAQ P10); pede autorização e CNPJ |

Nenhuma chamada à **produção**. Nenhum dado de paciente.

## 7. Linha de base

| Comando | Ambiente | Commit | Resultado |
| --- | --- | --- | --- |
| `docker compose exec app python manage.py rodar_roteiros` | pilha local completa (Postgres, Redis, RabbitMQ reais), banco de demonstração | `2af8a17` | **116 roteiros, nenhuma falha, 426 s** (2026-10-21) |

É a referência contra a qual as próximas sprints medem regressão.

## 8. Riscos

| Risco | Prob. | Impacto | Mitigação |
| --- | --- | --- | --- |
| RCE digital emitida após 31/10 sem número SNCR é recusada na farmácia | **alta** | paciente sem medicamento | D1 — bloquear o caminho digital da RCE até a integração |
| Sem CNPJ de mantenedora, a integração não sai | certa | bloqueio | D2 |
| Timeout depois do POST perde um bloco | baixa | 1 de 3 pedidos do mês | estado incerto, sem retry, procedimento manual |
| Número usado em duas receitas | baixa com controle | grave | unicidade no banco + consumo transacional |
| Médico em várias plataformas | média | blocos usados em paralelo | blocos são por pedido; o NeuroDoc só usa os que ele mesmo recebeu |
| Token de 30 s expira na fila | média | pedido falha | chamada imediata, síncrona curta, sem fila longa |
| Mudança da API (X-Jws, validação da mantenedora) | média | quebra | cliente isolado, parser tolerante, feature flag |
| Regressão no PDF atual | baixa | documentos | gerador oficial **separado**; `build_pdf` intocado |

## 9. Decisões necessárias

**D1 — RCE assinada digitalmente a partir de 31/10/2026.** *(urgente)*
Contexto: R1. Alternativas: (a) a partir de 31/10, a RCE só sai **em
papel** (o botão de assinar some para `special_control`, com mensagem);
(b) manter e avisar; (c) nada. Risco de (b)/(c): receita recusada na
farmácia. **Recomendo (a)**, como correção pequena e separada desta
integração, publicada antes de 31/10. Decisão: autoriza (a)?

**D2 — CNPJ da mantenedora.** Contexto: R7; o NeuroDoc é contratado por
pessoa física. Alternativas: (a) constituir/indicar uma empresa
mantenedora e ajustar o contrato (Dra. Karina); (b) usar o CNPJ de uma
empresa sua já existente **se** ela passar a ser, de fato e no contrato, a
mantenedora; (c) consultar a Anvisa. **Não** usar o CNPJ de clínica
cliente. Para instalações autohospedadas, cada uma informa o próprio CNPJ
na configuração. Decisão: qual CNPJ?

**D3 — Prova de comunicação completa.** Precisa de você: criar uma conta
Gov.br **de treinamento** com o seu CPF (Instruções §2.1) e fazer o login
uma vez numa página local que eu preparo. Autoriza também pedir **um**
bloco de RCE **em homologação** (consome 1 das 3 do mês no treinamento)?

**D4 — Quem chama a API.** (a) o servidor, logo após o retorno do Gov.br
(recomendo: token nunca vai ao navegador, CSP intacta); (b) o navegador
(exige abrir `connect-src` da CSP para a Anvisa). Depende da PoC (L7).

**D5 — Escopo inicial.** Recomendo **RCE (listas C1/C5)** primeiro.
Notificações dependem de cota da VISA; RET (antimicrobianos/GLP-1) não
tem modelo eletrônico definido. Concorda?

**D6 — RCE em papel.** O modelo físico versão 2 tirou o quadro do
fornecedor (agora carimbo no verso). O layout distinto é permitido (P7).
Ajustar o quadro agora, ou manter?

**D7 — Lista de substâncias.** A classificação precisa da lista oficial,
versionada. Autoriza buscar e versionar a lista publicada pela Anvisa
como novo catálogo (como a CMED)?

## 10. Arquitetura proposta (resumo)

- **App novo `sncr/`**, isolado, ligado só por feature flag
  (`InstallationSettings.sncr_ativo = False` por padrão) e por clínica.
- **Cliente** (`sncr/cliente.py`): `httpx`, timeouts curtos, base URL por
  ambiente na configuração, parser tolerante (L2), erros mapeados em
  português.
- **Autenticação**: o médico clica "Obter numeração SNCR" → Gov.br →
  volta a `/app/sncr/retorno/?session_id=` → o servidor troca e usa o
  token **na mesma requisição** (30 s), sem guardar o token.
- **Numeração** (`sncr/models.py`): `BlocoNumeracao` (médico, CRM/UF,
  tipo, início, fim, CNPJ, estado `ok|incerto`, quando) e `NumeroSncr`
  (texto íntegro, bloco, estado `livre|reservado|consumido|perdido`,
  documento). `UNIQUE(numero)`. Reserva com `select_for_update(skip_locked)`
  **fora** de chamada HTTP.
- **Estado incerto**: timeout/erro de rede depois do POST grava o pedido
  como `incerto`; **nada repete sozinho**; o médico vê "verifique no
  portal do SNCR"; um operador concilia à mão.
- **PDF oficial**: gerador separado, fiel ao modelo; `build_pdf` intocado.
- **Assinatura**: o PAdES atual, sem mudança.
- **Contingência**: falha antes do número → oferecer papel, com
  confirmação; número reservado e PDF não assinado → rascunho sem
  validade, número continua reservado.

**Rollback:** desligar a flag. Migrações só de expansão; números e
blocos recebidos **nunca** são apagados.

## 11. Plano das próximas sprints

- **Sprint 1** — núcleo: cliente, autenticação, CNPJ, blocos e números,
  idempotência, estado incerto, trilha, flag desligada; roteiros.
- **Sprint 2** — receita eletrônica: lista estruturada de medicamentos,
  classificação pela lista oficial, limite `min(3, regra)`, PDF oficial,
  assinatura, histórico; papel preservado.
- **Sprint 3** — contingência, homologação real no treinamento,
  documentação operacional, plano de ativação gradual.
