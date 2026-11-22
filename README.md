# NeuroDoc — prontuário eletrônico para neurologistas e neurocirurgiões

[![Versão](https://img.shields.io/badge/vers%C3%A3o-1.56-3454d1)](docs/releases/)
[![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green)](LICENSE)
[![Em produção](https://img.shields.io/badge/produ%C3%A7%C3%A3o-neurodoc.app.br-3454d1)](https://neurodoc.app.br)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue)](https://www.python.org/)
[![Django 6.1](https://img.shields.io/badge/django-6.1-0c4b33)](https://www.djangoproject.com/)

[![NeuroDoc no Startups to Watch](https://startupstowatch.com.br/selo/neurodoc.svg)](https://startupstowatch.com.br/produto/neurodoc?ref=selo)

**[neurodoc.app.br](https://neurodoc.app.br)** · [Manual de uso](https://neurodoc.app.br/ajuda/) ·
[Perguntas frequentes](https://neurodoc.app.br/ajuda/perguntas/) ·
[Contrato](https://neurodoc.app.br/contrato/) ·
[Instagram @neurodoc_prontuario](https://www.instagram.com/neurodoc_prontuario/)

> **Outra especialidade?** O NeuroDoc é feito para **neurologia e
> neurocirurgia**. Para as demais especialidades, use o
> **[ProntDoc](https://prontdoc.app.br)** — o prontuário eletrônico geral,
> com agenda, receita da Anvisa, TISS, IA e portal do paciente.

Prontuário eletrônico e gestão para o consultório de **neurologistas e
neurocirurgiões**: o exame neurológico estruturado e as 14 escalas que a
especialidade usa — ou o texto livre, como o médico preferir —, com
**apoio de IA** revisado pelo médico, agenda, **receita digital da Anvisa
(SNCR)**, **Notificação de Receita A, B e B2 eletrônica**, documento
assinado em PAdES, **faturamento TISS**, agenda de EEG, ENMG e
polissonografia, portal do paciente, Dashboard e financeiro. Feito por um
neurologista, em uso real em consultório.

Django monolítico modular, SSR com Django Templates, PostgreSQL como fonte
de verdade clínica e Celery para trabalho pesado. Multi-inquilino: uma
instalação, várias clínicas.

| | |
| --- | --- |
| **Versão** | 1.56 (`base/version.py`) |
| **Em produção** | <https://neurodoc.app.br> — em uso real desde 02/10/2026 |
| **Licença** | [MIT](LICENSE) — código aberto |
| **Verificação** | 191 roteiros em `checks/` |
| **Stack** | Python 3.14 · Django 6.1 · PostgreSQL 17 · Celery · RabbitMQ · Redis · Traefik · Docker Swarm · Cloudflare |

## Apoie o projeto

O NeuroDoc é escrito e mantido por um neurologista, no tempo entre um
atendimento e outro. Se ele for útil para você:

- ⭐ **deixe uma estrela** neste repositório — é o que mostra a outros
  médicos que o projeto existe e é usado;
- 💚 **contribua com qualquer valor pelo PIX:** `fernando.freua@gmail.com`;
- 📷 **siga o NeuroDoc no Instagram:** [@neurodoc_prontuario](https://www.instagram.com/neurodoc_prontuario/)
  — novidades de cada versão e dicas de uso;
- 🐛 **abra uma issue** com o defeito que encontrou ou com o que falta para
  a neurologia e a neurocirurgia.

---

## O que o sistema faz

**Clínico.** Atendimento em dois tipos — prontuário estruturado e texto
livre —, roteiro de exame neurológico em árvore (387 nós, YAML), 14 escalas
pontuadas, medicações, hipóteses em CID-10, resultados de exame com valores
laboratoriais, cópia revisada da consulta anterior, série temporal em
gráfico, busca de paciente por diagnóstico (CID-10 e CID-11). As listas do
prontuário vêm em ordem: exames do mais recente ao mais antigo, medicações
em uso antes das suspensas. Durante o atendimento, os
dados de cadastro ficam numa **gaveta** (`Alt+D`), sem sair da evolução.
Prontuário finalizado é imutável: correção é **adendo**, com autor e data,
nos dois tipos. O histórico de outro sistema entra por migração (o do
iClin, 7.661 atendimentos, já entrou), como texto livre finalizado.

**Documentos.** Receita simples, laudo, atestado, relatório, declaração de
comparecimento, pedido de exame, encaminhamento e solicitação de cirurgia —
assinados em **PAdES** com o certificado do próprio médico e verificáveis
publicamente por QR, sem conta. **Modelos de documento** por médico
(pedidos por categoria, conjuntos que abrem um pedido por categoria) emitidos
direto da Conduta. Catálogo CMED/Anvisa com 26 mil apresentações no
autocomplete.

**Receita controlada no SNCR da Anvisa** (RDC 1.000/2025). O médico pede a
própria numeração com o Gov.br e emite, no **modelo oficial**, a Receita de
Controle Especial e a de Retenção (blocos de 1.000 números) e, desde a 1.34,
a **Notificação de Receita A, B e B2** (lotes retirados da cota da Vigilância
Sanitária) — uma folha e um número por medicamento, com o QR da consulta no
SNCR. A lista oficial da Portaria 344/98 (780 substâncias, 16 listas) confere
cada medicamento contra o tipo de receita e aponta o certo.

**Convênio e exames.** Faturamento **TISS** da ANS — guias de Consulta e
SP/SADT, lotes em XML validados contra o XSD oficial de **sete versões** do
padrão (3.04.00 a 4.03.00) — e **agenda de exames por equipamento** (EEG,
ENMG, polissonografia que atravessa a noite), separada da dos médicos.
Particular ou convênio escolhido por atendimento; 1.105 operadoras da ANS
no cadastro de convênio.

**Operação do consultório.** Agenda por médico com regras de
disponibilidade, **intervalos pontuais** (o almoço), bloqueios, feriados,
retorno programado e **lista de espera** ordenada pela secretária e puxada
direto para o horário; a **agenda do dia seguinte por e-mail** a cada
médico, às 19h; **aviso automático** ao paciente ao marcar, remarcar e
cancelar, com o endereço e o telefone da clínica; cadastro com
**naturalidade** (5.571 municípios do IBGE no autocomplete); portal
público onde o paciente pede receita, relatório ou pedido de exames sem
criar conta, e **envia os laudos dos exames que fez** (PDF, direto no
prontuário, com alerta ao médico até o "Ciente"); outbox de entrega
por e-mail e SMS com links opacos, OTP e confirmação de entrega lida do
provedor; convênios, honorários com vigência,
recebíveis e pagamentos (tudo em `Decimal`); exportação do acervo em
Markdown e JSON.

**Gestão.** **Indicadores** com primeiras consultas, seguimentos e retornos,
e a receita discriminada por tipo de atendimento e por procedimento.
**Dashboard** por clínica e por médico — idade, sexo, UF,
município, país, naturalidade, origem, pagamento, convênio, atendimentos por
mês e CID —,
cada tabela em CSV agregado, com a regra das células pequenas. **Mailing** de
quem consentiu, com o link de descadastro de cada um. **Comunicação em
massa em HTML com CSS**, com prévia, teste e **cliques contados por link**
(o mesmo link para todos: a contagem não identifica ninguém).

**IA.** Jobs com revisão médica obrigatória, desidentificação local antes
de sair, chat persistente com streaming (Redis Streams + SSE), catálogo de
dez provedores e a possibilidade de a clínica apontar o próprio contrato.
O **provedor padrão** da instalação é trocado no console, com verificação
de que o modelo ainda existe. Relatório do paciente redigido pela IA e
assinado pelo médico. Na conversa sem paciente, o chat de apoio também
responde sobre o **uso do sistema**, pelos trechos do manual e da
documentação técnica que a busca escolhe para cada pergunta. O apoio
clínico é recurso de plano, vetado em duas camadas independentes.

**O que é da clínica.** E-mail, SMS e IA seguem a mesma cadeia — a clínica
que configurou o seu usa o seu; a que desligou volta ao padrão da
instalação. A **comunicação em massa** é a exceção: está em todos os
planos e sai só pelo servidor de e-mail da própria clínica. O nome
fantasia é editado pela própria clínica; razão social e CNPJ continuam
vindo do convite.

**Segurança e cadastro.** Segundo fator (TOTP) obrigatório para
responsável e médico, com o **dispositivo confiável** que a clínica pode
liberar (termo aceito e auditável, revogável a qualquer momento); registro
de **quem abriu cada prontuário**, visível ao responsável; CRM validado para
o papel médico; cadastro de clínica com CNPJ (inclusive o alfanumérico) ou CPF;
e-mail descartável recusado por uma lista pública de ~220 mil domínios,
atualizada toda semana.

**Para conhecer.** Plano Gratuito sem prazo, e **degustação de sete dias
do Completo** pela página de vendas, sem cartão — depois, a clínica volta ao
Gratuito e nada é apagado.

**Plataforma.** Multi-inquilino com três camadas de autorização, trilha de
auditoria imutável, backup diário cifrado com `age`, com cópia externa e
cópia na nuvem com trava contra exclusão, registro de telas lentas,
console de superadministrador, central de ajuda pública e página de vendas. Telas
ajustadas ao celular de 320 px ao tablet, e um tema só, o claro.

---

## Experimente na sua máquina

Tudo roda em contêineres: banco, fila, worker, antivírus e uma caixa de
e-mail de teste (Mailpit). Nenhuma chave de serviço externo é necessária —
e-mail real, SMS e IA nascem desligados.

**Pré-requisitos:** Git, Docker com Compose (Docker Desktop no Windows e no
macOS) e Python 3.10 ou mais novo com o PyYAML (`pip install pyyaml`),
usado pelos scripts que geram a configuração.

```bash
git clone https://github.com/ffreua/neurodoc.git
cd neurodoc
cp .env.example .env                 # o gerador força DEBUG e desliga e-mail, SMS e IA
python -m ops.secret_setup --local   # cria .secrets/ com senhas e chaves aleatórias
python -m ops.local_compose          # gera compose.yml a partir do docker-stack.yml
docker compose up -d --build         # a primeira build leva alguns minutos; o app migra sozinho
docker compose exec app python manage.py seed_demo
```

Abra <http://localhost:8000> e entre com uma conta de demonstração — a
senha de todas é `DemoS3nha!123`:

| Conta | Papel |
| --- | --- |
| `doctor-a@demo.neurodoc.local` | médica e responsável, nas **duas** clínicas de demonstração: prontuário, documentos, agenda e organização |
| `doctor-b@demo.neurodoc.local` | médico da Clínica A: o próprio prontuário e a própria agenda |
| `secretary-a@demo.neurodoc.local` | secretária, nas **duas** clínicas: agenda e cadastro, sem acesso ao prontuário |
| `manager-a@demo.neurodoc.local` | gestora da Clínica A: financeiro e indicadores |

Quem tem vínculo com as duas clínicas escolhe a organização ao entrar — é
o mesmo caminho de quem atende em mais de um consultório.

Os pacientes, as agendas e as clínicas são fictícios. Nunca use a
demonstração com dados de paciente real.

Os e-mails que o sistema enviaria aparecem no Mailpit, em
<http://localhost:8025>. Dois catálogos ficam de fora da semeadura porque
são baixados da internet, e um terceiro mora no repositório mas também não
vem da semeadura; rode-os quando for usar receita, receita controlada e
naturalidade:

```bash
docker compose exec celery_worker python manage.py import_cmed        # medicamentos da Anvisa (~12 MB)
docker compose exec celery_worker python manage.py import_municipios  # municípios do IBGE
docker compose exec app python manage.py import_portaria344           # lista oficial dos controlados
```

Para desligar: `docker compose down` (mantém o banco) ou
`docker compose down -v` (apaga tudo e recomeça do zero).

**Não rode `manage.py migrate` à mão.** A conexão padrão usa um papel sem
permissão de DDL; quem migra é o próprio `app` ao subir, por uma conexão
separada e com trava.

---

## Verificação

Não há suíte de testes automatizados — o substituto são os **roteiros** em
[`checks/`](checks/): cada um tenta quebrar um comportamento, imprime seção
por seção e sai com código 1 listando as falhas. Com a demonstração
semeada e os três catálogos acima importados:

```bash
docker compose exec app python manage.py rodar_roteiros            # todos os 191
docker compose exec app python manage.py rodar_roteiros planos landing
docker compose exec app python manage.py rodar_roteiros --listar
```

`rodar_roteiros` lê `checks/` **de dentro da imagem**: depois de mudar
código, reconstrua (`docker compose up -d --build`) antes de acreditar no
resultado. Um roteiro só, direto do disco:

```bash
docker compose exec -T app python manage.py shell < checks/check_planos.py
```

---

## Publicar numa VPS

A produção roda em **Docker Swarm de um nó**, com a imagem publicada no
GitHub Container Registry e identificada pelo SHA do commit, o Traefik
emitindo o certificado do Let's Encrypt por desafio de DNS na Cloudflare, e
a Cloudflare na frente, com proxy. A porta de entrada da operação é o
[`DEPLOY.md`](DEPLOY.md): como a produção está montada, como se publica e
onde está cada assunto.

**O que você precisa:**

- uma VPS com **Ubuntu 24.04**, 4 vCPU, 8 GB de RAM e 80 GB de disco,
  com acesso `root` por SSH;
- um **domínio no Cloudflare** e um token de API com permissão de editar o
  DNS (o certificado é curinga, para `*.seudominio`, por desafio DNS);
- um **token do GitHub** com o escopo `write:packages`, para publicar a
  imagem;
- um par de chaves do [`age`](https://github.com/FiloSottile/age) para o
  backup cifrado — a pública vai para o servidor, **a privada nunca**;
- uma caixa de e-mail com SMTP (opcional para começar).

**Num fork, troque o domínio.** O deploy confere que está publicando o
domínio esperado, e ele está escrito em três lugares:
`docker-stack.yml` (as regras do Traefik), `ops/deploy.py` (a conferência
de `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` e `PUBLIC_BASE_URL`) e
`scripts/setup_deploy.sh` (`DOMINIO=`). No `.env`, `REGISTRY` aponta para
o seu registro (`ghcr.io/<seu-usuario>/neurodoc`).

**Primeira vez**, na VPS limpa, como `root`:

```bash
git clone https://github.com/<seu-usuario>/neurodoc.git /srv/neurodoc
bash /srv/neurodoc/scripts/setup_deploy.sh
```

O script instala Docker, Swarm, firewall e `age`, cria o usuário de
operação, pergunta as chaves (guardando-as como *secrets* do Swarm, nunca
em arquivo), publica a imagem e sobe a pilha. Ele **retoma de onde
parou** — se cair no meio, rode de novo. O passo a passo comentado, para
quem nunca administrou um servidor, está em
[`docs/operations/primeiro-deploy.md`](docs/operations/primeiro-deploy.md).

**Atualizações**, com o usuário de operação:

```bash
cd /srv/neurodoc && git pull --ff-only
bash scripts/deploy.sh --check                                             # confere sem publicar
setsid nohup bash scripts/deploy.sh > /tmp/deploy.log 2>&1 < /dev/null &   # publica
```

O deploy constrói a imagem, sobe as réplicas novas antes de derrubar as
antigas, migra o banco na subida e só termina quando `/health/` responde.
Rollback, backup (cifrado e com cópia externa), restauração e
monitoramento: [`docs/operations/`](docs/operations/). Voltar uma versão é
`docker service rollback` nos **três** serviços da aplicação, e não
`--skip-build`, que republica a atual
([`rollback.md`](docs/operations/rollback.md)).

Com o proxy da Cloudflare ligado, ponha as faixas dela em
`TRUSTED_PROXIES` e feche as portas 80 e 443 para quem não é ela
(`ops/cloudflare_firewall.sh`, instalado à mão — ver
[`manutencao.md`](docs/operations/manutencao.md)).

**Quantos processos.** `APP_WORKERS` e `WORKER_CONCURRENCY` no `.env`
dizem quantos processos cada réplica do `app` roda e quantas tarefas o
worker faz ao mesmo tempo (vazio é 2 e 2, o de uma VPS pequena; a produção
roda 4 e 6, numa VPS de 6 vCPU e 16 GB, e estima-se que aguente cerca de
300 clínicas do porte das atuais). Subir os números exige subir o limite de
CPU do `docker-stack.yml` junto — ver
[`capacidade.md`](docs/operations/capacidade.md).

Duas chaves começam desligadas **de propósito**: `SECURE_HSTS_SECONDS`
(ligue só com o HTTPS comprovado — o navegador guarda a instrução e não há
volta) e `CSP_ENFORCE` (a política sai primeiro em modo de relatório;
esta dá para voltar).

---

## Versões

`VERSION` em [`base/version.py`](base/version.py) identifica o **produto**;
o SHA do commit publicado identifica o **build**. Funcionalidade nova
avança a versão menor (1.16 → 1.17); correção ganha a terceira casa quando
é preciso distinguir quem já tem a correção. Cada versão publicada tem
registro em [`docs/releases/`](docs/releases/). Abaixo, as cinco últimas,
em ordem cronológica; o histórico inteiro está em `base/version.py` e em
`docs/releases/`.

| Versão | Data | Nome | O que entrou |
| --- | --- | --- | --- |
| **1.52** | 2026-11-19 | Dashboard | **Dashboard no menu**: o perfil da carteira e da atividade por clínica e por médico (idade, sexo, UF, município, origem, pagamento, convênio, mês a mês e CID), cada tabela em CSV agregado; quem administra escolhe o médico, o médico vê a própria carteira. O **mailing** dos contatos que consentiram, só pelo responsável e com o código recente. Junto, a correção de incluir horário fora da cadência na agenda. Sem migração. `check_painel` |
| **1.53** | 2026-11-20 | a auditoria | **A auditoria externa conferida e corrigida**: segundo fator que só se troca com o código atual, o `/admin/login/` pedindo o código, acervo e mailing baixados só por quem pediu, convite pago preso ao e-mail, restauração presa ao `.env`, pagamento estornado que não se apaga, PDF do paciente no quadro, a corrida ao finalizar travada, a trilha sem nome de medicamento e de exame; e **quem abriu o prontuário**, na trilha e na ficha. `check_revisao_2026_11_20` |
| **1.54** | 2026-11-20 | telas lentas | **O registro de telas lentas**: toda resposta acima de 500 ms grava a rota, o tempo e as consultas, sem dado que identifique, por 30 dias, e o console mostra por rota. Junto, o **HTML comprimido na saída** (a vitrine de 124 KB a 21 KB). Uma migração, só acrescenta. `check_telas_lentas`, `check_compressao` |
| **1.55** | 2026-11-22 | a campanha | **Comunicação em massa em HTML com CSS**, limpa por lista de permissão, com prévia, rascunho editável, **cliques contados por link** (sem identificar quem clicou) e **excluir campanha**. O painel do SNCR com lista curta de pedidos e histórico paginado; no Dashboard, o município somado sem diferença de acento, o **Exterior** e o cartão **País**; o país do endereço numa lista na ficha. Duas migrações, só acrescentam. `check_campanha_html`, `check_sncr_lista_de_pedidos` |
| **1.56** | 2026-11-22 | indicadores | **O painel de indicadores completo**: cartões de **seguimentos** e **retornos** pelo tipo da agenda, as consultas atendidas por tipo e a **receita por tipo de atendimento** — primeira consulta, seguimento, retorno e cada procedimento pelo código TUSS, com quantidade, valor, médio e porcentagem; a taxa de falta contando o check-in. No Dashboard, a **naturalidade** (país e UF de nascimento). Sem migração. `check_indicadores_por_tipo` |

---

## Arquitetura

```
Navegador → Cloudflare (proxy) → Traefik (TLS) → Django ASGI (app) → PostgreSQL
                                   ↓
                              RabbitMQ → Celery worker → PostgreSQL
                                              ↓         ↘ IA / SMTP / SMSDEV
                                           Redis  → SSE de volta ao app
```

Sete serviços permanentes: `app`, `celery_worker`, `celery_beat`, `db`,
`rabbitmq`, `redis`, `traefik` (+ `mailpit` só no ambiente local). Quantos
processos e tarefas cada um roda é do `.env` da instalação
([`docs/operations/capacidade.md`](docs/operations/capacidade.md)).

**Regra de rede que explica muito código:** e-mail, SMS, IA, o espelho da
TUSS e a lista de e-mail descartável saem sempre por **tarefa Celery**,
nunca de dentro da requisição. A exceção deliberada é o pedido de numeração
do SNCR, trocado na requisição porque o token do Gov.br vive 30 segundos. O
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
| `base` | primitivas (`TenantModel`, cripto, logging com redação), página de vendas, central de ajuda e **SEO** (`seo.py`: título, descrição, `robots`, sitemap, JSON-LD e `llms.txt` de uma fonte só) |
| `accounts` | `User` (e-mail como login), MFA TOTP obrigatório para responsável e médico, códigos de recuperação, CRM do médico |
| `tenancy` | `Tenant` (CNPJ ou CPF), `Membership`, convites, leads, **planos, limites, matriz de permissão e contrato de adesão**, e-mail de encerramento |
| `patients` | ficha, contatos, convênio, numeração por clínica, naturalidade, forma canônica do nome, migração de cadastro |
| `catalogs` | CID-10, TUSS (com vigência por código), CMED/Anvisa, municípios do IBGE, CEP, operadoras da ANS, **Portaria 344/98** e domínios de e-mail descartável |
| `clinical` | atendimento nos dois tipos, exame, diagnósticos, medicações, adendo, cópia da consulta anterior, série temporal, migração do histórico do iClin |
| `exams` | motor do roteiro em árvore e as 14 escalas |
| `scheduling` | agenda, disponibilidade, intervalos pontuais, bloqueios, retorno programado, **lista de espera**, forma de cobrança por atendimento, declaração, estatísticas |
| `sncr` | numeração da Anvisa (blocos da RCE/RET, lotes da Notificação A/B/B2), receita eletrônica no modelo oficial |
| `modelos` | modelos de documento do médico e a emissão pela Conduta |
| `tiss` | faturamento TISS: prestador, credenciamento, guias, lotes e XML em sete versões do padrão |
| `agenda_exames` | agenda por equipamento (EEG, ENMG, polissonografia) e a cobrança do exame realizado |
| `documents` | anexos com antivírus, documentos médicos, assinatura PAdES, QR público, portal do paciente (solicitações e envio de laudos), OCR |
| `communications` | outbox, links opacos com OTP, aviso de horário, campanhas com consentimento, credenciais da clínica |
| `finance` | honorários com vigência, recebíveis, pagamentos, ajustes |
| `ai` | jobs com revisão médica, desidentificação, chat com streaming (que, sem paciente, consulta o manual), relatório do paciente |
| `notifications` · `teamchat` | sino do usuário · mensagens internas da equipe |
| `audit` · `events` | trilha imutável · outbox de eventos com dispatcher idempotente |
| `reporting` · `integrations` · `ops` | indicadores e exportação · antivírus/CEP/TUSS · deploy, backup, saúde, console (com as chaves de **Operação**) |

O detalhe de cada decisão está em [`CLAUDE.md`](CLAUDE.md) §4 e no
[`PRD.md`](PRD.md).

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
| [`docs/CODEBASE_MAP.md`](docs/CODEBASE_MAP.md) | o mapa do código: o que cada módulo exporta, fluxos em diagrama, e "para mexer em X, abra Y" |
| [`docs/ESTADO-ATUAL.md`](docs/ESTADO-ATUAL.md) | **leia primeiro** — o retrato de hoje: o que está provado, o que está aberto, as lições que custaram caro |
| [`PRD.md`](PRD.md) | a especificação completa (matriz de permissão §4, roteiro de homologação §21) |
| [`docs/index.md`](docs/index.md) | índice da documentação técnica, publicada em `/technical-docs/` (MFA) |
| [`docs/decisions.md`](docs/decisions.md) | decisões (DEC-xx) e pendências (P-xx) com dono e condição de liberação |
| [`docs/governance/lgpd.md`](docs/governance/lgpd.md) | matriz de tratamento, operadores, medidas técnicas e o roteiro que verifica cada uma |
| [`DEPLOY.md`](DEPLOY.md) | **a porta de entrada da operação**: como a produção está montada, como se publica, e o índice de `docs/operations/` |
| [`docs/operations/`](docs/operations/) | deploy, rollback, backup, cópia externa, monitoramento, capacidade |
| [`docs/sncr/`](docs/sncr/) | a integração com o SNCR da Anvisa: decisões, estado e ativação |
| [`docs/tiss/`](docs/tiss/) | o faturamento TISS: campos, operação e homologação |
| [`docs/homologation/seo.md`](docs/homologation/seo.md) | como o produto aparece na busca: catálogo, sitemap, `robots`, `llms.txt` e o que falta fazer no Search Console |
| [`docs/homologation/`](docs/homologation/) | homologação por entrega — é onde mora o "por que ficou assim" |
| [`docs/releases/`](docs/releases/) | registro de cada release publicada (PRD §18.6) |

---

## Contribuir

Issues e pull requests são bem-vindos, **em português** — o produto, os
comentários e as mensagens de commit são em português. Antes de abrir um
PR:

1. leia as convenções em [`CLAUDE.md`](CLAUDE.md) §1;
2. rode os roteiros que cobrem o que você mexeu, e escreva um novo se o
   comportamento não tiver roteiro — ele precisa **falhar** com o defeito
   presente;
3. nunca inclua dado de paciente real em issue, commit ou captura de tela.

**Falha de segurança:** não abra issue pública. Escreva para
contato@neurodoc.app.br; a correção é feita aqui e no sistema derivado antes
de qualquer detalhe ficar público.

### Agradecimentos

- **[@meirakalile-ship-it](https://github.com/meirakalile-ship-it)** leu o
  código por conta própria e relatou, em novembro de 2026, seis pontos de
  segurança — leitura de prontuário pelo admin sem trilha, certificado
  revogado que continuava guardado, a janela da senha do certificado na
  sessão de assinatura, o rodapé que afirmava ICP-Brasil sem conferir a
  cadeia, o código de recuperação do segundo fator sem limite e o molde de
  configuração que nascia inseguro. Todos procediam e foram corrigidos.
  Obrigado.

---

## Licença

Código sob a [licença MIT](LICENSE) · © 2026 Fernando Freua.

O serviço hospedado em <https://neurodoc.app.br> é mantido pela
**ProntDoc Prontuários Médicos Ltda.**, CNPJ 69.887.146/0001-05 (desde
2026-10-29; antes, pela pessoa física do autor), e oferecido às clínicas
por contrato de adesão próprio, publicado em
<https://neurodoc.app.br/contrato/>; ele rege a prestação do serviço e não
altera os direitos que a licença MIT concede sobre este código.
