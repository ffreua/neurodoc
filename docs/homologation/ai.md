# Homologação — IA com autorização e revisão médica (S11)

Evidência coletada via scripts de verificação (`python manage.py shell`) e via
`django.test.Client`. Nenhuma chamada real a OpenRouter/OpenAI/Anthropic foi
feita (`AI_ENABLED=False` neste ambiente, sem chaves reais — P-09 e o
provedor final aprovado permanecem pendentes). O adaptador do modelo de
linguagem foi substituído, apenas nos testes, por `FakeListChatModel` do
próprio `langchain_core` — o **grafo, o schema Pydantic, as tools, a
autorização, a desidentificação e a política de privacidade rodaram de
verdade**; só a chamada de rede final foi substituída.

## H-17 — IA

- [x] **Job reautoriza usuário/tenant/paciente**: `build_ai_authorization`
  roda tanto na criação do job quanto de novo dentro de `run_job` (chamado
  pelo worker Celery, nunca inline no request) — testado revogando a
  membership do médico entre a criação e a execução; a segunda chamada
  recusa. `patient_id` de outro tenant é recusado (`AIAuthorizationDenied`),
  mesmo vindo de um `AccessContext` autenticado e válido para o tenant
  correto.
- [x] **Tools não aceitam tenant controlado pelo modelo**: cada tool em
  `ai/tools/clinical.py`/`administrative.py` recebe a `AIAuthorization`
  (nunca um `patient_id`/`tenant_id` cru vindo do texto do modelo) e
  filtra sempre por `tenant_id=authorization.tenant_id`; sem paciente no
  escopo da autorização, a tool recusa (`ToolScopeError`) — testado.
  Paginação limitada (`MAX_ENCOUNTERS=20`, `MAX_FINDINGS=100`,
  `MAX_DIAGNOSES=50`, `MAX_ROWS=20` no administrativo).
- [x] **Chat administrativo não obtém nota clínica**: `ai/tools/
  administrative.py` só expõe etapa de CRM, compromissos e status
  financeiro (valores/datas/status) — nenhuma função ali toca
  `Encounter.chief_complaint`/`hpi`/diagnóstico ou `MedicalDocument`;
  verificado programaticamente (nenhuma chave `chief_complaint`/`hpi` em
  nenhuma linha retornada).
- [x] **Desidentificação local, nunca externa**: `ai.deidentification.
  deidentify_text` substitui nome do paciente, nome da mãe, CPF, telefone
  e e-mail por marcadores — tudo em processo local (regex), sem chamar
  serviço externo algum. Testado com um texto contendo todos esses dados
  reais de um paciente sintético: nenhum sobreviveu à desidentificação.
- [x] **Fail-closed por risco residual**: consanguinidade **confirmada** e
  documentada bloqueia o job (`blocked_privacy`) **antes** de qualquer
  tentativa de requisição externa — nenhuma chamada ao provedor chega a
  ocorrer (o teste verifica a decisão da política isoladamente, sem sequer
  instanciar um cliente de IA).
- [x] **Saída inválida/referência inventada não é apresentada como válida**:
  o grafo (`ai/graphs.py`, 2 nós: chamar modelo → validar contra
  `ClinicalSummaryArtifact`) foi testado com três respostas de modelo
  diferentes — JSON válido (artefato criado), texto que não é JSON (erro,
  nenhum artefato), e um output que passaria por JSON mas contém
  `qualitative_hypotheses` com percentual numérico (`"80% de probabilidade"`)
  — rejeitado pelo próprio schema Pydantic (RF-11.05: nunca probabilidade
  diagnóstica numérica não calibrada).
- [x] **Limite de tempo**: uma chamada de modelo deliberadamente lenta
  (3s) contra um `timeout_seconds=1` é interrompida
  (`ThreadPoolExecutor` + `TimeoutError`) e o job registra erro, nunca fica
  pendurado nem apresenta uma resposta parcial como válida.
- [x] **Rascunho separado do registro clínico e fonte com proveniência**:
  `AIArtifact.result` inclui `source_refs` (tipo/id/versão do encontro de
  origem) e nunca é escrito em `Encounter`; `medical_review_notice` é fixo
  em todo artefato.
- [x] **Aceitar/editar/rejeitar é auditável, e aceitar não assina/prescreve**:
  `ai.review.accept_artifact` grava `AuditEvent` e nunca toca
  `Encounter`/`MedicalDocument` — testado comparando `plan_text`/`status`
  do atendimento antes e depois de aceitar um artefato.
- [x] **Fonte alterada torna o rascunho stale**: alterar o atendimento
  (`row_version` avança, como um autosave faria) depois de gerar o artefato
  e antes da revisão faz `is_stale()` retornar `True` e bloqueia
  aceitar/rejeitar (`ArtifactStale`) até uma nova geração.
- [x] **Nova geração não sobrescreve artefato revisado anterior**: uma
  segunda geração para uma versão nova do mesmo atendimento cria um
  `AIArtifact` **novo**, com `supersedes` apontando para o anterior — o
  artefato antigo continua existindo, com seu `review_state` e conteúdo
  intactos (verificado lendo o registro antigo depois de gerar o novo).
- [x] **Troca de provedor é explícita**: `ai.providers.get_chat_model(provider=None)`
  só resolve por `settings.AI_PROVIDER` (ou um argumento explícito) — nunca
  cai silenciosamente para outro provedor; cada adaptador
  (`openrouter.py`/`openai_provider.py`/`anthropic_provider.py`) usa o
  mesmo `settings.AI_MODEL` como identificador único, evitando ampliar a
  política de dados por engano ao trocar de provedor.
- [x] **IA indisponível não bloqueia o prontuário**: `AIJobStatus.DISABLED`
  é um estado de primeira classe — quando `AI_ENABLED=False` (como neste
  ambiente), o job é criado normalmente para registro, mas nunca chega a
  `run_job`; a finalização do atendimento em si (S05) é totalmente
  independente e nunca aguarda ou depende do resultado da IA.

## Achado real corrigido nesta sprint: dispatcher de outbox só suportava um consumidor por tópico

`events.dispatcher` (S08) foi desenhado assumindo um único handler por
prefixo de tópico. Ao registrar um segundo consumidor independente para
`clinical.encounter_finalized` (o financeiro, de S09, e agora a IA), o
segundo registro **sobrescrevia silenciosamente** o primeiro no dicionário
`_HANDLERS` — o financeiro teria parado de criar recebíveis assim que o
app de IA carregasse. Corrigido generalizando `_HANDLERS` para uma lista de
consumidores por prefixo; cada consumidor tem seu próprio `ProcessedEvent`
e sua própria semântica de entrega/retentativa — a falha de um nunca
impede nem duplica o efeito do outro. **Testado de ponta a ponta**:
finalizar um atendimento com IA e financeiro ambos habilitados faz os dois
`ProcessedEvent` (`finance.encounter_finalized` e `ai.encounter_finalized`)
existirem após um único `run_once()`, e ambos os efeitos (recebível +
`AIJob`) aparecem no banco.

## Decisões de escopo

- **P-06/P-09 permanecem pendentes.** Nenhum dado real foi processado por
  um provedor de IA externo; a substituição do modelo de linguagem por
  `FakeListChatModel` nos testes é explícita e documentada — o código de
  produção (`ai/providers/*.py`) usa os clientes reais de
  `langchain-openai`/`langchain-anthropic`, nunca um substituto, e
  `ProviderUnavailable` é levantado sempre que `AI_ENABLED=False` ou a
  chave não está configurada.
- A política de privacidade (`ai/privacy_policy.py`) usa uma lista
  ilustrativa e conservadora de marcadores de risco (consanguinidade
  confirmada, termos de doença rara/genealogia em texto livre) — uma
  taxonomia de risco real de reidentificação exige avaliação
  jurídica/clínica (P-06), ainda não disponível. A política atual é
  deliberadamente mais restritiva do que o necessário (fail-closed), nunca
  mais permissiva.
- O grafo desta sprint não usa seleção autônoma de tool pelo modelo
  (ReAct); um nó Python determinístico chama as tools diretamente antes de
  invocar o modelo, o que já satisfaz "tool revalida escopo e limita
  páginas/linhas/chamadas" com uma superfície de ataque menor (o modelo
  nunca decide qual tool chamar nem com quais argumentos). Uma futura
  sprint pode evoluir para seleção autônoma de tools sem migração
  incompatível, caso o produto queira essa capacidade.
- `AIJobKind` cobre `encounter_summary` e `patient_summary`; apenas o
  primeiro foi exercitado nesta homologação (o segundo reaproveita a mesma
  autorização/desidentificação/grafo, apenas sem `encounter_id`).
