# Grafo do código (graphify) — o que ler antes de codar

> Escrito em 2026-11-20 a pedido do titular, para que o grafo traga
> contexto **da forma certa** a quem vai mexer no código (pessoa ou IA).
> Vale para o NeuroDoc; o ProntDoc tem o mesmo documento, com os números
> dele. Onde este arquivo divergir do código, **vale o código**.

## 0. Onde o grafo entra

São quatro camadas de contexto, e cada uma responde a uma pergunta. Leia
na ordem e pare na primeira que responder:

| Camada | Responde | Onde |
| --- | --- | --- |
| Regras | o que não se pode fazer, e por quê | `../CLAUDE.md` (pasta raiz) e `CLAUDE.md` |
| Mapa | o que cada módulo faz, os fluxos, "para mexer em X, abra Y" | `docs/CODEBASE_MAP.md` (Cartographer) |
| **Grafo** | **quem chama quem, o raio de impacto de uma mudança, as espinhas** | `graphify-out/` (este documento) |
| Código | o que de fato acontece | os arquivos |

O grafo **não** substitui a leitura do arquivo: ele diz onde olhar. Todo
caminho que ele sugere é conferido no código antes de virar conclusão
(§3, armadilha 4, mostra por quê).

## 1. Reconstruir

O grafo **não é versionado**: `graphify-out/` está no `.git/info/exclude`
(arquivo local), porque é gerado e porque este repositório é público.
Numa máquina nova, ou depois de mudança grande, reconstrua:

```powershell
uv tool install graphifyy                      # uma vez por máquina
& "$(uv tool dir)\graphifyy\Scripts\python.exe" scripts\grafo_codigo.py
```

O script fixa o **recorte** (só o código: `.py`, `.js`, `.css`, ~870
arquivos), lido pela árvore sintática — sem modelo de linguagem, sem
custo de tokens, uns dez minutos. Documentos, templates e imagens ficaram
fora de propósito: passavam de 450 arquivos e custariam dezenas de
subagentes, e o mapa deles já existe no `CODEBASE_MAP.md`.

Saída: `graph.json` (os dados), `GRAPH_REPORT.md` (espinhas, pontes,
perguntas sugeridas) e `graph.html` (uma bolha por comunidade; acima de
5.000 nós o graphify só desenha a visão agregada).

## 2. Consultar

```powershell
graphify explain "tenancy/models.py::Membership"   # nó ambíguo: caminho::símbolo
graphify explain "tenancy_models_membership"       # ou o id
graphify path "Membership" "capabilities_for"
graphify query "como o vínculo vira permissão" --budget 1500
```

`explain --all` lista todas as ligações mas **não** agrupa por arquivo. Para
o raio de impacto (quem depende de um símbolo, por módulo), leia o
`graph.json` direto — é um grafo do NetworkX em JSON:

```python
import collections, json, networkx as nx
g = json.load(open('graphify-out/graph.json', encoding='utf-8'))
nos = {n['id']: n for n in g['nodes']}
G = nx.Graph([(e['source'], e['target']) for e in g['links']])
alvo = 'tenancy_models_membership'
print(collections.Counter((nos[v].get('source_file') or '').split('/')[0] for v in G[alvo]).most_common())
```

## 3. Leitura honesta — as armadilhas

1. **Nem todo nó é nosso.** `design_system/refs/duralux/assets/*.js` é o
   bundle minificado do tema, copiado como referência. Gera dezenas de
   comunidades ("Bundle Duralux (terceiros)") e três das dez espinhas
   (`t()`, `b`, `Ne()`). Ignore-as.
2. **O grafo enxerga só o Python e o JS.** Templates ficaram fora: o
   `ctx.can(...)` de um template e o `{% url %}` não aparecem. Os 32
   `urls.py` não geram símbolo, então **as rotas são invisíveis** — para
   saber que URL chega a uma view, leia o `urls.py`.
3. **Arestas `INFERRED` são palpite.** Importação, herança e "contém" são
   `EXTRACTED` (lidas do código); `uses` é inferido por heurística. Das 305
   ligações do `Membership`, 113 são `uses` inferidas. Trate-as como pista.
4. **Caminho mais curto não é fluxo de execução.** `graphify path
   Membership AccessContext` responde "passando por `seed_demo.py`" —
   verdade no grafo (o comando importa os dois), irrelevante para o
   sistema. O caminho real (§5) passa pelo middleware. O grafo junta
   símbolos por importação, e um arquivo que importa muita coisa vira atalho.
5. **Comunidade não é módulo, e o número dela muda.** O agrupamento
   (Leiden/Louvain) não é determinístico: o mesmo código deu 421 e depois
   391 comunidades. Nunca cite "comunidade 4"; cite o arquivo e o
   símbolo. E um nó com chamadores por todo lado cai numa comunidade
   arbitrária: `record_audit_event()` ficou em "Financeiro" sem ter nada de
   financeiro (§4).
6. **A saúde acusa, e é esperado.** ~3.000 arestas para fora do recorte
   (bibliotecas, templates), ~70 laços, ~2.600 repetidas fundidas. O grafo
   serve para navegar; não é inventário completo.

## 4. As espinhas (nós mais ligados) e o que significam

| Nó | Ligações | O que significa para quem coda |
| --- | --- | --- |
| `record_audit_event()` (`audit/services.py:22`) | 305 | **A porta única da trilha**, importada por ~80 arquivos (atendimento, agenda, documentos, equipe, console, IA, SMS, TISS, contratação…). Ação que muda estado chama ela; nunca com texto clínico, token ou segredo nos metadados (auditoria externa de 2026-11-20 tirou nome de medicamento, de exame e motivo livre). Não há outro caminho de escrita na trilha — e não crie um. |
| `Membership` (`tenancy/models.py:280`) | 305 | O **vínculo** pessoa × clínica, de onde sai toda permissão. §5 inteiro. |
| `Tenant` (`tenancy/models.py:56`) | 236 | A clínica: plano, estado comercial (`ACTIVE`/`SUSPENDED`/`CLOSED`), TISS liberado. |
| `Patient` | 216 | O paciente; sempre filtrado pela clínica. |
| `User` | 184 | A conta (e-mail como login, segundo fator, dispositivo confiável). Quase todo roteiro de `checks/` a usa para montar login — por isso as "conexões surpreendentes" do relatório são só `checks/*` → `User`. |
| `Encounter` | 167 | O atendimento: estruturado ou texto livre, e as estruturas de primeira consulta e seguimento. |

## 5. Do vínculo à permissão — o traçado do `Membership`

Conferido linha a linha no código em 2026-11-20. **Os nove arquivos desta
cadeia são idênticos no NeuroDoc e no ProntDoc** (comparados sem fim de
linha): `tenancy/middleware.py`, `tenancy/context.py`,
`tenancy/permissions.py`, `ai/context.py`, `ai/sse.py`, `teamchat/sse.py`,
`accounts/dispositivo_confiavel.py`, `reporting/painel.py`,
`notifications/services.py`.

### 5.1 O dado

`Membership` (`tenancy/models.py:280`): `roles` é uma lista
(`owner`, `doctor`, `secretary`, `manager` — **acumulam**: quem é `owner` e
`doctor` soma as duas colunas) e `status` é `invited`, `active`,
`suspended` ou `revoked`. **Só `active` autoriza.**
`can_practice_clinically()` (`:320`) é papel `doctor` **e**
`PhysicianProfile` verificado — marcar o papel não basta para assinar.

### 5.2 Na requisição (`/app/`)

`TenantMiddleware.__call__` (`tenancy/middleware.py:30`), só para
`/app/`, nesta ordem:

1. sem login → tela de login;
2. e-mail não verificado → 403 explicando (não 404);
3. sem `tenant_id` na sessão → escolher a clínica;
4. degustação vencida → volta ao Gratuito **antes** de montar o contexto;
5. `build_access_context` → `None` vira **404**;
6. clínica `CLOSED` → 403 com a tela que explica;
7. segundo fator obrigatório pendente → configuração;
8. clínica `SUSPENDED` e método que escreve → 403 (o congelamento mora
   aqui, e não em cada view);
9. a resposta sai sem cache no navegador.

`build_access_context` (`tenancy/context.py`) relê do banco **a cada
requisição** — nunca da sessão —, por isso vínculo revogado para de
autorizar na hora:

- `active_membership_for` (`:55`): `status=ACTIVE`, a pessoa, a clínica da
  sessão;
- o domínio da requisição não pode ser alias de outra clínica;
- `AccessContext` (imutável): `membership_id`, `permissions` (os papéis),
  `tenant_status` e `capabilities`.

`capabilities_for` (`tenancy/permissions.py:189`) é a matriz do PRD §4:
une `_ADMINISTRATIVE` de cada papel (`:130`) e `_TISS` se contratado
(`:161`); `doctor` ganha leitura clínica e IA, e escrita clínica e emissão
**só** com `clinically_enabled`; `CLINICAL_AI` é **vetada** se o plano não
tem IA. Os argumentos são nomeados e obrigatórios de propósito: um padrão
que concedesse por omissão compilaria em todo lugar sem cobrar o plano.

### 5.3 Na view e no template

- `CapabilityRequiredView` (`tenancy/permissions.py:238`): toda tela de
  `/app/` herda dela e declara `required_capability`. Recusa é **404**
  (quem não pode não precisa saber que a tela existe), e o link some junto.
  `None` é decisão explícita ("qualquer vínculo ativo"), não esquecimento.
- A capacidade responde **"o quê"**; o objeto responde **"de quem"**:
  `can_configure_agenda_of` (`:268`) e `can_set_fee_for` (`:284`) — o
  médico mexe só na própria agenda e no próprio honorário; quem administra,
  em qualquer um.
- Pergunte `ctx.can(Capability.X)`, **nunca** `'doctor' in roles`.

### 5.4 Fora da requisição — onde o middleware não passa

Worker, streams e avisos não passam pelo `TenantMiddleware`. Cada um
**relê o vínculo** do banco, e é isso que impede um vínculo revogado entre
"enfileirar" e "executar" de vazar dado:

| Onde | O que reconfere |
| --- | --- |
| `ai/context.py:23` `build_ai_authorization` | vínculo ativo, plano com IA, degustação; na criação do job **e** logo antes do provedor |
| `ai/sse.py:55` `_membership_still_authorized` | o stream da resposta da IA |
| `teamchat/sse.py:63` `_membership_still_active` | vínculo ativo, pessoa ativa, clínica não encerrada; solta a conexão do banco (`sync_to_async`: chamar sem `await` devolve corrotina, que é sempre verdadeira) |
| `tiss/lotes.py:267` `_ainda_autorizado` | o lote TISS no worker |
| `notifications/services.py:45` `_members_with` | quem recebe o aviso, pela capacidade |
| `accounts/dispositivo_confiavel.py:138` `politica_permite` / `:296` `revogar_da_clinica` | dispositivo confiável só se **todas** as clínicas ativas da pessoa permitem |
| `reporting/painel.py:160` `resolver_escopo` | Dashboard: o médico preso à própria carteira; quem administra escolhe |
| `accounts/services.py:118` `revoke_membership` / `:97` `switch_tenant` | revogar encerra também as sessões de assinatura; trocar de clínica reescreve a sessão |

### 5.5 Decisões do titular que o código não mostra

- **O médico vê o financeiro e a lista de pacientes dos colegas da mesma
  clínica** (2026-11-20). A auditoria externa chamou isso de BOLA; é
  decisão, não defeito. Não restrinja por médico sem nova decisão.
- Recusa por capacidade é 404, não 403 — deliberado.

### 5.6 Lista de conferência ao codar

- Tela nova em `/app/` → herda `CapabilityRequiredView` com
  `required_capability` explícita; recusa por objeto → um helper como
  `can_configure_agenda_of`.
- Trabalho em segundo plano que toca dado da clínica → relê `Membership`
  ativo, o estado da clínica e o plano, no molde de `build_ai_authorization`.
- Template → `ctx.can(...)`, e esconde o link junto com a recusa.
- Ação que muda estado → `record_audit_event`, sem texto clínico.
- Rode `check_matrix`, `check_roles`, `check_isolation` e o roteiro do
  módulo; tela nova pede roteiro novo que tente furá-la.
- Mudou aqui → confira o mesmo arquivo no ProntDoc (são iguais hoje).

## 6. NeuroDoc × ProntDoc no grafo

| | NeuroDoc | ProntDoc |
| --- | --- | --- |
| Arquivos de código | 870 | 869 |
| Nós / arestas | ~12.570 / ~34.240 | ~12.520 / ~34.080 |
| Ligações de `record_audit_event()` | 305 | 303 |
| Ligações de `Membership` | 305 | 309 |
| Chamadas da trilha em `clinical/views.py` | 15 | 12 |

A espinha é a mesma — a origem comum aparece inteira no grafo. As
diferenças são as particularidades: as três chamadas a mais no
`clinical/views.py` do NeuroDoc são o exame estruturado e as escalas, que
o ProntDoc não tem.

## 7. Como este documento foi feito

graphify (`graphifyy`, instalado por `uv tool`), recorte só do código,
sem tokens; o traçado do `Membership` saiu do `graph.json` com NetworkX e
foi conferido em cada arquivo citado. Ao reconstruir o grafo depois de
mudança grande, revise as linhas citadas na §5 — elas são o que envelhece.
