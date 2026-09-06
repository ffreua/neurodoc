# Homologação — Chat persistente e streaming (S12)

Evidência coletada via scripts de verificação (`python manage.py shell`), via
`django.test.AsyncClient` contra a view SSE real, e via `curl` **através do
Traefik real** já em execução na pilha local (`http://127.0.0.1:8080`, o
mesmo proxy que roteia `traefik_public` em produção). Modelo de linguagem
substituído por `FakeListChatModel` do `langchain_core` apenas no limite da
chamada de rede (mesmo padrão de S11); todo o resto — sessão, persistência,
Redis Streams, SSE, sanitização, cancelamento — rodou de verdade.

## H-18 — Chat e SSE

- [x] **Sessões separadas por usuário/tenant/paciente, sem herança de
  contexto**: criar uma sessão sem paciente explícito não reaproveita o
  paciente de nenhuma sessão anterior (`patient_id=None` mesmo com uma
  sessão prévia contextualizada); trocar de paciente
  (`switch_patient_creates_new_session`) sempre cria uma sessão **nova**,
  nunca muta a existente — confirmado lendo a sessão original depois da
  troca. Sessões são filtradas por `tenant_id` **e** `owner_user_id` em
  toda view (`ai/chat_views.py`), nunca só por tenant.
- [x] **Tokens chegam incrementalmente pelo Traefik**: publicados dois
  eventos Redis Streams (`delta` e `complete`) e lidos de volta com um
  `curl -N` de verdade **através do Traefik real** rodando na pilha
  (`127.0.0.1:8080`, o mesmo roteador usado em produção) — os dois eventos
  chegaram na ordem certa, com `Content-Type: text/event-stream`,
  `Cache-Control: no-cache` e `X-Accel-Buffering: no` (evita buffering
  intermediário). Não é um teste in-process: passou pelo proxy real.
- [x] **Chave do stream inclui tenant/user/session/job e TTL de 1h**:
  `ai.streaming.stream_key` monta a chave com os quatro componentes;
  `TTL` confirmado entre 3000–3600s logo após publicar.
- [x] **Reconexão por Last-Event-ID sem duplicar nem vazar stream alheia**:
  `ai.streaming.read_after` usa o range exclusivo do Redis Streams
  (prefixo `(`) — ler novamente a partir do último id recebido devolve
  apenas os eventos posteriores, nunca repete o mesmo; a chave em si já
  impede ler o stream de outro tenant/usuário/sessão (não há como montar a
  chave de outra combinação sem saber tenant/user/session/job reais, que
  vêm sempre do `AccessContext` autenticado, nunca de parâmetro do
  cliente). No navegador, a reconexão em si é responsabilidade nativa do
  `EventSource` (`static/ai/chat.js`), que reenvia `Last-Event-ID`
  automaticamente — não foi reimplementada à mão.
- [x] **Cancelamento persistido, sem prometer estorno de custo**:
  `ai.cancellation.cancel_message` marca `ChatMessageState.CANCELLED` no
  banco e publica um evento terminal `cancelled` no stream (para que
  qualquer SSE aberta encerre); o docstring e o comportamento deixam
  explícito que nenhuma reversão de custo do provedor é assumida.
  Limite de concorrência (`MAX_CONCURRENT_STREAMS_PER_USER=3`) testado no
  limiar exato: a terceira mensagem em streaming simultânea é aceita, a
  quarta é recusada.
- [x] **Markdown malicioso não executa script durante nem depois do
  stream**: `ai.rendering.render_markdown` escapa o texto bruto **antes**
  de rodar o Markdown (então `<script>alert(1)</script>` vira entidades
  inertes) e neutraliza qualquer `href`/`src` com esquema
  `javascript:`/`data:`/`vbscript:` que a sintaxe `[texto](url)` do
  Markdown produza — testado com os dois vetores simultaneamente, mais um
  link real (`https://...`) e um **negrito** de controle para confirmar
  que a sanitização não quebra o conteúdo legítimo. No cliente
  (`static/ai/chat.js`), os deltas incrementais são inseridos via
  `textContent` (nunca `innerHTML`) enquanto a resposta ainda está sendo
  gerada; só o HTML final, já sanitizado no servidor, é inserido via
  `innerHTML` no evento `complete` — script nenhum roda em nenhuma das
  duas fases.
- [x] **Revogação interrompe uma leitura já aberta**: distinto de apenas
  bloquear uma nova requisição (que o `TenantMiddleware` já faz desde S02),
  este teste abriu a conexão SSE com a membership ainda ativa, consumiu o
  primeiro chunk, **então** revogou a membership, e confirmou que a
  chamada seguinte ao gerador assíncrono (sem nova requisição HTTP) já
  retorna o evento terminal `revoked` — a checagem roda a cada iteração do
  próprio gerador (`ai/sse.py`), não apenas uma vez no início da conexão.
- [x] **Resultado final sobrevive à perda do Redis**: a chave do stream foi
  apagada manualmente do Redis logo após a conclusão; o conteúdo final da
  mensagem, lido de volta do Postgres, permaneceu intacto — a persistência
  do texto nunca dependeu da sobrevivência do stream.
- [x] **Sem conexão ORM pendurada**: o gerador assíncrono só toca o banco
  através de `sync_to_async` em chamadas pontuais (revalidar a membership,
  buscar a sessão uma vez no início) — nenhuma consulta fica aberta durante
  a espera entre eventos (`asyncio.sleep`), consistente com o padrão já
  usado em toda a base para não segurar conexões de banco além do
  necessário.

## Decisões de escopo

- O grafo de streaming desta sprint não reaproveita o grafo estruturado de
  S11 (`ai/graphs.py`, que valida contra `ClinicalSummaryArtifact`) — uma
  conversa de chat é texto livre, não um artefato clínico estruturado; a
  tarefa (`ai.tasks.run_chat_turn`) transmite o texto incrementalmente via
  `chat_model.stream(...)` e só sanitiza/persiste ao final. Uma extensão
  futura poderia rotear certas perguntas de chat para o grafo estruturado
  quando fizer sentido (ex.: "resuma este atendimento"), sem migração
  incompatível.
- "Rollout comunica reconexão quando necessária" (parte de H-18) depende
  de duas réplicas de `app` coexistindo durante um rollout real — mesmo
  bloqueio de P-02 já registrado em S10; o mecanismo do lado do cliente
  (`EventSource` reconecta sozinho com `Last-Event-ID`) já está pronto para
  esse cenário, mas o *drill* de rollout com streaming ativo não foi
  executado contra uma VPS real.
- `ai/chat_views.py` não distingue papel médico/secretaria nas ferramentas
  disponíveis ao chat ainda — isso é responsabilidade das *tools*
  administrativas/clínicas já isoladas desde S11 (`ai/tools/`), que o chat
  reaproveita; nenhuma tool nova foi criada nesta sprint.
