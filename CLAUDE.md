# NeuroDoc — mapa do sistema

Prontuário eletrônico e gestão para consultório de **neurologia e
neurocirurgia**, multi-inquilino (uma instalação, várias clínicas). Django
monolítico modular, SSR com Django Templates, PostgreSQL como fonte de
verdade clínica, Celery para trabalho pesado.

Este arquivo é o mapa. O detalhe de cada decisão está em `PRD.md` (a
especificação, ~360 KB) e em `docs/` (homologação por sprint, publicada em
`/technical-docs/`).

---

## 1. Convenções do repositório (leia antes de editar)

- **Idioma:** o produto, os comentários novos e as mensagens de commit são
  em **português**. Código mais antigo tem comentários em inglês; não
  traduza em massa.

  **Isso inclui mensagem de erro**, que é justamente a que escapa: ela só
  aparece no caminho que deu errado, e esse é o caminho que ninguém
  exercita ao escrever a tela. Dezenove mensagens atravessaram até
  produção assim — a do bloqueio de login ("Too many attempts") foi
  encontrada pelo próprio médico. `check_idioma.py` varre `messages.*`,
  `ValidationError`, `label=`, `help_text=` e as exceções que as views
  mostram com `str(exc)`. Exceção que só quem opera o servidor lê pode
  ficar em inglês.
- **Comentário explica *por quê*, nunca *o quê*.** O estilo da casa é um
  bloco no topo do módulo/atributo dizendo qual erro aquela escolha
  impede, com a alternativa recusada e o motivo. Veja `tenancy/plans.py`,
  `tenancy/permissions.py` ou `core/settings.py` — imite isso.
- **Não há suíte de testes automatizados** (DEC-20). O substituto são os
  *roteiros de verificação* em `checks/` (ver §7) e os documentos de
  homologação em `docs/homologation/`. Ao mudar comportamento, rode o
  roteiro correspondente e atualize o documento.
- **Números do negócio moram em código, não no banco.** Planos, limites e
  preços estão em `tenancy/plans.py` justamente para que mudá-los seja um
  commit com autor e data — e nunca escritos à mão num template.
- `None` significa **ilimitado** em todo `tenancy/plans.py`. Nunca use um
  número grande.
- **O nome de pessoa tem uma forma só.** `patients.naming.normalizar_nome`
  — caixa alta, sem espaço sobrando — e ela é **gravada**, no `clean()` e
  no `save()` do `Patient`. Quem criar paciente por caminho novo não
  precisa lembrar; quem copiar o nome para outro lugar (o contato do
  próprio paciente, por exemplo) deve copiar **da ficha**, nunca do texto
  digitado.
- **Nunca pergunte a data ao relógio do processo.** O contêiner roda em
  `Etc/UTC` e o produto em `America/Sao_Paulo`: entre 21h e meia-noite o
  UTC já está no dia seguinte, e `timezone.now().date()`, `date.today()` e
  `datetime.now()` respondem **amanhã** por três horas, toda noite. Use
  `django.utils.timezone.localdate()` e `localtime()`. `check_fuso.py`
  varre o repositório e reprova quem esquecer — a verificação é estrutural
  porque o defeito só aparece em três horas do dia, e um roteiro
  comparativo passaria nas outras vinte e uma.

## 2. Topologia

```
Navegador → Traefik (TLS) → Django ASGI (app) → PostgreSQL
                                   ↓
                              RabbitMQ → Celery worker → PostgreSQL
                                              ↓         ↘ IA / SMTP / SMSDEV
                                           Redis  → SSE de volta ao app
```

Sete serviços permanentes: `app`, `celery_worker`, `celery_beat`, `db`,
`rabbitmq`, `redis`, `traefik` (+ `mailpit` só no ambiente local).

**Regra de rede que explica muito código:** e-mail, SMS, IA e o espelho da
TUSS saem sempre por **tarefa Celery**, nunca de dentro da requisição. O
worker está em `neurodoc_v1_egress`, tem a chave de SMTP (só a ele o
segredo é entregue) e pode tentar de novo quando o provedor falha; uma
requisição web não pode nada disso — ela espera o timeout com o usuário
olhando. Ver `communications/mail_backend.py` e o comentário de
`EMAIL_BACKEND` em `core/settings.py`.

**O que este parágrafo dizia e não era verdade** (corrigido em
2026-10-02): que o processo `app` *não tem saída para a internet*. Ele
tem. `neurodoc_v1_internal` é `internal: true`, mas o `app` está também em
`traefik_public`, que **não** é — e o Traefik precisa de saída para o
ACME do Let's Encrypt. Basta uma rede sem `internal` para o contêiner
ganhar rota default, então o isolamento que o desenho pretendia nunca
existiu.

Isso importa por dois motivos, e o segundo é o que custa caro: perde-se a
defesa em profundidade (execução arbitrária no `app` conseguiria
exfiltrar), e **o documento induz a erro de diagnóstico** — nesta sessão,
um defeito de entrega foi atribuído a "timeout por falta de egresso"
quando a causa era outra. Fechar o furo é separar o Traefik do `app` em
duas redes (Traefik ↔ internet para o ACME, Traefik ↔ app interna);
trabalho aberto, com o risco de mexer na rede de produção. Até lá, o que
vale é o parágrafo acima: a regra de pôr trabalho externo no worker
continua certa, pelas razões certas.

## 3. Multi-inquilino e autorização

Três camadas, e vale conhecer as três antes de mexer em qualquer view:

1. **`tenancy/middleware.py` (`TenantMiddleware`)** — atua só em `/app/`.
   Resolve a organização da sessão, monta `request.access_context` e
   devolve 404 para quem não tem vínculo. Também aplica o estado comercial
   da clínica: `SUSPENDED` congela (lê, não escreve — bloqueio por verbo
   HTTP, num lugar só), `CLOSED` fecha com tela explicativa.
2. **`tenancy/context.py` (`AccessContext`)** — dataclass imutável por
   requisição com `user_id`, `tenant_id`, `membership_id`, papéis e
   **capacidades**. Reconstruído do banco a cada requisição, de propósito:
   vínculo revogado para de autorizar imediatamente.
3. **`tenancy/permissions.py`** — a matriz do PRD §4 em código. As views e
   os templates perguntam `ctx.can(Capability.READ_CLINICAL)`, **nunca**
   `'doctor' in roles`. Papéis: `owner`, `doctor`, `secretary`, `manager`.

No banco, o isolamento é reforçado por **chave estrangeira composta**:
todo `TenantModel` carrega `UNIQUE(tenant_id, id)` — isso vale para todos
— e os filhos referenciam `(tenant_id, fk)`, de modo que a linha não
consegue apontar para objeto de outro inquilino nem por bug de aplicação.
Ver `base/db.py::composite_tenant_foreign_key`.

**A restrição composta está aplicada em `clinical` e `teamchat`**
(`clinical/migrations/0009_*`, `teamchat/migrations/0001_*`), e não nos
demais apps. Até 2026-09-19 só o `teamchat` a tinha, e este parágrafo
dizia que todos a tinham — o `UNIQUE(tenant_id, id)` estava em toda parte
e a chave que ele habilita, em lugar nenhum. Estender a `patients`,
`documents`, `scheduling`, `finance` e `communications` é trabalho aberto;
até lá, o que separa as clínicas nesses apps é o filtro por inquilino em
cada consulta, sem a rede embaixo.

**Rotas fora de `/app/` são públicas ou de instalação, de propósito:**
`/` (vendas), `/accounts/`, `/verificar/` (QR do documento, aberto na
farmácia), `/solicitacoes/` (portal do paciente, sem conta), `/d/`
(entrega por link opaco), `/descadastrar/`, `/instalacao/` (console do
superadministrador — fora de `/app/` porque quem opera o servidor não tem
vínculo com clínica nenhuma), `/admin/` e `/technical-docs/` (MFA).

## 4. Apps de domínio

| App | O que guarda / faz |
| --- | --- |
| `core` | settings, urls, asgi, celery |
| `base` | primitivas compartilhadas (`TenantModel`, cripto, logging com redação, widgets), **página de vendas** (`base/views.py::LandingView`), textos de venda (`base/content.py`) e central de ajuda (`base/help_content.py`) |
| `accounts` | `User` (e-mail como login), MFA TOTP, códigos de recuperação, `PhysicianProfile` (CRM) |
| `tenancy` | `Tenant`, `Membership`, `ClinicProfile`, `Invitation`, `Lead`, `ClinicMessage` (a clínica falando com quem mantém a instalação), `ContractAcceptance`; **planos, limites, a matriz de permissão e o contrato de adesão** (`contract.py`) |
| `patients` | `Patient`, contatos, convênio/`PatientCoverage`, numeração por clínica, foto, **forma canônica do nome** (`naming.py`: caixa alta, gravada) e a **migração de cadastro** de outro sistema (`importacao.py` + `import_pacientes_xml`) |
| `catalogs` | CID-10, espelho da TUSS (sincronizado semanalmente pelo worker), **medicamentos da CMED/Anvisa** (26 mil apresentações, com a tarja) e CEP dos Correios |
| `clinical` | `Encounter` em dois tipos (`kind`: prontuário estruturado ou **texto livre**), achados do exame, diagnósticos, medicações, resultados de exame e valores laboratoriais, aditamento, cópia da consulta anterior, **busca de paciente por CID** (`por_cid.py`) e a **série temporal** em gráfico (`series.py`) |
| `exams` | motor do roteiro de exame em árvore (387 nós, YAML) e 14 escalas pontuadas |
| `scheduling` | agenda por médico, regras de disponibilidade, bloqueios, feriados, **retorno programado** (`returns.py`), a **declaração de comparecimento** (`declaracao.py`) e as **estatísticas do mês** (`estatisticas.py`, contagens para os quatro papéis) |
| `documents` | anexos (com antivírus), documentos médicos, **assinatura PAdES** via pyHanko, verificação pública por QR, portal de solicitações (com **janela de retorno**, `portal_retorno.py`), OCR, arquivo morto |
| `communications` | outbox de entrega (e-mail/SMS), links opacos com OTP, campanhas com consentimento, credenciais SMTP/SMS da clínica |
| `finance` | tabela de honorários com vigência, recebíveis, pagamentos, ajustes (tudo em `Decimal`) |
| `ai` | jobs de IA com revisão médica obrigatória, desidentificação, chat persistente com streaming (Redis Streams + SSE), catálogo de dez provedores e o **relatório do paciente** (`relatorio.py`: a IA redige, o médico revisa e assina) |
| `notifications` | sino do usuário |
| `teamchat` | **mensagens internas da equipe** — janela flutuante ao lado do sino, conversa de duas pessoas, presença e entrega ao vivo (Redis Streams + SSE). Não é prontuário, e a tela diz isso |
| `audit` | trilha imutável (`record_audit_event`) |
| `reporting` | indicadores e **exportação do acervo** (cadastro e prontuário em Markdown e JSON); CSV protegido contra injeção de fórmula, tudo expira em 24 h |
| `integrations` | antivírus, CEP e TUSS; os modelos antigos de captura permanecem apenas como proveniência histórica |
| `events` | outbox de eventos de domínio com dispatcher idempotente e múltiplos consumidores por tópico |
| `ops` | deploy, backup/restauração, saúde, console do superadministrador (inclusive **Operação**, as chaves que se viram sem republicar), geração do compose local |

## 5. Planos, limites e preço

**Fonte única: `tenancy/plans.py`.** Quatro planos (`free`, `basic`,
`complete`, `custom`), cada um com `max_patients`, `max_doctors`,
`price_monthly` **em centavos**, texto de venda e `features`.

- Preço em centavos, nunca em `float` — `158.00 * 12` em ponto flutuante
  dá `1895.9999999999998`.
- O **anual deriva do mensal** (`MESES_NO_ANO`); o **preço de tabela
  ("de") deriva do preço cobrado** (`DESCONTO_PROMOCIONAL`). Nenhum
  desses números é escrito a mão duas vezes.
- Três estados de preço, e a tela distingue os três: grátis (`0`), com
  preço de tabela, e **sem** preço de tabela (`None` — o Personalizado,
  que não é grátis, é combinado).
- `pricing(code)` devolve tudo já formatado; `public_plans()` monta a
  vitrine na ordem de `PUBLIC_ORDER`; `plan_choices()` alimenta o menu do
  formulário de contato — acrescentar um plano aparece nos três.
- **A cobrança é anual.** O valor mensal exibido é a referência do que o
  plano custa por mês dentro do pagamento anual.

**Limites: `tenancy/limits.py`.** Conta paciente **ativo** (arquivar
libera vaga) e médico com o papel. `patient_limit_override` /
`doctor_limit_override` no `Tenant` vencem o plano; nulo cai no plano —
é assim que uma clínica negocia 1.200 pacientes sem virar um quinto plano.
Aviso a partir de 80 %; no limite, bloqueia. **Rebaixar congela: nada é
apagado nem fica inacessível.** A trava vale em seis portas (cadastro
completo, pré-cadastro da agenda, quatro caminhos do papel médico).

**O apoio clínico por IA é recurso de plano** (`clinical_ai` em
`plans.py`): Completo e Personalizado têm; Gratuito e Básico, não. A
vitrine já anunciava isso só no Completo e o servidor não cobrava — uma
clínica no Gratuito tinha a IA inteira. O bloqueio mora em dois lugares, e
os dois são necessários: `capabilities_for` recebe `ai_contracted` e veta
`CLINICAL_AI` (telas, barra lateral, stream SSE, tarefa do chat), e
`ai/context.py::build_ai_authorization` recusa (criação do job, a
reconferência antes de falar com o provedor, e o resumo automático, que
nasce de um evento e não passa por tela). O corte é por plano e não por
cota porque a clínica que configurou a própria chave paga a própria conta
— ver `docs/homologation/ia-por-plano.md`.

Acesso é liberado por **código de convite** (`tenancy/invitations.py`), que
carrega o plano contratado — não há pagamento on-line.

**Contrato de adesão: `tenancy/contract.py`.** Dezoito cláusulas,
**redigidas pela Dra. Karina Albuquerque Freua, OAB/SP nº 450.476** —
não são texto nosso, e correção de redação passa por ela. O texto mora em
código pelo mesmo motivo dos preços: mudá-lo é um commit com autor e
data. `VERSAO` identifica a redação, e **nunca se edita uma versão já
aceita** (cláusula 17.6): texto novo é versão nova.

O aceite é obrigatório no cadastro, em **duas** caixas — "li e aceito" e
"tenho poderes para contratar por esta clínica" (cláusula 2.2, "i") —, e
grava versão, SHA-256, **cópia integral do texto aceito** (cláusula 2.3),
plano e valor anual (2.2, "h"), quem aceitou, IP, navegador e os dois
prazos (arrependimento de 7 dias, vencimento no aniversário). Uma via
completa vai por e-mail ao contratante, tirada da cópia arquivada e não
do texto corrente. `/contrato/` é público; `/instalacao/contratos/` lista
os aceites e acusa quem aponta para um texto diferente do que está no ar.
O que o contrato fixa em matéria de LGPD, e o que ele promete e ainda não
existe (os Anexos I a V), está em `docs/governance/lgpd.md` §9.

## 6. Ambiente local

```bash
python -m ops.local_compose     # gera compose.yml e os env_files a partir do .env
docker compose up -d --build
docker compose exec app python manage.py migrate
docker compose exec app python manage.py seed_demo
```

- App em `http://localhost:8000`, via Traefik em `:8080`, caixa de e-mail
  do Mailpit em `http://localhost:8025`.
- **Abrir no celular** (a aderência ao toque não se confere no emulador do
  navegador): ponha `NEURODOC_LAN_HOST=<IP desta máquina no Wi-Fi>` no
  `.env` e regenere. São três travas em série, e o gerador abre as três de
  uma vez — porta publicada em `0.0.0.0`, o IP em `ALLOWED_HOSTS` e a
  origem em `CSRF_TRUSTED_ORIGINS`; abrir só uma dá conexão recusada, 400
  ou login que não passa, nessa ordem. Falta ainda liberar a porta no
  firewall do Windows, **no perfil da rede privada** — assim a regra vale
  em casa e não segue valendo no Wi-Fi do aeroporto. Vazio, que é o
  padrão, mantém tudo preso ao `127.0.0.1`. O Mailpit continua local: não
  há motivo para a caixa de e-mail atravessar a rede.
- `compose.yml` é **gerado** a partir de `docker-stack.yml` — edite o
  stack e regenere, não edite `compose.yml` à mão.
- Segredos ficam em `.secrets/<NOME>` (um arquivo por segredo, lidos por
  `ops/env.py::secret`). `.env` não versionado; `.env.example` é o molde.

Comandos úteis: `seed_demo`, `issue_platform_invitation`,
`create_superadmin`, `install_exam_template`, `import_catalog`,
`sync_tuss`, `import_cmed`, `testar_email`, `prepare_recovery`,
`verify_physician`.

`import_cmed` traz a lista de medicamentos da Anvisa (XLSX, ~12 MB) e roda
**no worker**, que é de quem é o trabalho externo (§2). `--dry-run` lê e
conta sem gravar, que é o que se roda quando a CMED publica um arquivo novo.

## 7. Verificação (o que substitui os testes)

Roteiros em `checks/`, rodados dentro do contêiner. A bateria inteira,
ou só os que interessam:

```bash
docker compose exec app python manage.py rodar_roteiros            # todos
docker compose exec app python manage.py rodar_roteiros planos landing
docker compose exec app python manage.py rodar_roteiros --listar
```

`rodar_roteiros` dá uma linha por roteiro, imprime a saída só de quem
falhou e sai com código 1 se algum falhar — é o que um CI chamaria. Ele lê
`checks/` **de dentro da imagem**; enquanto se escreve um roteiro novo,
continue empurrando o arquivo do disco pela entrada padrão, que é o que
vale na hora:

```bash
docker compose exec -T app python manage.py shell < checks/check_planos.py
```

Cada roteiro **tenta quebrar** o comportamento, imprime seção por seção e
sai com código 1 listando as falhas. Os mais relevantes:

| Roteiro | Cobre |
| --- | --- |
| `check_landing.py` | página de vendas: limites vêm do catálogo, preço fecha a conta, lead não se perde com SMTP fora, campo-armadilha, relay aberto, limite por IP |
| `check_planos.py` | limites do plano nas seis portas, override, rebaixamento |
| `check_isolation.py` | vazamento entre inquilinos |
| `check_roles.py`, `check_matrix.py` | matriz de permissão |
| `check_prontuario.py`, `check_roteiro.py` | prontuário e roteiro de exame |
| `check_texto_livre.py` | os dois tipos de atendimento, a cópia entre eles e a grade por abertura/fechamento |
| `check_mensageria.py`, `check_email.py` | outbox, entrega, reconciliação |
| `check_entrega_documento.py` | a entrega que não pode derrubar a tela: a mensagem de SMS cabe num segmento **com o link real**, a de e-mail continua completa, **o e-mail sai mesmo com o SMS quebrado**, falha inesperada vira entrega marcada e não exceção, a entrega sai pelo worker e o primeiro envio é automático por evento |
| `check_links_de_mensagem.py` | **todo link que sai numa mensagem abre**: nenhum e-mail é enfileirado antes do commit (transação desfeita não manda nada), o link do documento é aberto de verdade, o reenvio troca o link e revoga o anterior, e a verificação de e-mail, o convite e o descadastro respondem |
| `check_chatbot.py`, `check_ia_padrao.py` | IA e chat |
| `check_mensagens.py` | chat da equipe: conversa única por par, participação, fronteira entre clínicas, contador não lido, envio congelado na clínica suspensa |
| `check_receitas.py` | catálogo CMED e a busca, documento sem atendimento, emissão em papel, e o QR só em documento assinado |
| `check_mobile.py` | aderência ao celular: o bloco de toque existe e pergunta por `pointer: coarse`, campos a 16px, alvo de 40px, tabela embrulhada, calha responsiva |
| `check_backup.py` | restaurador carrega, trava única entre backup e arquivo morto, unidades do systemd executáveis |
| `check_mensagem_clinica.py` | as duas portas do rodapé do menu: qualquer vínculo escreve, a mensagem fica na clínica de quem escreveu, o texto não vai para a trilha, e o console lê as duas com MFA |
| `check_perimetro.py` | a borda: agente de captura sem CSRF, desidentificação sem comer palavra, IP do visitante atrás do proxy |
| `check_imutabilidade.py` | o que não pode mudar: prontuário finalizado (cópia da consulta anterior e admin), salvamento concorrente, trilha de auditoria, guarda de 20 anos, contador de tentativas do link |
| `check_ia_plano.py` | a IA segue o plano: a capacidade vetada, a autorização do job recusando, o resumo automático que sai por `return` em vez de derrubar o evento, o chat em 404 com o link sumindo junto, e a tela de configuração que explica sem deixar gravar |
| `check_contrato.py` | contrato de adesão: cláusulas obrigatórias, aceite obrigatório no cadastro, prazos gravados, via por e-mail, isolamento e o hash que denuncia texto editado sem troca de versão |
| `check_exportacao.py` | exportação do acervo: MD e JSON com o conteúdo prometido, quem pode pedir cada um, o POST que tenta furar a matriz, o arquivo escrito pelo worker com a extensão certa, e a versão do produto |
| `check_fuso.py` | o dia que o produto enxerga é o da clínica: varre o repositório inteiro proibindo `timezone.now().date()` e `date.today()` (que devolvem o dia em UTC), e confere que a agenda marca como hoje o dia de Brasília |
| `check_importacao.py` | migração de cadastro: ninguém nasce autorizado a receber mensagem, o responsável homônimo não vira contato extra, a importação pode ser repetida, CPF repetido não derruba nada e ficha daqui não é sobrescrita |
| `check_nome_caixa_alta.py` | o nome numa forma só: os quatro caminhos de criação, o acento que permanece, a busca que continua achando e o nome do parente que não é reescrito |
| `check_mes_e_estatisticas.py` | a visão de mês não mente sobre o passado: `done` para quem foi atendido, `past` para o que ficou vago, **sem mexer na oferta de vaga**; e as estatísticas somam pela mesma grade, separando atendido de falta e de cancelado |
| `check_idioma.py` | **tudo que o usuário lê está em português**: varre `messages.*`, `ValidationError`, `label=`, `help_text=` e as exceções que as views mostram com `str(exc)`; deixa passar log e ferramenta de operação, de propósito. A lista de exceções era escrita à mão e por isso envelhecia — a seção 5 **procura** no código quem devolve `str(exc)` ao usuário e reprova quem não estiver na lista, que foi como três mensagens em inglês apareceram |
| `check_paginacao.py` | paginação: **cria volume antes de olhar** (sem passar de uma página, o bloco nem é renderizado e o roteiro não testa nada), a primeira e a última página abrem, e número de página inválido não vira erro 500 |
| `check_csp.py` | política de conteúdo: `script-src` sem `unsafe-inline`, nonce novo a cada resposta e igual ao do HTML, a varredura dos templates atrás de `onclick` e de `<script>` sem nonce, o modo de relatório como padrão, e o coletor com teto por IP |
| `check_declaracao.py` | declaração de comparecimento: o papel **não** carrega CID nem diagnóstico, nega ser atestado com todas as letras, ver não emite (só o POST registra), horário invertido não vira papel, e a fronteira entre clínicas |
| `check_evolucao.py` | série temporal: o eixo do tempo proporcional à data real, a escala usando o próprio domínio, a incompleta fora da linha, unidades diferentes como séries diferentes, e a tela que mostra o número sem interpretá-lo |
| `check_mfa_reconfirmacao.py` | reconfirmar o segundo fator **sem derrubar a sessão**: a tela existe, o `next` volta para onde se estava e não sai do host, código errado não carimba a hora, a tela de certificados pede o código **antes** da senha, e envio cancelado não deixa botão girando |
| `check_relatorio_ia.py` | relatório escrito pela IA: o marcador de desidentificação que não pode chegar ao papel, a identificação que não entra no contexto, o diagnóstico refutado que não vira doença, o recorte declarado, a ponte que cria **rascunho** e não documento emitido, e o texto editado na tela sendo o que vai assinado |
| `check_por_cid.py` | busca de paciente por diagnóstico: a fronteira (a secretária e o gestor não abrem a tela), o código por prefixo com o ponto dispensável, o diagnóstico anotado sem código, e o refutado que não volta — vale a última palavra sobre cada código |
| `check_retorno.py` | retorno programado: meses de calendário sem estourar o fim do mês, um retorno por atendimento, a janela de 20 dias com o dia perdido recuperado, o `notified_at` que barra o segundo e-mail, a recusa do contato respeitada, a redação de cuidado e não de captação, e a fila da secretária |
| `check_portal_retorno.py` | consulta recente no portal: a fronteira dos 180 dias, a escolha do médico vencendo a da clínica, as três portas, sessão aberta antes de ligar a regra, e a tela citando as duas normas do CFM com a redação que consta nelas |
| `check_instalacao.py`, `check_super.py` | instalação limpa e console |

Ao mexer em preço ou plano, `check_landing.py` e `check_planos.py` são
obrigatórios — o primeiro confere que o anual é o mensal × 12 e que o
número anunciado é o do catálogo.

## 7-A. Versão do produto

**`base/version.py`.** `VERSION` é a versão do produto — o primeiro deploy
é a **1.0**. Não confundir com `RELEASE_ID`, que é o SHA do commit
publicado: aquele identifica um *build* e muda a cada publicação; este
identifica o *produto* e é o número que aparece num chamado de suporte,
numa nota de versão e num contrato.

Maior quando quebra algo para quem já usa; menor quando entra
funcionalidade sem quebrar. Correção sem funcionalidade nova não mexe em
nenhum dos dois — o `RELEASE_ID` já a identifica.

Aparece no rodapé do aplicativo e da página pública (`nd_versao`, do
processador de contexto), em `/instalacao/` ao lado do build, no retorno
do `operational_ping` e na saída do deploy. O módulo não importa nada de
propósito: `ops/deploy.py` roda no host, fora do Django.

## 7-B. Exportação do acervo

**`/app/reporting/acervo/`**, no menu de administração da clínica. É o que
cumpre a cláusula 13.1 do contrato de adesão — obter os dados em formato
de uso comum — e sai só em **Markdown e JSON**:

- **JSON** para levar a outro sistema: estrutura preservada, inclusive as
  listas (contatos, convênios) que não cabem numa célula.
- **Markdown** para ler: o cadastro vira uma ficha por paciente, e o
  prontuário vira um documento agrupado por paciente e em ordem de data,
  com o texto de cada anotação. Tabela com uma coluna de vinte mil
  caracteres é tecnicamente uma exportação e praticamente ilegível.

Reaproveita o motor de `reporting` inteiro: fila no worker, arquivo
privado com 0600, expiração em 24 h, trilha de auditoria.

**Quem pode.** A capacidade é declarada **por relatório**, em
`reporting/apps.py`, e conferida em `request_export` — não na view, porque
o nome do relatório chega pelo POST. O cadastro exige
`MANAGE_ORGANIZATION` (só o dono, que é a CONTRATANTE do contrato); o
acervo clínico exige `MANAGE_ORGANIZATION` **e** `READ_CLINICAL`, porque
um dono que não é médico não abre prontuário na tela e não pode baixar
todos num arquivo. Recusa entra na trilha como `reporting.export_denied`.

## 7-C. Consulta recente no portal

**`documents/portal_retorno.py`.** O portal público recebe pedido de
receita, relatório e exame — os três são ato médico. Duas normas do CFM
sustentam a recusa, e elas se encaixam:

- **Código de Ética Médica** (Res. CFM nº 2.217/2018), **art. 37**: é
  vedado prescrever "sem exame direto do paciente, salvo em casos de
  urgência ou emergência e impossibilidade comprovada de realizá-lo". O
  **parágrafo único** remete o atendimento a distância à regulamentação
  do CFM.
- **Res. CFM nº 2.314/2022, art. 6º, § 2º** — a regulamentação que o
  parágrafo único anuncia: consulta presencial com o médico assistente
  "em intervalos não superiores a **180 dias**".

**O prazo não é configurável, e isso é a decisão.** Ele é o da norma —
`PORTAL_RECENT_VISIT_DAYS = 180`, em dias e não em meses de calendário,
porque seis meses dão 181 a 184 dias e seriam mais permissivos que o texto
citado. Um prazo configurável faria a tela de bloqueio citar uma resolução
que diz 180 dias logo acima de um prazo que a contraria, com o paciente
lendo as duas coisas na mesma folha.

**O que se escolhe é barrar ou não:**

| Onde | Campo | Estados |
| --- | --- | --- |
| Identidade da clínica → portal | `ClinicProfile.patient_portal_requires_recent_visit` | sim / não (padrão **sim**) |
| Fila de solicitações do portal | `Membership.patient_portal_requires_recent_visit` | sim / não / **nulo** = seguir a clínica |

A escolha do médico que atendeu vence a da clínica — é dele a
responsabilidade do art. 37. Nulo é um terceiro estado, e é o que permite
o responsável mudar o padrão e a mudança valer para quem não se
manifestou. **Não barrar não impede ninguém de prescrever:** o pedido
chega à fila como qualquer outro, e a decisão continua do médico.

Conta **qualquer** atendimento, inclusive em rascunho — rascunho significa
que o médico abriu a ficha durante a visita. Confere em **três portas**:
identificação, abertura do formulário e envio; a do envio existe porque
entre abrir a sessão e enviar cabe o médico mudar a opção.

`check_portal_retorno` cobra a fronteira exata (180 passa, 181 não), a
precedência das escolhas, as três portas, e que a tela **cite as duas
normas com a redação que consta nelas** — inclusive uma asserção contra a
exceção inventada "emergência comunicada ao CRM", que o art. 37 não tem.

## 7-D. Chaves que se viram sem deploy

**`base.models.InstallationSettings`** — uma linha só, e a tela é
`/instalacao/operacao/` (superusuário com MFA). Duas chaves moram nela:

| Chave | O que faz |
| --- | --- |
| `ai_base_url_allowlist` | Endereços de API que a instalação libera **além** do catálogo, para provedor de IA próprio (Ollama, vLLM). Vazio = só o catálogo |
| `documents_gc_dry_run` | Ensaio da coleta semanal de arquivos apagados. `True` conta e registra sem apagar |

**O `.env` semeia, o banco decide.** `AI_BASE_URL_ALLOWLIST` e
`DOCUMENTS_GC_DRY_RUN` valem para criar a linha na primeira vez; depois
disso quem manda é o console, e mexer no `.env` não muda mais nada. A tela
diz isso com todas as letras — regra dessas, descoberta por tentativa,
custa uma madrugada.

**Por que no console e não só no `.env`.** Não é conveniência: é que
*desligar demorava*. Uma trava que só se solta editando arquivo, regerando o
runtime e republicando não serve de freio de emergência — e as duas são
exatamente isso.

**A assimetria é deliberada.** Voltar a coleta ao ensaio é **um clique**:
parar de apagar é a direção segura, e uma pergunta a mais ali custaria o
tempo que importa. Autorizar o apagamento exige digitar `APAGAR` e escrever
o motivo, que vai para a trilha — do outro lado há arquivo clínico que não
volta. `check_decisoes.py` cobra as duas direções.

## 8. Deploy

Docker Swarm, imagem publicada por SHA do commit, Traefik com Let's
Encrypt. `scripts/deploy.sh` → `ops/deploy.py`, com trava de execução.

- **Passo a passo do zero:** `docs/operations/primeiro-deploy.md`, e
  `scripts/setup_deploy.sh` para fazê-lo sozinho numa VPS limpa (retoma de
  onde parou; não reimplementa build/push/stack — chama `ops/deploy.py`).
- Mecanismo, rollback, backup/restauração (cifrado com `age`) e
  monitoramento: `docs/operations/`.
- `RELEASE_ID` é o SHA e entra no caminho dos estáticos
  (`/static/<sha>/`); `dev` no ambiente local.
- `SECURE_HSTS_SECONDS` começa em `0` **de propósito** — ligue só depois
  de o HTTPS estar comprovadamente funcionando; o navegador guarda a
  instrução e não há como voltar atrás.
- **`CSP_ENFORCE` começa em `False`**, pelo mesmo espírito e com uma
  diferença: a política sai como `Content-Security-Policy-Report-Only`, o
  navegador obedece normalmente e **avisa** em `/csp-report/` o que teria
  bloqueado. Leia o log (`csp:`) por algumas semanas de uso real antes de
  pôr `True`. Ao contrário do HSTS, **este dá para voltar**: `False` e
  republicar. Ver `base/csp.py` e `docs/homologation/csp.md`.

  A consequência prática para quem escreve tela: **nada de `onclick` nem
  de `<script>` sem nonce**. Atributo de evento não é coberto por nonce, e
  mantê-lo exigiria `unsafe-inline`, que desliga a proteção inteira. Os
  comportamentos vivem em `static/duralux/nd-inline.js` atrás de atributos
  `data-nd-*`; bloco `<script>` inline leva `nonce="{{ nd_csp_nonce }}"`.
  `check_csp.py` varre os templates e reprova quem esquecer.

## 9. Onde procurar o resto

- **`docs/ESTADO-ATUAL.md` — leia primeiro.** O retrato do sistema no dia
  em que entrou em uso real: o que está provado, o que está aberto, e as
  lições que custaram caro. É o arquivo que responde "onde estamos" a
  quem (ou ao que) chega agora.
- `PRD.md` — a especificação completa (matriz de permissão §4, roteiro de
  homologação §21).
- `docs/index.md` — índice da documentação técnica por sprint.
- `docs/governance/lgpd.md` — a matriz de tratamento (finalidade × base legal
  × medida técnica), operadores e transferência internacional, as medidas
  técnicas com o roteiro que verifica cada uma, e onde cada exigência
  jurídica ficou tratada. **Sem pendências desde 2026-09-21**: o contrato
  de adesão da advogada (§9) é o instrumento do art. 39, e o §6 registra a
  decisão do controlador de que nada ali bloqueia a operação.
- `docs/decisions.md` — decisões e pendências com dono e condição de
  liberação (P-02 VPS real e P-05 certificado real permanecem abertas;
  P-08 foi encerrada com a retirada da captura local; P-06 e P-07 foram resolvidas em
  2026-09-21 — a primeira pelo contrato de adesão da advogada, a segunda
  por decisão de escopo sobre o SNCR).
- `docs/specs/2026-09-12-planos-e-limites.md` — as dez decisões de plano,
  com a alternativa recusada.
- `design_system/design-system.html` — o tema Duralux real, servido
  localmente; `docs/design-system.md` cataloga os tokens. **O produto tem
  um tema só, o claro** — o escuro foi removido: um prontuário lido ao lado
  do paciente não ganhava nada com ele, e cada tela nova passava a ter duas
  versões para conferir.
