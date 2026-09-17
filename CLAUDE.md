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
todo `TenantModel` carrega `UNIQUE(tenant_id, id)` e os filhos referenciam
`(tenant_id, fk)` — ver `base/db.py::composite_tenant_foreign_key`. Uma
linha não consegue apontar para objeto de outro inquilino nem por bug de
aplicação.

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
| `tenancy` | `Tenant`, `Membership`, `ClinicProfile`, `Invitation`, `Lead`; **planos, limites e a matriz de permissão** |
| `patients` | `Patient`, contatos, convênio/`PatientCoverage`, numeração por clínica, foto |
| `catalogs` | CID-10 e espelho da TUSS (sincronizado semanalmente pelo worker), CEP dos Correios |
| `clinical` | `Encounter`, achados do exame, diagnósticos, medicações, resultados de exame e valores laboratoriais, aditamento |
| `exams` | motor do roteiro de exame em árvore (387 nós, YAML) e 14 escalas pontuadas |
| `scheduling` | agenda por médico, regras de disponibilidade, bloqueios, feriados |
| `documents` | anexos (com antivírus), documentos médicos, **assinatura PAdES** via pyHanko, verificação pública por QR, portal de solicitações, OCR, arquivo morto |
| `communications` | outbox de entrega (e-mail/SMS), links opacos com OTP, campanhas com consentimento, credenciais SMTP/SMS da clínica |
| `finance` | tabela de honorários com vigência, recebíveis, pagamentos, ajustes (tudo em `Decimal`) |
| `ai` | jobs de IA com revisão médica obrigatória, desidentificação, chat persistente com streaming (Redis Streams + SSE), catálogo de dez provedores |
| `notifications` | sino do usuário |
| `teamchat` | **mensagens internas da equipe** — janela flutuante ao lado do sino, conversa de duas pessoas, presença e entrega ao vivo (Redis Streams + SSE). Não é prontuário, e a tela diz isso |
| `audit` | trilha imutável (`record_audit_event`) |
| `reporting` | indicadores e exportações (CSV protegido contra injeção de fórmula, expiram em 24 h) |
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

## 6. Ambiente local

```bash
python -m ops.local_compose     # gera compose.yml e os env_files a partir do .env
docker compose up -d --build
docker compose exec app python manage.py migrate
docker compose exec app python manage.py seed_demo
```

- App em `http://localhost:8000`, via Traefik em `:8080`, caixa de e-mail
  do Mailpit em `http://localhost:8025`.
- `compose.yml` é **gerado** a partir de `docker-stack.yml` — edite o
  stack e regenere, não edite `compose.yml` à mão.
- Segredos ficam em `.secrets/<NOME>` (um arquivo por segredo, lidos por
  `ops/env.py::secret`). `.env` não versionado; `.env.example` é o molde.

Comandos úteis: `seed_demo`, `issue_platform_invitation`,
`create_superadmin`, `install_exam_template`, `import_catalog`,
`sync_tuss`, `testar_email`, `prepare_recovery`, `verify_physician`.

## 7. Verificação (o que substitui os testes)

Roteiros em `checks/`, rodados dentro do contêiner:

```bash
docker compose exec app python manage.py shell < checks/check_planos.py
docker compose exec app python manage.py shell < checks/check_landing.py
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
| `check_mensageria.py`, `check_email.py` | outbox, entrega, reconciliação |
| `check_chatbot.py`, `check_ia_padrao.py` | IA e chat |
| `check_mensagens.py` | chat da equipe: conversa única por par, participação, fronteira entre clínicas, contador não lido, envio congelado na clínica suspensa |
| `check_instalacao.py`, `check_super.py` | instalação limpa e console |

Ao mexer em preço ou plano, `check_landing.py` e `check_planos.py` são
obrigatórios — o primeiro confere que o anual é o mensal × 12 e que o
número anunciado é o do catálogo.

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
- `docs/decisions.md` — DEC-01..DEC-20 e as pendências P-01..P-10, com dono
  e condição de liberação (P-02 VPS real, P-05 certificado real, P-06/P-07
  responsáveis de LGPD, P-08 scanner real permanecem abertas).
- `docs/specs/2026-09-12-planos-e-limites.md` — as dez decisões de plano,
  com a alternativa recusada.
- `design_system/design-system.html` — o tema Duralux real, servido
  localmente; `docs/design-system.md` cataloga os tokens. **O produto tem
  um tema só, o claro** — o escuro foi removido: um prontuário lido ao lado
  do paciente não ganhava nada com ele, e cada tela nova passava a ter duas
  versões para conferir.
