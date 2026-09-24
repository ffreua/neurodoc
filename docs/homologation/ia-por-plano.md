# A IA segue o plano contratado

O apoio clínico por IA passa a ser recurso do **Completo** e do
**Personalizado**. Gratuito e Básico não o recebem.

Evidências: `checks/check_ia_plano.py`, contra a pilha Docker local.

## O defeito que isto corrige

A linha de venda já existia sozinha. `tenancy/plans.py` anunciava, **só**
no Completo, "IA como copiloto do registro, sempre com revisão médica" — e
não havia nada no servidor cobrando isso. Uma clínica no Gratuito, com um
médico verificado, tinha a IA inteira: chat de apoio, apoio ao raciocínio
diagnóstico, leitura de laudo e resumo automático do atendimento.

Era exatamente a divergência que o cabeçalho daquele módulo diz que o
acoplamento impede — texto de venda e comportamento no mesmo arquivo —, e
ela estava dentro do próprio arquivo.

## Quem paga a conta decide o desenho

`ai/providers/__init__.py::get_chat_model` resolve o modelo em duas
origens, e a ordem importa:

1. a clínica que configurou `AIProviderSettings` usa **a chave dela**,
   cifrada no banco. Contrato dela, fatura dela;
2. quem não configurou cai na chave da instalação (`AI_API_KEY`) — e aí a
   conta é de quem hospeda.

Por isso o corte é **por plano**, e não por volume. Uma cota mensal
limitaria também a clínica que traz a própria chave, cobrando por algo que
não custa nada a quem hospeda. E uma cota justa exigiria contar *tokens*,
que o sistema não registra hoje: contar requisições trataria igual um
resumo de oitocentos tokens e um turno de chat de quarenta mil.

Cota continua fazendo sentido depois, e o molde existe (`tenancy/limits.py`
— aviso em 80 %, `*_limit_override` no `Tenant`). O que falta antes é
instrumentar o consumo.

## Onde o bloqueio mora

Duas camadas, e cada uma fecha portas que a outra não alcança.

**1. `tenancy/permissions.py::capabilities_for`** ganhou `ai_contracted`,
que é `plans.has_clinical_ai(tenant.plan)`. É *veto*, aplicado depois dos
papéis: nenhuma combinação de papel devolve `CLINICAL_AI` numa clínica que
não contratou. Como o `AccessContext` é reconstruído do banco a cada
requisição, rebaixar o plano corta a IA na requisição seguinte.

O argumento é **obrigatório e nomeado**. Um padrão `True` manteria os
cinco chamadores compilando e nenhum deles cobrando o plano — o defeito
que não aparece em teste nenhum: a tela abre, a IA responde, e a fatura é
de quem hospeda.

Fecha: as telas de `/app/ai/`, o link na barra lateral, a reconferência a
cada volta do *stream* SSE e a tarefa Celery do chat.

**2. `ai/context.py::build_ai_authorization`** recusa quando o plano não
inclui a IA. É por onde passa **todo** trabalho de IA: a criação do job, a
reconferência imediatamente antes da chamada ao provedor, e o resumo
automático de `ai/handlers.py` — que nasce de um evento, sem tela nenhuma
e sem ninguém clicando.

Só a camada 1 fecharia as portas que têm tela e deixaria aquela aberta.
E, pela mesma razão que o vínculo é relido ali, o plano também: um
rebaixamento entre enfileirar e executar é o mesmo caso de um vínculo
revogado no meio, e a última chance de não gastar a chave é essa.

## O resumo automático sai por `return`, não por exceção

`ai/handlers.py` é consumidor de evento. Exceção ali faz o despachante
reentregar com recuo e, esgotadas as tentativas, marcar o evento como
`FAILED` (`events/dispatcher.py`). Mas nada falhou: a clínica não
contratou o recurso, e o evento foi processado corretamente ao não fazer
nada. Deixar isso virar falha encheria a caixa de eventos de falha falsa a
cada atendimento finalizado — e esconderia a falha de verdade quando
viesse.

O handler já saía por `return` para `AI_ENABLED=False` e para a clínica
que não ligou o resumo. O plano entrou na mesma forma, pelo mesmo motivo.

## O que o usuário vê

| Tela | Plano sem IA |
| --- | --- |
| Chat de apoio (`/app/ai/chat/`) | 404, e o link some da barra lateral |
| Apoio ao raciocínio diagnóstico | o bloco some do prontuário |
| "Ler laudo com IA" | o botão e a caixa somem; **o estado de leituras anteriores continua visível** |
| Configuração da IA (`/app/org/ia/`) | abre e explica qual plano tem o recurso; o formulário sai |

A configuração é a única que **não** recusa por 404, e a diferença é
deliberada: quem abre aquela tela é o dono ou o gestor — quem contrataria
o plano. Escondê-la ensinaria que o recurso não existe; mostrá-la
explicando responde à pergunta que a pessoa foi fazer. O que ela não pode
é deixar gravar: uma chave de provedor guardada numa clínica onde a IA
nunca vai rodar é uma armadilha — a tela diria "configurada" e nada
funcionaria. Por isso o bloqueio é **por verbo HTTP**, num lugar só, igual
ao que `TenantMiddleware` faz com a clínica suspensa.

## Não é prontuário, e por isso o corte pode ser total

`tenancy/limits.py` estabelece que rebaixar congela e **nada fica
inacessível** — uma clínica que cai de plano mantém os pacientes que já
tem, com o prontuário intacto. Valia perguntar se a IA entra nessa
promessa.

Não entra, e quem diz isso é o próprio código:

- `ai/review.py::accept_artifact` — aceitar uma sugestão "é juízo
  editorial sobre o texto; não assina, não prescreve e não emite nada". O
  que vira registro é o que o médico escreveu no atendimento, e isso vive
  em `clinical`;
- `ai/chat_views.py::ChatSessionDeleteView` — "isto não é prontuário.
  Conversa de apoio não entra no registro clínico do paciente". O usuário
  pode apagá-la inteira quando quiser.

A promessa de acessibilidade protege o prontuário, que a Lei 13.787/2018
manda guardar por vinte anos. Ela não se estende a um andaime que o
próprio usuário pode jogar fora. Por isso uma capacidade só, e não uma
para ler o histórico e outra para gastar.

## Um defeito encontrado pelo roteiro

O bloqueio da tela de configuração estava escrito **antes** da conferência
de capacidade. Quem não tem `MANAGE_INTEGRATIONS` — uma secretária, um
médico sem papel administrativo — recebia `403` no POST e `404` no GET da
mesma rota. O 403 contava que a tela existe, que é exatamente o que a
recusa por 404 evita no resto de `/app/`.

Só apareceu porque o roteiro pegou "o primeiro médico" da clínica de
demonstração, que é o médico sem papel administrativo. A conferência de
capacidade passou para antes do plano, e o roteiro agora exercita três
vínculos diferentes de propósito — médico, gestor, e médico sem papel
administrativo — e cobra os dois códigos.

## Nada disso muda o banco

Não há migração: o gate é catálogo em código mais uma leitura de
`tenant.plan`. Um rebaixamento não apaga job, artefato nem conversa — o
que já existe permanece no banco, e volta a ficar acessível se o plano
voltar.

## O que foi verificado

`checks/check_ia_plano.py`, oito seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | Catálogo e vitrine concordam? | Completo anuncia e tem; ninguém anuncia o que não tem |
| 2 | A capacidade segue o plano? | Completo sim, Básico não — e a leitura de prontuário fica |
| 3 | Dá para chamar `capabilities_for` sem decidir? | `TypeError` |
| 4 | A autorização do job recusa? | sim, dizendo que o motivo é o plano |
| 5 | Rebaixar entre enfileirar e executar? | recusado |
| 6 | O resumo automático cria job? levanta? | nem um nem outro |
| 7 | O chat abre pela URL direta? o link some? | 404, e some |
| 8 | A configuração explica? deixa gravar? | explica; POST em 403, e 404 para quem não tem a capacidade |

Plano desconhecido no `Tenant` cai em "sem IA" — a mesma direção de erro
do `plan_config`, que cai no menor limite. Errar para o lado do menor
direito aparece como "recurso não disponível, fale conosco"; errar para o
outro lado gasta a chave da instalação sem contrato.

## O que ficou de fora, e por quê

**Desvio por clínica** (um `ai_override` no `Tenant`, como
`patient_limit_override`). Hoje, vender IA a uma clínica no Básico exige
movê-la para o Completo, o que também muda os limites de paciente e de
médico. O molde existe e o precedente é do próprio arquivo — mas é decisão
comercial, não técnica: depende de a IA ser vendável à parte.

**Contagem de consumo.** Nenhum token é registrado hoje. É o pré-requisito
de qualquer cota futura, e não se verifica sem uma chave real de provedor
— por isso não entrou junto.
