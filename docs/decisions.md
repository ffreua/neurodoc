# Decisões, limites e responsáveis pendentes

Este documento rastreia as decisões arquiteturais adotadas no PRD (seção 3) e as
pendências P-01 a P-10, cada uma com dono e condição de liberação. É a referência
de S01-T01 e é atualizado sempre que uma pendência é resolvida ou uma decisão muda.

## Decisões adotadas (DEC-01 a DEC-21)

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
| DEC-21 | Segundo fator do link do documento: quatro últimos dígitos do CPF (ou data de nascimento, quando não há CPF), link válido por 30 dias — substitui o código de uso único de 8 dígitos/10 min/7 dias do RF-09.02 | Implementado em `communications/access.py`; **enfraquece** o segundo fator e alonga a validade do link, e por isso a proteção efetiva passa a ser o link opaco de 32 bytes com contador de tentativas atômico. Revisar se o portal do paciente passar a tratar pedido que não seja entrega de documento |
| DEC-21 | Base local de faixas de CEP dos Correios (`catalogs.PostalCodeRange`, 6.614 faixas versionadas em `catalogs/data/postal_ranges.csv`) como fonte de município/UF; ViaCEP fica apenas como complemento de logradouro/bairro | O cadastro resolve o endereço sem depender de rede; o conjunto local é por faixa municipal e não contém logradouro, por isso o complemento externo permanece — enviando somente o CEP, nunca dado do paciente |
| DEC-22 | CPF obrigatório no formulário de cadastro de paciente, não no modelo | Identifica o paciente em documento, guia e cobrança e bloqueia duplicata por CPF; o modelo continua aceitando nulo para não invalidar registros criados antes desta regra |
| DEC-23 | Roteiro de exame como árvore versionada carregada de YAML (`exams`), com o roteiro oficial publicado pela organização e derivação pessoal por médico | Especialidade nova é arquivo novo, sem alterar código; o atendimento guarda roteiro e versão, então registro antigo continua sendo lido com o roteiro com que foi preenchido |
| DEC-24 | Finalizar o atendimento sempre trava e registra hash, mesmo sem sessão de assinatura; a assinatura digital do prontuário fica pendente e pode ser feita depois | Decidido com o produto: exigir certificado para fechar a consulta impediria o médico sem PFX à mão de encerrar o atendimento. A imutabilidade não depende da assinatura |
| DEC-25 | Medicações em uso e resultados de exame pertencem ao **atendimento**, não ao paciente | O prontuário registra o que estava em uso naquela consulta, e é isso que fica imutável depois de finalizado. Lista viva do paciente mudaria o registro passado; a continuidade vem da cópia revisada do atendimento anterior (RF-03.04) |
| DEC-26 | A faixa de referência de analito laboratorial vem sempre do laudo, nunca de tabela interna; sem faixa no laudo o resultado fica "sem referência" e não é classificado | A faixa varia com laboratório, método, idade e sexo. Classificar contra referência de outra origem seria inventar a interpretação, e chamar de normal o que não foi comparado é pior que não classificar |
| DEC-27 | Leitura de laudo por IA produz **rascunho revisável**, nunca escrita direta no prontuário (RF-11-B); a transcrição é automática, a entrada no registro é de um clique | Extração de PDF erra em silêncio — troca coluna de referência por resultado, perde "menor que", junta linhas de hemograma. Gravado sem revisão, o erro fica indistinguível de dado conferido |
| DEC-28 | Hipóteses da IA carregam **prioridade qualitativa** (`higher`/`intermediate`/`lower`/`insufficient_evidence`), com validador que recusa percentual, e `requires_physician_review` fixo em `True` no esquema | RF-11.05 e PRD linha 805 já exigem isso. Percentual de modelo de linguagem no prontuário pareceria medida calibrada sem ter sido validado; e um campo que o modelo pudesse baixar para `False` seria caminho para pular a revisão |
| DEC-29 | Job de IA com fonte em documento usa o **anexo** como fonte de idempotência e de desatualização, não a versão do atendimento | Se usasse a versão do atendimento, corrigir uma vírgula na conduta marcaria como desatualizada a leitura de um PDF que não mudou |
| DEC-30 | Nenhuma `<textarea>` do sistema é redimensionável; a caixa cresce com o texto e o `rows` do formulário é a altura mínima | Arrastar o canto de um campo não é decisão que o prontuário deva pedir a quem atende, e cada caixa arrastada deixava a tela mais torta. Crescer sozinha entrega o que a alça entregava, sem o custo |
| DEC-31 | A finalização apura **todos** os requisitos faltantes de uma vez (`missing_requirements`), mostrados no modal antes do clique | A verificação em cascata fazia quem fechava a consulta descobrir a lista aos poucos, um erro por clique — parecia que o sistema não finalizava |
| DEC-32 | Busca sem acento no CID-10 por coluna derivada (`DiagnosisCode.search_text`), não por extensão `unaccent` | O usuário da aplicação não tem privilégio para criar extensão neste banco, e são 14 mil linhas: a varredura sequencial custa menos que a dependência. Importação e busca usam a **mesma** função de normalização, senão a busca passa a mentir em silêncio |
| DEC-33 | Hipótese sem CID continua permitida; hipótese **vazia** passa a ser recusada | Hipótese sem código é o caso comum da primeira consulta. Linha em branco com grau de certeza ao lado não é registro clínico de nada |
| DEC-34 | Tom neutro do `nd_tone` é `dark`, não `secondary` | Medido no navegador: `bg-soft-secondary` existe no CSS do tema mas não define fundo (`rgba(0,0,0,0)`). Como `secondary` era o tom de reserva, todo estado neutro e todo valor fora do mapa apareciam como texto solto |
| DEC-35 | O resumo do atendimento é página imprimível de leitura, **não** documento assinado, e diz isso no rodapé | Receita, relatório e encaminhamento têm fluxo próprio com assinatura digital. Folha impressa de resumo não deve circular parecendo laudo |
| DEC-36 | Peso e altura são `Observation` com data, não campos do paciente; a edição só grava medida quando o valor **muda** | A ficha mostrava IMC sem haver por onde informar peso e altura. Sendo série com data, salvar o cadastro sem tocar no peso não pode inserir uma medida idêntica e sujar a evolução |
| DEC-37 | A faixa de interpretação do IMC não é exibida abaixo de 20 anos | A classificação da OMS é para adulto; criança e adolescente usam percentil por idade e sexo. Escrever "obesidade" para uma criança de 8 anos é leitura errada com cara de laudo |
| DEC-38 | Atendimento **não finalizado** pode ser descartado com justificativa e log; finalizado, nunca | Abrir atendimento no paciente errado acontece, e a linha ficava na história para sempre. Finalizado é registro clínico e a correção lá é adendo |
| DEC-39 | O descarte **recusa** quando há documento médico emitido, cobrança lançada ou dado já levado para outra consulta, em vez de apagar em cascata | Apagar o atendimento por baixo deles deixaria uma receita assinada referindo uma consulta que não existe |
| DEC-40 | A agenda usa **célula base com ocupação variável**: a grade é do menor bloco e cada tipo ocupa N células | Duas durações na mesma janela (80 min de primeira consulta, 40 de retorno) não caberiam numa régua por tipo sem perder o calendário visual, que é o que responde "que horário posso oferecer" |
| DEC-41 | Duração por tipo é configurada **por médico** (`AppointmentTypeDuration`), e o fim da consulta é sempre calculado dela | RF-06.02 pede duração por tipo. Digitar o fim à mão era a porta de entrada de consulta com duração errada |
| DEC-42 | `follow_up` passou a "Seguimento" e entrou `return_visit` como "Retorno" | Eram coisas diferentes com o mesmo rótulo; sem separá-las não havia como declarar duas durações |
| DEC-43 | A agenda publicada **não é materializada**: a grade é calculada das regras, bloqueios e reservas | Um ano de agenda seriam milhares de linhas, e mudar a regra exigiria regeneração — com o risco de a agenda materializada discordar da regra |
| DEC-44 | Feriados nacionais são **calculados** (fixos + derivados da Páscoa), não baixados; estadual e municipal são cadastrados pela clínica | Calcular vale para qualquer ano e funciona sem rede. Local varia por lei e não é calculável — inventá-lo seria pior que pedir o cadastro |
| DEC-45 | Feriado **sugere** o bloqueio; quem bloqueia é o médico, dia por dia. Ponto facultativo entra desativado | Atender em feriado acontece (plantão, mutirão, reposição). E Carnaval é ponto facultativo, não feriado: ligá-lo por conta própria seria o sistema afirmar o que não pode |
| DEC-46 | Agendamento por telefone cria `Patient` com `registration_stage='preliminary'` (nome + telefone), e o cadastro completo é pedido no check-in | Exigir CPF e endereço na ligação significa perder o agendamento ou inventar dado. O telefone é obrigatório: pré-cadastro sem contato não pode ser confirmado depois |
| DEC-47 | Na visão de mês, "agendados" conta **pacientes**, não células de grade | Uma consulta de 80 min ocupa duas células e continua sendo um paciente; contar células faria a agenda parecer duas vezes mais cheia do que está |
| DEC-48 | A contagem do mês é calculada em massa (`month_summary`), com regras, bloqueios e reservas carregados uma vez | Montar 42 grades chamando o banco em cada uma seriam mais de cem consultas para desenhar um calendário; medido, são 3 |
| DEC-49 | Remarcar é feito pelo calendário do mês, e a **duração não é editável** | Quem remarca está ao telefone e precisa ver onde há vaga; digitar dois `datetime` obrigava a sair da tela. E remarcar é mudar o quando, não o quanto — digitar o fim seria a chance de encurtar a consulta sem querer |
| DEC-50 | Confirmação **manual** de horário dispensa o opt-in e a verificação que o lembrete automático exige | A secretária acabou de falar com a pessoa e confirma no número que ela passou: é transacional, pedida por quem atende, para quem marcou. Exigir verificação prévia inviabilizaria o pré-cadastro por telefone. A mensagem não leva conteúdo clínico |
| DEC-51 | Chave de API e senha de SMTP ficam **no banco, cifradas** (`base.crypto`), configuradas pelo gestor da clínica | Quem tem a chave do SMSDEV é a clínica, e cada uma tem a sua — não é segredo de infraestrutura. Em texto claro, um dump do banco entregaria a chave de SMS e a senha de e-mail de todas |
| DEC-52 | `SECRETS_MASTER_KEY` é separada de `PFX_MASTER_KEY`; enquanto não definida, cai na do PFX **e a tela avisa** | Comprometer a chave de SMS não deveria dar acesso ao certificado de assinatura. O fallback existe para a instalação atual continuar funcionando, não como recomendação |

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
