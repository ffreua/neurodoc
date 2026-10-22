# Checklist de deploy — NeuroDoc 1.0

> **Documento histórico** (de 2026-09-24): o checklist do primeiro deploy,
> feito em 2026-09-25. As caixas em branco ficaram como estavam naquele
> dia. O procedimento em vigor está em [`DEPLOY.md`](DEPLOY.md) e, para um
> servidor novo, em
> [`docs/operations/primeiro-deploy.md`](docs/operations/primeiro-deploy.md).
>
> Três itens abaixo levariam alguém a errar hoje, e estão anotados onde
> aparecem: os segredos (são do Swarm, não de `.secrets/`), o
> `postgres_init.sh` (não se roda à mão) e o firewall (80 e 443 só para a
> Cloudflare).

Adaptado ao projeto real. O que está marcado foi **verificado nesta
auditoria** (2026-09-24); o que está em branco depende da VPS e de você.

Detalhe de cada item: `PRE_DEPLOY_AUDIT.md`. Passo a passo: `DEPLOY.md` e
`docs/operations/primeiro-deploy.md`.

---

## Antes de sair da máquina de desenvolvimento

### Código e verificação
- [x] Os 54 roteiros de `checks/` passam (`manage.py rodar_roteiros`)
- [x] 479 arquivos `.py` sem erro de sintaxe
- [x] `makemigrations --check --dry-run` limpo
- [x] `manage.py check --deploy` — só os 2 avisos deliberados de HSTS
- [x] `docker compose build app` conclui (inclui `pip check` e `mkdocs --strict`)
- [ ] Bateria rodada **uma última vez** na revisão exata que vai subir

### Segurança
- [x] Nenhum segredo versionado; `.gitignore` cobre `.env`, `.secrets/`, `*.pem`, `*.key`, `*.pfx`
- [x] Histórico do git sem segredo (o `.env` do primeiro commit tinha todas as chaves vazias)
- [x] Zero SQL cru; os 11 `cursor.execute` são *advisory locks* com parâmetro ligado
- [x] Apenas 2 `|safe`, ambos por renderizador que escapa antes
- [x] XSS de atributo no cliente corrigido e coberto por roteiro
- [x] Injeção de marcação no PDF corrigida e provada em PDF real
- [x] `/admin/login/` com limitador de tentativas
- [x] Alerta de erro sem segredo e sem dado de paciente
- [x] As duas entradas de dinheiro validadas (`150,00` não derruba mais a tela)
- [x] Download do acervo clínico cobra a capacidade do relatório, não a da tela
- [x] Data do sistema lida no fuso da clínica, não em UTC
- [x] **D-01 decidido e implementado**: endereço da IA por lista de permissão (`AI_BASE_URL_ALLOWLIST`, vazia por padrão)
- [ ] Se alguma clínica for usar servidor próprio (Ollama/vLLM), liberar o host em **`/instalacao/operacao/`** (não no `.env`: ele só semeia)
- [ ] Avaliar subir `cryptography` para 49.0.0 (exercitando a assinatura)

### Dados e privacidade
- [x] Exportação do acervo com permissão 0600 e expiração de 24 h
- [x] Trilha de auditoria imutável por gatilho
- [x] **D-02 decidido e implementado**: coleta semanal agendada, começando em ensaio (`DOCUMENTS_GC_DRY_RUN=True`)
- [ ] Após **um mês** de ensaio, ler na trilha quantos arquivos seriam removidos
- [ ] Só então autorizar o apagamento em **`/instalacao/operacao/`** (digitando `APAGAR` + motivo) — e **só depois** de a restauração ter sido testada num host separado
- [ ] Saber que o freio existe: "Voltar ao ensaio agora", um clique, na mesma tela

## Na VPS

### Preparação
- [ ] `scripts/setup_deploy.sh` executado até o fim (ele **para** se faltar `age`)
- [ ] Docker em modo Swarm, nó manager
- [ ] `fail2ban` ativo no SSH
- [ ] Fuso horário `America/Sao_Paulo`
- [ ] Firewall: 80 e 443 abertas; 22 restrita
  — *Hoje (desde 2026-10-19): 80 e 443 só para as faixas da Cloudflare,
  por `ops/cloudflare_firewall.sh` e `neurodoc-cloudflare-fw.timer`, que
  o `setup_deploy.sh` não instala. Ver `docs/operations/manutencao.md`.*

### Configuração
- [ ] `.env` preenchido a partir de `.env.example` (44 variáveis)
- [ ] `PUBLIC_BASE_URL=https://neurodoc.app.br` (o preflight recusa outro valor)
- [ ] `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` com o domínio real
- [ ] `DEBUG=False` (o preflight recusa `True`)
- [ ] `SECURE_HSTS_SECONDS=0` **neste primeiro deploy** — ligar só depois de o HTTPS estar comprovado
- [ ] `ACME_EMAIL` real (o preflight recusa `CHANGE_ME`)
- [ ] `ALERT_ADMIN_EMAILS` preenchido
- [ ] Os 9 segredos em `.secrets/`, um arquivo por segredo, modo 0600
  — *Errado para produção: `.secrets/` é do ambiente local. Na VPS são
  **quinze segredos do Swarm** (`docker secret create`), os de
  `docker-stack.yml`; o preflight confere cada um.*
- [ ] `TRUSTED_PROXIES` conferido **se houver Cloudflare ou outro proxy na frente** (auditoria §25.2)

### Banco
- [ ] `ops/postgres_init.sh` executado: papéis `neurodoc_owner`/`neurodoc_app`, `ALTER DEFAULT PRIVILEGES`, extensão `btree_gist`
  — *Não se roda à mão: o deploy o entrega ao contêiner `db` como
  `docker config`, e o Postgres o executa sozinho na primeira subida, com
  o volume vazio. Migrar também não é à mão (`manage.py migrate` nunca).*
- [ ] `REVOKE CREATE ON SCHEMA public FROM PUBLIC` aplicado
- [ ] 86 migrations aplicadas (`RUN_MIGRATIONS=True` só no `app`)

### Publicação
- [ ] `NEURODOC_SCHEMA_CHANGE=expand`
- [ ] Nota de versão copiada para `docs/releases/<SHA>.md`
- [ ] `NEURODOC_RELEASE_APPROVED=True`
- [ ] `scripts/deploy.sh` concluído sem erro
- [ ] Os 7 serviços saudáveis (`docker service ls`)

## Depois de publicar

### Fumaça (ver `TEST_MATRIX.md`)
- [ ] `https://neurodoc.app.br/health/` responde
- [ ] Rodapé mostra **versão 1.0**
- [ ] HTTP redireciona para HTTPS (301)
- [ ] Certificado emitido pelo Let's Encrypt
- [ ] Cabeçalhos: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`
- [ ] Cookies `Secure; HttpOnly; SameSite`
- [ ] `Host:` desconhecido devolve 400
- [ ] Página de vendas abre e o formulário de contato grava lead
- [ ] `/ajuda/` abre com as 47 capturas
- [ ] `/contrato/` abre

### Primeiro acesso
- [ ] `create_superadmin` e **MFA configurada antes de qualquer outra coisa**
- [ ] `/instalacao/` abre só com MFA
- [ ] `/admin/` recusa sem MFA
- [ ] Convite de plataforma da clínica-sede emitido
- [ ] Cadastro feito com aceite do contrato (SHA-256 gravado, via por e-mail)
- [ ] **Encarregado de dados** preenchido em Identidade da clínica

### Operação
- [ ] `testar_email` com SMTP real
- [ ] Celery: `dispatch_outbox` rodando (a cada minuto)
- [ ] `celery_beat` com as 7 tarefas agendadas (a coleta de lixo entrou)
- [ ] Primeiro backup executado **e restauração testada num host separado**
- [ ] Chave `age` de recuperação em posse de quem restaura, fora da VPS
- [ ] `BACKUP_DIR` com destino **externo** à VPS (P-10)
  — *P-10 foi resolvida de outro jeito, em 2026-10-02: `BACKUP_DIR` fica
  local (`/srv/neurodoc-backups`) e um PC **puxa** a cópia, de modo que a
  VPS não guarda credencial do destino. Ver
  `docs/operations/copia-externa.md`.*
- [ ] Alerta de erro chegando em `ALERT_ADMIN_EMAILS` (dispare um 500 de teste)

### Só depois de tudo verde
- [ ] `SECURE_HSTS_SECONDS` ligado
- [ ] `docs/releases/<SHA>.md` assinado por quem homologou
