# Decisões, limites e responsáveis pendentes

Este documento rastreia as decisões arquiteturais adotadas no PRD (seção 3) e as
pendências P-01 a P-10, cada uma com dono e condição de liberação. É a referência
de S01-T01 e é atualizado sempre que uma pendência é resolvida ou uma decisão muda.

## Decisões adotadas (DEC-01 a DEC-20)

| ID | Decisão adotada e objetivo preservado | Estado/impacto |
| --- | --- | --- |
| DEC-01 / CR-01 | Stack `neurodoc_v1`; redes `traefik_public`, `neurodoc_v1_internal`, `neurodoc_v1_egress`. Registry permanece `ghcr.io/pycodebr/scsi_v1` | Nomes fixos; propriedade do registry pendente (ver P-02) |
| DEC-02 / CR-02 | Vocabulário clínico. "Sinistro" é resíduo de outro domínio; "negociação" limita-se a registros financeiros autorizados | Não criar corretora ou módulo de seguros |
| DEC-03 / CR-03 | `core` configura o projeto; `base` concentra primitivas pequenas compartilhadas; apps de domínio na raiz | Não criar um app monolítico |
| DEC-04 / CR-04 | Timestamps em models próprios e relações intermediárias explícitas; tabelas internas de bibliotecas permanecem sob gestão delas | Exceção documentada |
| DEC-05 / CR-05 | Papéis acumuláveis por vínculo; dono não recebe automaticamente permissões clínicas | Exige matriz de permissões |
| DEC-06 / CR-06 | OpenRouter/GLM padrão; OpenAI/Anthropic selecionáveis por administrador técnico; sem fallback externo implícito | Qualquer provedor deve cumprir política de dados |
| DEC-07 / CR-07 | Sessão de assinatura de 2/4/6/12 horas, sempre com ação médica por documento | A assinatura produzida não expira ao encerrar a sessão |
| DEC-08 / CR-08 | Desidentificação local; reidentificação reversível continua sendo pseudonimização; envio externo bloqueado quando não satisfaz a política | IA externa pode ficar indisponível para certos casos |
| DEC-09 / CR-09 | `collectstatic --clear` em staging por release; publicação atômica, retenção de releases e leitura dinâmica dos assets | Evitar limpeza de arquivos em uso |
| DEC-10 / CR-10 | App migra com advisory lock; worker/beat aguardam dependências e migrations locais aplicadas | Não depender de depends_on no Swarm |
| DEC-11 / CR-11 | Duas réplicas web, start-first, atualização sequencial, healthchecks e verificação posterior | Meta de continuidade; não é HA contra perda da VPS |
| DEC-12 / CR-12 | Parser literal de `.env`, env_files por serviço e configuração de stack gerada com valores controlados | Nenhum source/eval; secrets fora de env_file |
| DEC-13 / CR-13 | Três redes pré-criadas; interna com `docker network create --internal`; stack apenas referencia redes externas | A propriedade efetiva Internal deve ser inspecionada |
| DEC-14 / CR-14 | Captura com agente local de importação de pasta, pareado à sessão clínica; upload manual disponível desde M1 | Não prometer API universal de scanner no navegador |
| DEC-15 | Sessão seleciona tenant em `neurodoc.app.br/app/`; subdomínios opcionais são aliases registrados, sem inferência de permissão | Simplifica início; wildcard TLS permanece |
| DEC-16 | Um tenant por CNPJ cadastrado; filiais jurídicas distintas podem ter tenants distintos | Política proposta; revisão antes do onboarding se houver unidades com mesmo CNPJ |
| DEC-17 | SSR com Django Templates, JavaScript pequeno e SSE; ASGI/Uvicorn em produção | Evitar SPA sem necessidade |
| DEC-18 | Redis: resultados DB 0, cache DB 1, eventos transitórios DB 2; fonte clínica definitiva no PostgreSQL | Separação lógica não é fronteira de segurança |
| DEC-19 | PostgreSQL 17, roles separadas para migração e execução, nenhum superuser no Django | App recebe credencial de DDL por exigir migrations no entrypoint; risco residual documentado |
| DEC-20 | Nenhuma suíte de testes automatizados | Decisão confirmada; revisão, verificação sintática e homologação manual continuam obrigatórias |
| DEC-21 | Base local de faixas de CEP dos Correios (`catalogs.PostalCodeRange`, 6.614 faixas versionadas em `catalogs/data/postal_ranges.csv`) como fonte de município/UF; ViaCEP fica apenas como complemento de logradouro/bairro | O cadastro resolve o endereço sem depender de rede; o conjunto local é por faixa municipal e não contém logradouro, por isso o complemento externo permanece — enviando somente o CEP, nunca dado do paciente |
| DEC-22 | CPF obrigatório no formulário de cadastro de paciente, não no modelo | Identifica o paciente em documento, guia e cobrança e bloqueia duplicata por CPF; o modelo continua aceitando nulo para não invalidar registros criados antes desta regra |
| DEC-23 | Roteiro de exame como árvore versionada carregada de YAML (`exams`), com o roteiro oficial publicado pela organização e derivação pessoal por médico | Especialidade nova é arquivo novo, sem alterar código; o atendimento guarda roteiro e versão, então registro antigo continua sendo lido com o roteiro com que foi preenchido |
| DEC-24 | Finalizar o atendimento sempre trava e registra hash, mesmo sem sessão de assinatura; a assinatura digital do prontuário fica pendente e pode ser feita depois | Decidido com o produto: exigir certificado para fechar a consulta impediria o médico sem PFX à mão de encerrar o atendimento. A imutabilidade não depende da assinatura |
| DEC-25 | Medicações em uso e resultados de exame pertencem ao **atendimento**, não ao paciente | O prontuário registra o que estava em uso naquela consulta, e é isso que fica imutável depois de finalizado. Lista viva do paciente mudaria o registro passado; a continuidade vem da cópia revisada do atendimento anterior (RF-03.04) |
| DEC-26 | A faixa de referência de analito laboratorial vem sempre do laudo, nunca de tabela interna; sem faixa no laudo o resultado fica "sem referência" e não é classificado | A faixa varia com laboratório, método, idade e sexo. Classificar contra referência de outra origem seria inventar a interpretação, e chamar de normal o que não foi comparado é pior que não classificar |
| DEC-27 | Leitura de laudo por IA produz **rascunho revisável**, nunca escrita direta no prontuário (RF-11-B); a transcrição é automática, a entrada no registro é de um clique | Extração de PDF erra em silêncio — troca coluna de referência por resultado, perde "menor que", junta linhas de hemograma. Gravado sem revisão, o erro fica indistinguível de dado conferido |
| DEC-28 | Hipóteses da IA carregam **prioridade qualitativa** (`higher`/`intermediate`/`lower`/`insufficient_evidence`), com validador que recusa percentual, e `requires_physician_review` fixo em `True` no esquema | RF-11.05 e PRD linha 805 já exigem isso. Percentual de modelo de linguagem no prontuário pareceria medida calibrada sem ter sido validado; e um campo que o modelo pudesse baixar para `False` seria caminho para pular a revisão |
| DEC-29 | Job de IA com fonte em documento usa o **anexo** como fonte de idempotência e de desatualização, não a versão do atendimento | Se usasse a versão do atendimento, corrigir uma vírgula na conduta marcaria como desatualizada a leitura de um PDF que não mudou |

## Pendências que não impedem a especificação (P-01 a P-10)

| ID | Informação/validação pendente | Quem resolve | Momento limite | Estado nesta execução |
| --- | --- | --- | --- | --- |
| P-01 | `design_system/design-system.html` não foi fornecido nesta execução | Produto/design | Antes de homologar qualquer aderência visual | **Resolvida.** O arquivo real (Duralux — Living Design System) está disponível em `design_system/design-system.html` com os assets em `design_system/refs/duralux/`. Inventariado em [`docs/design-system.md`](design-system.md) (S01-T02). |
| P-02 | URL Git, permissão GHCR, IP/arquitetura e acesso da VPS | Responsável técnico | S01 / primeiro deploy | **Pendente.** Nenhuma VPS foi acessada nesta execução; ver [`docs/operations/environment.md`](operations/environment.md). Bloqueia S10-T01/T02. |
| P-03 | SMTP, SMSDEV, orçamento de IA e contatos reais de operação | Produto/operação | Antes de habilitar canais reais | **Pendente.** `EMAIL_ENABLED`, `SMS_ENABLED` e `AI_ENABLED` permanecem `False` no ambiente local/exemplo até a resolução. |
| P-04 | Resolução conjunta de dependências e digest das imagens | Desenvolvimento | S01; novas releases revisam lock | **Resolvida para S01/S02.** `requirements.in` resolvido via `uv pip compile --generate-hashes` em contêiner `python:3.14.7-slim-bookworm`, gerando `requirements.txt` com hashes (ver `docs/operations/environment.md`). Digests de imagem de produção continuam pendentes de publicação real (depende de P-02). |
| P-05 | Validação da assinatura com certificado A1 real autorizado, cadeia, revogação e modalidade documental | Médico responsável + segurança | Antes de emissão clínica | **Pendente.** Sem certificado real; escopo de S07. |
| P-06 | Base legal, contratos de operadores, retenção, transferência internacional, RIPD e política de anonimização | Controlador + assessoria especializada | Antes de dados reais/IA externa | **Pendente.** Bloqueia S11/S12 para dados reais. |
| P-07 | Situação atual e acesso técnico ao SNCR/modalidades controladas | Produto + responsável regulatório | Antes da respectiva funcionalidade | **Pendente.** |
| P-08 | Windows/software do scanner e diretório de saída de cada consultório | Operação da clínica | S13 | **Pendente**; não bloqueia S01-S12. |
| P-09 | Validação de enquadramento regulatório do apoio diagnóstico, inclusive eventual SaMD | Produto + regulatório | Antes de divulgar finalidade clínica da IA | **Pendente.** Bloqueia M3. |
| P-10 | Destino externo e titular da chave de recuperação de backup | Operação + controlador | Antes do piloto assistencial | **Pendente.** Bloqueia S10-T05 e o piloto assistencial (M2). |

## Limites explícitos desta execução (S01)

- Nenhuma VPS, conta de provedor ou ambiente de produção foi acessado (P-02 segue aberta).
- `requirements.txt` só passa a existir com hashes reais gerados por resolução em Python 3.14.7; nenhum lock foi inventado.
- Nenhuma suíte de testes automatizados foi criada (DEC-20); verificação sintática (AST/`sh -n`/YAML), `pip check`, `mkdocs build --strict` e convergência do `compose.yml` local substituem testes automatizados nesta fase.
- Os apps de domínio criados nesta sprint são esqueletos carregáveis (`AppConfig`, `models.py` vazio ou mínimo) — a modelagem completa da seção 9 é objeto das sprints S02 em diante.

## Decisões de implementação (S02)

- **User sem `AbstractUser`.** A seção 9.2 descreve "AbstractUser customizado
  com username removido"; a implementação usa `AbstractBaseUser` +
  `PermissionsMixin` diretamente (padrão oficial do Django para usuário
  totalmente customizado). O resultado observável é idêntico — nenhum campo
  `username`, login por e-mail, `id` UUID — e evita carregar/mascarar um campo
  que seria imediatamente removido.
- **`permissions` do `AccessContext` são os papéis da Membership.** A seção 10.1
  define `AccessContext(user_id, tenant_id, membership_id, permissions,
  request_id)` sem detalhar o formato de `permissions`. Nesta sprint,
  `permissions` é o conjunto (`frozenset`) dos papéis (`owner`/`doctor`/
  `secretary`/`manager`) da Membership ativa. A matriz fina de permissões por
  ação (seção 4) será aplicada nas views de cada app à medida que forem
  implementadas — não existe ainda nenhuma view clínica/administrativa para
  aplicá-la.
- **Confirmação de e-mail bloqueia toda a área `/app/`.** RF-01.04 fala em
  "confirmação de e-mail antes de acesso clínico"; como ainda não há
  separação entre áreas clínicas e administrativas dentro de `/app/`, o
  bloqueio por e-mail não confirmado (`build_access_context`) é aplicado a
  toda a área por enquanto — revisar quando houver telas puramente
  administrativas que não devam depender disso.
- **Envio de e-mail de confirmação usa o backend nativo já configurado**
  (`console`/`locmem` em dev, já que `EMAIL_ENABLED=False`); a integração SMTP
  real do worker é S08-T03, conforme a matriz de rastreabilidade (RF-01.04:
  S02-T01, S02-T06, S08-T03).
