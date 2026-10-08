# NeuroDoc

Prontuário eletrônico e gestão para consultório médico, com o exame
neurológico estruturado que a neurologia e a neurocirurgia exigem — e com
agenda, receita, documento assinado digitalmente, portal do paciente e
financeiro que servem a **qualquer especialidade**.

Django monolítico modular, SSR com Django Templates, PostgreSQL como fonte
de verdade clínica e Celery para trabalho pesado. Multi-inquilino: uma
instalação, várias clínicas.

| | |
| --- | --- |
| **Versão do produto** | 1.8.3 "o que faltava para vender" (`base/version.py`) |
| **Produção** | <https://neurodoc.app.br> — em uso real desde 02/10/2026 |
| **Verificação** | 96 roteiros em `checks/`, nenhuma falha |
| **Stack** | Python 3.14 · Django 6.1 · PostgreSQL 17 · Celery · RabbitMQ · Redis · Traefik · Docker Swarm |
| **Repositório** | privado |

> **Leia antes de mexer:** [`CLAUDE.md`](CLAUDE.md) é o mapa do sistema e as
> convenções da casa; [`docs/ESTADO-ATUAL.md`](docs/ESTADO-ATUAL.md) é o
> retrato de onde o sistema está, com o que está provado e o que está
> aberto. Os dois respondem mais rápido do que ler o código.

---

## Versão e histórico

`VERSION` em [`base/version.py`](base/version.py) identifica o **produto**;
`RELEASE_ID` é o SHA do commit publicado e identifica um **build**. São
dois números com trabalhos diferentes: o SHA muda em toda publicação e
entra no caminho dos estáticos; a versão é o que aparece num chamado de
suporte, numa nota e num contrato.

**Regra de incremento.** Funcionalidade compatível avança a versão menor
(1.1, 1.2…). Mudança incompatível avançaria a maior. Correção sem
funcionalidade nova **não** mexe em nenhuma das duas — o `RELEASE_ID` já
identifica o build exato; a terceira casa só aparece quando é preciso
distinguir, num chamado de suporte, quem já tem a correção de quem ainda vê
o defeito.

| Versão | Data | Nome | O que entrou |
| --- | --- | --- | --- |
| **1.8.3** | 2026-10-07 | o que faltava para vender | **Aviso de horário não nasce de evento velho.** Ao entrar no ar, o consumidor novo encontrou 48 eventos de agendamento que estavam pendentes desde sempre — porque ninguém consumia aquele tópico — e avisou sobre todos: dez e-mails de madrugada sobre consultas já realizadas ou canceladas, quatro deles a pacientes reais. Agora o aviso ignora evento com mais de 6 h, consulta que já aconteceu, e fato que o estado atual contradiz. |
| **1.8.2** | 2026-10-07 | o que faltava para vender | O dia da agenda com **intervalo de almoço** passava a dizer "fechado" assim que a última vaga era preenchida — e os pacientes já marcados sumiam da visão de mês. O rótulo saía de "há célula bloqueada e nenhuma livre", o que valia quando só feriado bloqueava célula; o almoço bloqueia uma. Agora "fechado" é o dia **inteiro** bloqueado, e nada menos. |
| **1.8.1** | 2026-10-07 | o que faltava para vender | Os três defeitos do primeiro teste real da 1.8: remover uma grade **publicada no mesmo dia** devolvia erro 500; a pausa de almoço fechava a célula que tocava em vez de **partir o dia**, e a tarde voltava 20 min depois do fim do intervalo; e a naturalidade, no celular, vinha na ordem errada e sem autocomplete — o `<datalist>` nativo não abre em boa parte dos navegadores móveis. |
| **1.8** | 2026-10-07 | o que faltava para vender | **Intervalo pontual** na agenda (o almoço, em horário diferente a cada dia) recortando a grade, os horários livres e a validação da reserva. **Naturalidade** do paciente, com os 5.571 municípios do IBGE no autocomplete e texto livre para quem nasceu fora. Os **dados de cadastro numa gaveta** durante o atendimento, sem sair da evolução (Alt+D). **Aviso automático** ao marcar, remarcar e cancelar, com o endereço e o telefone no lugar do nome da clínica. **Nome fantasia** editável pelo próprio inquilino. |
| **1.7.1** | 2026-10-07 | o padrão da instalação | Dois defeitos achados ao **provar** que o SMS funciona, em vez de concluir: a confirmação de entrega nunca era lida — 17 mensagens ficaram "sem confirmação" para sempre, inclusive uma que a operadora entregou — e o botão de testar a chave do SMSDEV reprovava chave boa, por consultar saldo no endereço de envio. Os dois eram código escrito contra esquema suposto; agora conferidos contra conta viva, o que encerra a pendência **P-03**. |
| **1.7** | 2026-10-06 | o padrão da instalação | O **provedor de IA padrão** passa a ser trocado no console do superadministrador, com verificação que pergunta ao provedor se o modelo ainda existe — ele estava apontando, desde 26/08, para um modelo aposentado que respondia `410 Gone`, e trocá-lo exigia republicar. A **confirmação de horário** passa a sair pelo worker: saía da requisição, onde o secret do SMS não existe, e por isso nunca chegou para a clínica sem chave própria. Recusa do provedor deixa de virar "tente novamente" quando repetir não resolve, e canal indisponível deixa de ser registrado como "sem contato cadastrado". |
| **1.6.2** | 2026-10-05 | o que a tela não mostrava | A leitura de laudo pela IA era descartada inteira quando um campo de texto voltava como lista vazia — trinta e um analitos corretos no lixo por causa do campo que diz "não ficou nada ilegível". A **forma** que o modelo devolve passa a ser normalizada; o **conteúdo** segue sob as mesmas guardas. O esquema vai junto do pedido, e a recusa passa a ser explicada em português, com o detalhe técnico gravado sem nenhum valor do laudo. |
| **1.6.1** | 2026-10-05 | o que a tela não mostrava | Quem atende em **duas clínicas** trocava de organização e seguia vendo o logotipo da anterior. Não era vazamento entre inquilinos — o servidor sempre mandou a imagem certa; era o cache do navegador, que guardava a mesma URL por cinco minutos porque a resposta pedia. Agora a resposta é revalidada, com validador que carrega o inquilino. |
| **1.6** | 2026-10-04 | o que a tela não mostrava | Adendo no atendimento de **texto livre** finalizado (o servidor sempre aceitou; a tela não oferecia). Campo **Impressões** no estruturado, na aba de hipóteses — existia no modelo e nenhuma aba o desenhava, a ponto de o que vinha da consulta anterior ser gravado invisível. Botão **Trazer tudo** da consulta anterior, numa transação só. Cada envio volta para a **aba de onde saiu**. |
| **1.5** | 2026-10-03 | encontrável | SEO completo a partir de um catálogo único (`base/seo.py`): título, descrição, canônica, `robots`, `sitemap.xml` e dados estruturados. Família de ícones da marca gerada de uma geometria só. Cartão de compartilhamento. Seção que responde ao médico de outra especialidade. Corrige o `<title>` que nunca chegava à página porque bloco não atravessa `{% include %}`. |
| **1.4** | 2026-10-01 | quem assina é o autor | Relatório do paciente escrito pela IA, revisado e assinado pelo médico. |
| **1.3.1** | 2026-10-01 | o mês que passou | O horário marcado também se clica na visão de mês; o dia vencido para de dizer "lotado". |
| **1.3** | 2026-10-01 | o mês que passou | Visão de mês da agenda e estatísticas, pela mesma grade, separando atendido de falta e de cancelado. |
| **1.2.3** | 2026-10-01 | migração | Tudo que o usuário lê passa a estar em português (varredura, não lista). |
| **1.2.2** | 2026-10-01 | migração | A busca de paciente devolvia a clínica inteira. |
| **1.2.1** | 2026-10-01 | migração | A lista de pacientes quebrava a partir da segunda página. |
| **1.2** | 2026-10-01 | migração | Nome do paciente numa forma só (caixa alta, gravada) e migração de cadastro de outro sistema — 2.223 fichas. |
| **1.1.1** | 2026-09-30 | seguimento | Das 21h à meia-noite, "hoje" era amanhã em quinze lugares (fuso). |
| **1.1** | 2026-09-30 | seguimento | Retorno programado, busca de paciente por CID, série temporal em gráfico, declaração de comparecimento, CSP em modo de relatório. |
| **1.0** | 2026-09-21 | primeiro deploy | Primeira publicação: prontuário, roteiro de exame, escalas, agenda, documentos assinados, comunicações, financeiro, IA com revisão médica, exportação do acervo, LGPD sem pendências. |

Cada release publicada deve ter um registro em
[`docs/releases/`](docs/releases/) com SHA, evidência de homologação e
responsável — é a seção 18.6 do PRD, e a ordem importa: o registro entra
**antes** de `NEURODOC_RELEASE_APPROVED=True`. As correções de terceira
casa (1.6.1, 1.7.1, 1.8.1…) são registradas no arquivo da versão menor a
que pertencem, ou em arquivo próprio quando a correção pede a sua própria
homologação.

---

## O que o sistema faz

**Clínico.** Atendimento em dois tipos — prontuário estruturado e texto
livre —, roteiro de exame neurológico em árvore (387 nós, YAML), 14 escalas
pontuadas, medicações, hipóteses em CID-10, resultados de exame com valores
laboratoriais, cópia revisada da consulta anterior, série temporal em
gráfico, busca de paciente por diagnóstico. Durante o atendimento, os
dados de cadastro ficam numa **gaveta** (`Alt+D`), sem sair da evolução.
Prontuário finalizado é imutável: correção é **adendo**, com autor e data,
nos dois tipos.

**Documentos.** Receita simples e de controle especial (duas vias, quadro
da Portaria 344/98), laudo, atestado, declaração de comparecimento, pedido
de exame e encaminhamento — assinados em **PAdES** com o certificado do
próprio médico e verificáveis publicamente por QR, sem conta. Catálogo
CMED/Anvisa com 26 mil apresentações no autocomplete.

**Operação do consultório.** Agenda por médico com regras de
disponibilidade, **intervalos pontuais** (o almoço), bloqueios, feriados e
retorno programado; **aviso automático** ao paciente ao marcar, remarcar e
cancelar, com o endereço e o telefone da clínica; cadastro com
**naturalidade** (5.571 municípios do IBGE no autocomplete); portal
público onde o paciente pede receita sem criar conta; outbox de entrega
por e-mail e SMS com links opacos, OTP e confirmação de entrega lida do
provedor; convênios, honorários com vigência,
recebíveis e pagamentos (tudo em `Decimal`); exportação do acervo em
Markdown e JSON.

**IA.** Jobs com revisão médica obrigatória, desidentificação local antes
de sair, chat persistente com streaming (Redis Streams + SSE), catálogo de
dez provedores e a possibilidade de a clínica apontar o próprio contrato.
O **provedor padrão** da instalação é trocado no console, com verificação
de que o modelo ainda existe. Relatório do paciente redigido pela IA e
assinado pelo médico; leitura de laudo anexado com a forma normalizada e
o conteúdo sob guarda. O apoio clínico é recurso de plano, vetado em duas
camadas independentes.

**O que é da clínica.** E-mail, SMS e IA seguem a mesma cadeia — a clínica
que configurou o seu usa o seu; a que desligou volta ao padrão da
instalação. O nome fantasia é editado pela própria clínica; razão social e
CNPJ continuam vindo do convite.

**Plataforma.** Multi-inquilino com três camadas de autorização, trilha de
auditoria imutável, backup cifrado com `age` e cópia externa, console de
superadministrador, central de ajuda pública e página de vendas.

---

## Arquitetura

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
worker tem a chave de SMTP (só a ele o segredo é entregue) e pode tentar de
novo quando o provedor falha; uma requisição web espera o timeout com o
usuário olhando.

**Autorização, em três camadas** — e vale conhecer as três antes de mexer
em qualquer view:

1. `tenancy/middleware.py` resolve a organização da sessão, monta
   `request.access_context` e devolve 404 a quem não tem vínculo;
2. `tenancy/context.py` é a dataclass imutável por requisição, reconstruída
   do banco a cada vez — vínculo revogado para de autorizar imediatamente;
3. `tenancy/permissions.py` é a matriz do PRD §4 em código. As views e os
   templates perguntam `ctx.can(Capability.READ_CLINICAL)`, **nunca**
   `'doctor' in roles`.

No banco, o isolamento é reforçado por chave estrangeira composta
(`UNIQUE(tenant_id, id)` + FK em `(tenant_id, fk)`), hoje aplicada em
`clinical` e `teamchat`.

### Apps

| App | O que guarda / faz |
| --- | --- |
| `core` | settings, urls, asgi, celery |
| `base` | primitivas (`TenantModel`, cripto, logging com redação), página de vendas, central de ajuda e **SEO** (`seo.py`) |
| `accounts` | `User` (e-mail como login), MFA TOTP, códigos de recuperação, CRM do médico |
| `tenancy` | `Tenant`, `Membership`, convites, leads, **planos, limites, matriz de permissão e contrato de adesão** |
| `patients` | ficha, contatos, convênio, numeração por clínica, naturalidade, forma canônica do nome, migração de cadastro |
| `catalogs` | CID-10, TUSS, CMED/Anvisa, municípios do IBGE, CEP |
| `clinical` | atendimento nos dois tipos, exame, diagnósticos, medicações, adendo, cópia da consulta anterior, série temporal |
| `exams` | motor do roteiro em árvore e as 14 escalas |
| `scheduling` | agenda, disponibilidade, intervalos pontuais, bloqueios, retorno programado, declaração, estatísticas |
| `documents` | anexos com antivírus, documentos médicos, assinatura PAdES, QR público, portal de solicitações, OCR |
| `communications` | outbox, links opacos com OTP, aviso de horário, campanhas com consentimento, credenciais da clínica |
| `finance` | honorários com vigência, recebíveis, pagamentos, ajustes |
| `ai` | jobs com revisão médica, desidentificação, chat com streaming, relatório do paciente, leitura de laudo |
| `notifications` · `teamchat` | sino do usuário · mensagens internas da equipe |
| `audit` · `events` | trilha imutável · outbox de eventos com dispatcher idempotente |
| `reporting` · `integrations` · `ops` | indicadores e exportação · antivírus/CEP/TUSS · deploy, backup, saúde, console (com as chaves de **Operação**) |

O detalhe de cada decisão está em [`CLAUDE.md`](CLAUDE.md) §4 e no
[`PRD.md`](PRD.md).

---

## Ambiente local

```bash
python -m ops.local_compose     # gera compose.yml e os env_files a partir do .env
docker compose up -d --build    # o próprio `app` migra na subida
docker compose exec app python manage.py seed_demo
docker compose exec celery_worker python manage.py import_cmed
docker compose exec celery_worker python manage.py import_municipios
```

- App em `http://localhost:8000`, via Traefik em `:8080`, caixa de e-mail do
  Mailpit em `http://localhost:8025`.
- **Não rode `manage.py migrate` à mão.** A conexão padrão é `neurodoc_app`,
  que não tem DDL. Quem migra é o próprio `app` ao subir
  (`bootstrap_release` → `ops/runtime.py::prepare_release`), pela conexão
  `migrations`, com `neurodoc_owner` e uma trava.
- `compose.yml` é **gerado** a partir de `docker-stack.yml` — edite o stack
  e regenere.
- Segredos ficam em `.secrets/<NOME>`, um arquivo por segredo. `.env` não é
  versionado; `.env.example` é o molde.
- `import_cmed` não vem da semeadura e baixa ~12 MB da Anvisa. Sem ele,
  `check_receitas` reprova numa instalação nova. `import_municipios` traz
  os municípios do IBGE para a naturalidade; sem ele o autocomplete fica
  mudo e o campo continua aceitando texto livre.

Comandos úteis: `seed_demo`, `issue_platform_invitation`,
`import_municipios`, `create_superadmin`, `install_exam_template`,
`import_catalog`, `sync_tuss`, `import_cmed`, `testar_email`,
`prepare_recovery`, `verify_physician`.

---

## Verificação

**Não há suíte de testes automatizados** (DEC-20). O substituto são os
**roteiros** em [`checks/`](checks/): cada um tenta quebrar um
comportamento, imprime seção por seção e sai com código 1 listando as
falhas.

```bash
docker compose exec app python manage.py rodar_roteiros            # todos
docker compose exec app python manage.py rodar_roteiros planos landing
docker compose exec app python manage.py rodar_roteiros --listar
```

`rodar_roteiros` lê `checks/` **de dentro da imagem** — ao escrever um
roteiro novo, reconstrua (`docker compose up -d --build app`) ou empurre o
arquivo pela entrada padrão:

```bash
docker compose exec -T app python manage.py shell < checks/check_planos.py
```

O que esses roteiros aprenderam a fazer, e que vale copiar ao escrever o
próximo:

- **lista escrita à mão envelhece.** As guardas de fuso, de idioma, de
  chaves do runtime e da política de conteúdo nasceram como listas e
  falharam pelo mesmo motivo — não cobriam o arquivo que ninguém lembrou de
  acrescentar. Viraram varreduras do repositório;
- **um teste que não falha com o defeito presente não é teste.** Roteiro de
  paginação sem volume não renderiza o bloco que vem conferir; asserção que
  casa com ícone decorativo passa com a tela quebrada.

---

## Deploy

Docker Swarm, imagem publicada por SHA do commit, Traefik com Let's
Encrypt. **Build e deploy rodam na VPS, nunca localmente.**

```bash
ssh deploy@<host> "cd /srv/neurodoc && git pull --ff-only \
  && bash scripts/deploy.sh --check \
  && (setsid nohup bash scripts/deploy.sh > /tmp/deploy.log 2>&1 < /dev/null &)"
```

- Passo a passo do zero: [`docs/operations/primeiro-deploy.md`](docs/operations/primeiro-deploy.md);
  `scripts/setup_deploy.sh` faz isso sozinho numa VPS limpa e retoma de onde
  parou.
- Mecanismo, rollback, backup/restauração (cifrado com `age`) e
  monitoramento: [`docs/operations/`](docs/operations/).
- `SECURE_HSTS_SECONDS` começa em `0` **de propósito** — ligue só depois de
  o HTTPS estar comprovadamente funcionando; o navegador guarda a instrução
  e **não há como voltar atrás**.
- `CSP_ENFORCE` começa em `False`, pelo mesmo espírito e com uma diferença:
  a política sai como `Content-Security-Policy-Report-Only`, o navegador
  obedece normalmente e **avisa** em `/csp-report/`. Este dá para voltar.

---

## Antes de editar

As convenções inteiras estão em [`CLAUDE.md`](CLAUDE.md) §1. As cinco que
mais pegam quem chega:

1. **Produto, comentários novos e mensagens de commit em português** —
   inclusive **mensagem de erro**, que é justamente a que escapa, porque só
   aparece no caminho que deu errado. `check_idioma.py` varre.
2. **Comentário explica *por quê*, nunca *o quê*.** O estilo da casa é um
   bloco no topo do módulo dizendo qual erro aquela escolha impede, com a
   alternativa recusada e o motivo. Veja `tenancy/plans.py` ou
   `base/seo.py` e imite.
3. **Nunca pergunte a data ao relógio do processo.** O contêiner roda em
   `Etc/UTC` e o produto em `America/Sao_Paulo`: entre 21h e meia-noite,
   `timezone.now().date()` responde **amanhã**. Use `localdate()` e
   `localtime()`; `check_fuso.py` varre o repositório e reprova.
4. **Números do negócio moram em código, não no banco** — planos, limites e
   preços em `tenancy/plans.py`, para que mudá-los seja um commit com autor
   e data. `None` significa **ilimitado**; nunca um número grande. Preço em
   centavos, nunca em `float`.
5. **Nada de `onclick` nem de `<script>` sem nonce.** Atributo de evento não
   é coberto por nonce, e mantê-lo exigiria `unsafe-inline`, que desliga a
   proteção inteira. Os comportamentos vivem em
   `static/duralux/nd-inline.js` atrás de atributos `data-nd-*`;
   `check_csp.py` varre os templates.

---

## Documentação

| Onde | O quê |
| --- | --- |
| [`CLAUDE.md`](CLAUDE.md) | **o mapa** — convenções, topologia, apps, planos, verificação, deploy |
| [`docs/ESTADO-ATUAL.md`](docs/ESTADO-ATUAL.md) | **leia primeiro** — o retrato de hoje: o que está provado, o que está aberto, as lições que custaram caro |
| [`PRD.md`](PRD.md) | a especificação completa (matriz de permissão §4, roteiro de homologação §21) |
| [`docs/index.md`](docs/index.md) | índice da documentação técnica, publicada em `/technical-docs/` (MFA) |
| [`docs/decisions.md`](docs/decisions.md) | decisões (DEC-xx) e pendências (P-xx) com dono e condição de liberação |
| [`docs/governance/lgpd.md`](docs/governance/lgpd.md) | matriz de tratamento, operadores, medidas técnicas e o roteiro que verifica cada uma |
| [`docs/operations/`](docs/operations/) | deploy, rollback, backup, cópia externa, monitoramento |
| [`docs/homologation/`](docs/homologation/) | homologação por entrega — é onde mora o "por que ficou assim" |
| [`docs/releases/`](docs/releases/) | registro de cada release publicada (PRD §18.6) |

**Documentos de raiz que são históricos, não correntes:**
`DEPLOY.md`, `DEPLOY_CHECKLIST.md`, `PRE_DEPLOY_AUDIT.md` e `TEST_MATRIX.md`
são artefatos do período anterior ao primeiro deploy. Nada no código ou nos
scripts os referencia — eles referenciam uns aos outros. O que vale hoje
está em `docs/operations/` e em `checks/`.

---

## O que está aberto

Não se repete aqui, de propósito: lista copiada envelhece e passa a
discordar do original. O retrato está em
[`docs/ESTADO-ATUAL.md`](docs/ESTADO-ATUAL.md) §3, e as pendências com dono
e condição de liberação em [`docs/decisions.md`](docs/decisions.md). Antes
de mexer em rede, em isolamento entre clínicas ou na imagem do banco, leia
os dois.

---

## Licença e titularidade

`LICENSE` (MIT) · © 2026 Fernando Freua.

**A `LICENSE` contradiz o contrato.** A cláusula 16 do contrato de adesão
afirma que o código-fonte pertence ao contratado e que o contrato "não
transfere sua propriedade intelectual"; um arquivo MIT concede a qualquer
um o direito de copiar, modificar, distribuir e sublicenciar. Com o
repositório privado nada foi concedido a ninguém, mas a contradição vira
real no dia em que o código for compartilhado com um terceiro. Trocar por
uma nota proprietária é decisão do titular.

O contrato de adesão que vale para quem usa o produto está em
[`tenancy/contract.py`](tenancy/contract.py), redigido pela **Dra. Karina
Albuquerque Freua, OAB/SP nº 450.476**. O texto mora em código pelo mesmo
motivo dos preços: mudá-lo é um commit com autor e data — e **nunca se
edita uma versão já aceita** (cláusula 17.6): texto novo é versão nova.
