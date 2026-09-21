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

**Regra de rede que explica muito código:** em produção o processo `app`
**não tem saída para a internet**; quem está na rede de egresso é o
worker. Por isso e-mail, SMS, IA e o espelho da TUSS saem sempre por
tarefa Celery — falar com um serviço externo dentro da requisição
funcionaria em desenvolvimento e travaria no timeout em produção. Ver
`communications/mail_backend.py` e o comentário de `EMAIL_BACKEND` em
`core/settings.py`.

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
| `patients` | `Patient`, contatos, convênio/`PatientCoverage`, numeração por clínica, foto |
| `catalogs` | CID-10, espelho da TUSS (sincronizado semanalmente pelo worker), **medicamentos da CMED/Anvisa** (26 mil apresentações, com a tarja) e CEP dos Correios |
| `clinical` | `Encounter` em dois tipos (`kind`: prontuário estruturado ou **texto livre**), achados do exame, diagnósticos, medicações, resultados de exame e valores laboratoriais, aditamento, cópia da consulta anterior |
| `exams` | motor do roteiro de exame em árvore (387 nós, YAML) e 14 escalas pontuadas |
| `scheduling` | agenda por médico, regras de disponibilidade, bloqueios, feriados |
| `documents` | anexos (com antivírus), documentos médicos, **assinatura PAdES** via pyHanko, verificação pública por QR, portal de solicitações, OCR, arquivo morto |
| `communications` | outbox de entrega (e-mail/SMS), links opacos com OTP, campanhas com consentimento, credenciais SMTP/SMS da clínica |
| `finance` | tabela de honorários com vigência, recebíveis, pagamentos, ajustes (tudo em `Decimal`) |
| `ai` | jobs de IA com revisão médica obrigatória, desidentificação, chat persistente com streaming (Redis Streams + SSE), catálogo de dez provedores |
| `notifications` | sino do usuário |
| `teamchat` | **mensagens internas da equipe** — janela flutuante ao lado do sino, conversa de duas pessoas, presença e entrega ao vivo (Redis Streams + SSE). Não é prontuário, e a tela diz isso |
| `audit` | trilha imutável (`record_audit_event`) |
| `reporting` | indicadores e **exportação do acervo** (cadastro e prontuário em Markdown e JSON); CSV protegido contra injeção de fórmula, tudo expira em 24 h |
| `integrations` | captura por scanner, antivírus, CEP, TUSS |
| `events` | outbox de eventos de domínio com dispatcher idempotente e múltiplos consumidores por tópico |
| `ops` | deploy, backup/restauração, saúde, console do superadministrador, geração do compose local |

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
**no worker** — só ele alcança a internet. `--dry-run` lê e conta sem
gravar, que é o que se roda quando a CMED publica um arquivo novo.

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
| `check_chatbot.py`, `check_ia_padrao.py` | IA e chat |
| `check_mensagens.py` | chat da equipe: conversa única por par, participação, fronteira entre clínicas, contador não lido, envio congelado na clínica suspensa |
| `check_receitas.py` | catálogo CMED e a busca, documento sem atendimento, emissão em papel, e o QR só em documento assinado |
| `check_mobile.py` | aderência ao celular: o bloco de toque existe e pergunta por `pointer: coarse`, campos a 16px, alvo de 40px, tabela embrulhada, calha responsiva |
| `check_backup.py` | restaurador carrega, trava única entre backup e arquivo morto, unidades do systemd executáveis |
| `check_mensagem_clinica.py` | as duas portas do rodapé do menu: qualquer vínculo escreve, a mensagem fica na clínica de quem escreveu, o texto não vai para a trilha, e o console lê as duas com MFA |
| `check_perimetro.py` | a borda: agente de captura sem CSRF, desidentificação sem comer palavra, IP do visitante atrás do proxy |
| `check_imutabilidade.py` | o que não pode mudar: prontuário finalizado (cópia da consulta anterior e admin), salvamento concorrente, trilha de auditoria, guarda de 20 anos, contador de tentativas do link |
| `check_contrato.py` | contrato de adesão: cláusulas obrigatórias, aceite obrigatório no cadastro, prazos gravados, via por e-mail, isolamento e o hash que denuncia texto editado sem troca de versão |
| `check_exportacao.py` | exportação do acervo: MD e JSON com o conteúdo prometido, quem pode pedir cada um, o POST que tenta furar a matriz, o arquivo escrito pelo worker com a extensão certa, e a versão do produto |
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

## 9. Onde procurar o resto

- `PRD.md` — a especificação completa (matriz de permissão §4, roteiro de
  homologação §21).
- `docs/index.md` — índice da documentação técnica por sprint.
- `docs/governance/lgpd.md` — a matriz de tratamento (finalidade × base legal
  × medida técnica), operadores e transferência internacional, as medidas
  técnicas com o roteiro que verifica cada uma, e onde cada exigência
  jurídica ficou tratada. **Sem pendências desde 2026-09-21**: o contrato
  de adesão da advogada (§9) é o instrumento do art. 39, e o §6 registra a
  decisão do controlador de que nada ali bloqueia a operação.
- `docs/decisions.md` — DEC-01..DEC-21 e as pendências P-01..P-10, com dono
  e condição de liberação (P-02 VPS real, P-05 certificado real, P-08
  scanner real permanecem abertas; P-06 e P-07 foram resolvidas em
  2026-09-21 — a primeira pelo contrato de adesão da advogada, a segunda
  por decisão de escopo sobre o SNCR).
- `docs/specs/2026-09-12-planos-e-limites.md` — as dez decisões de plano,
  com a alternativa recusada.
- `design_system/design-system.html` — o tema Duralux real, servido
  localmente; `docs/design-system.md` cataloga os tokens. **O produto tem
  um tema só, o claro** — o escuro foi removido: um prontuário lido ao lado
  do paciente não ganhava nada com ele, e cada tela nova passava a ter duas
  versões para conferir.
