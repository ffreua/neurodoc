# Onde o NeuroDoc está — 2026-10-02

Leia isto antes de mexer em qualquer coisa. É o retrato do sistema no dia
em que ele passou a ser usado de verdade, com o que está provado, o que
está aberto e o que já quebrou antes.

**Versão:** 1.4 "quem assina é o autor" · **Produção:**
`https://neurodoc.app.br` (VPS Integrator, `ssh deploy@23.106.44.46`)

---

## 1. O que está no ar

Sete serviços em Docker Swarm, todos saudáveis: `app` (2 réplicas),
`celery_worker`, `celery_beat`, `db`, `rabbitmq`, `redis`, `traefik`.

Uma clínica real — **Consultório Dr. Fernando Freua**, plano Personalizado
— com **2.229 pacientes** migrados do sistema anterior, 2 vínculos ativos,
1 certificado de assinatura e 1 médico com CRM. Nenhum dado de
demonstração em produção.

| Trava de segurança | Estado |
| --- | --- |
| `DEBUG` | `False` |
| HTTPS forçado, cookies `secure` | sim |
| **HSTS** | **ligado em 02/10/2026** — 1 ano, **com** subdomínios. Não há volta |
| **CSP** | **em modo bloqueio desde 02/10/2026**. Dá para voltar: `CSP_ENFORCE=False` e republicar |
| MFA | obrigatória para certificado e console de instalação |

## 2. O que está provado

**O backup abre.** Em 02/10/2026 o backup de 01/10 foi baixado,
decifrado com a chave privada do controlador e conferido: dump Postgres
válido, **86 tabelas**, incluindo `patients_patient`,
`clinical_encounter` e `documents_medicaldocument`. Nove backups diários
em `/srv/neurodoc-backups/`, cifrados com `age`, ~4,6 MB cada.

Isto era a maior incógnita do sistema. Não é mais — mas só vale para
aquele backup e aquela chave: **refazer a prova depois de qualquer
mudança no `BACKUP_AGE_RECIPIENT`.**

**89 roteiros de verificação, nenhuma falha.** São o que substitui a
suíte de testes (DEC-20). Rodar com `manage.py rodar_roteiros`, dentro do
contêiner.

## 3. O que está aberto, e o que custa

### ~~P-10 — Backup só existe na máquina que ele protege~~ — resolvida em 2026-10-02

O backup deixou de existir só na máquina que ele protege. Os **11
conjuntos** estão em `D:
eurodoc-backups` (SSD externo, 57,8 MB), cada
arquivo conferido por **SHA-256 contra o `manifest.json`**, e a tarefa
diária das 09:00 está registrada no Windows e **já executou com sucesso**
(resultado 0) — a execução sob o agendador foi testada, e não só a
manual, porque é lá que a chave SSH poderia não funcionar.

Puxar, e não empurrar, é a decisão que importa: se a VPS empurrasse, ela
guardaria a credencial do destino, e quem a invadisse apagaria também a
cópia de fora. Puxando, a VPS não sabe que o disco existe.

Ver [`operations/copia-externa.md`](operations/copia-externa.md) e
`scripts/puxar_backups.ps1`.

**O que a primeira execução real ensinou:** 2 das 11 pastas falharam com
`scp: Connection closed`, sem padrão, e vieram inteiras na tentativa
seguinte. O script passou a tentar três vezes — vermelho semanal por
soluço de rede é vermelho que ninguém olha, e é assim que uma falha de
verdade passa despercebida.

### ~~A chave privada do backup está num lugar só~~ — resolvida em 2026-10-02

A chave foi guardada em **gerenciador de senhas** pelo controlador, fora
desta máquina. Deixa de ser ponto único de falha: antes,
`C:\Users\ferna\Documents\CHAVE-BACKUP.key` era a única cópia, em texto
claro, e sem ela todo backup é lixo cifrado — coisa que **já se perdeu uma
vez neste projeto** (ver `docs/operations/diario-do-primeiro-deploy.md`
§3).

O arquivo na máquina continua sendo o que o dia a dia usa; o que mudou é
que ele não é mais o único lugar onde a chave existe.

**Nunca entra em limpeza de disco**, e a prova de restauração tem de ser
refeita a cada mudança de `BACKUP_AGE_RECIPIENT`.

### Os pacientes migrados não recebem documento

Dos 2.229, **sete** contatos estão aptos. A migração não autoriza
ninguém a receber mensagem, por decisão de LGPD — e isso está certo. A
ficha do paciente agora **avisa** quando o contato não está apto, no
momento em que a secretária pode resolver (marcar "conferido" e
"Autorizado a receber documentos").

Esperado: a base vai ficando apta conforme os pacientes voltam.

### O processo web tem saída para a internet

O `app` está em `traefik_public`, que não é `internal` — e não pode ser,
porque o Traefik precisa alcançar o ACME do Let's Encrypt. O isolamento
que o desenho pretendia **nunca existiu**; o `CLAUDE.md` afirmava o
contrário até 02/10/2026 e por isso induziu a um diagnóstico errado nesta
sessão.

Fechar é separar Traefik e `app` em duas redes. Trabalho aberto, com
risco de mexer na rede de produção.

### Outras

- **P-02** (VPS real) e **P-05** (certificado real) seguem como estão em
  `docs/decisions.md`.
- **P-09** — enquadramento regulatório do apoio diagnóstico. Bloqueia M3.
- **TUSS incompleta**: ~3.200 de ~5.900 procedimentos. Ela se retoma
  sozinha de hora em hora desde 02/10; antes disso o laço morria a cada
  deploy.
- O `CLAUDE.md` lista 43 dos 89 roteiros ("os mais relevantes") e 4 views
  de catálogo têm `required_capability = None` sem o comentário que a
  convenção exige.

## 4. As lições que custaram caro nesta sessão

Estão aqui porque cada uma voltou disfarçada de outra coisa.

**Há defeito que não quebra nada e por isso ninguém encontra.** O
`<title>` da página inteira do produto era a palavra "NeuroDoc" desde
sempre: `partials/head.html` entra por `{% include %}` e o bloco morava
lá dentro — bloco não atravessa include, e os noventa e nove
`{% block title %}` dos templates eram letra morta. Nada quebra, nada vai
para o log, e o sintoma só existe na aba do navegador e na primeira linha
do resultado de busca, que são os dois lugares onde ninguém olha ao
conferir uma tela. Encontrado em 2026-10-03, ao montar o SEO; o roteiro
que o teria pego é `check_seo.py` (ver `docs/homologation/seo.md`).

**Um teste que não falha com o defeito presente não é teste.** Quatro
ocorrências: roteiro lendo a própria legenda; roteiro de paginação sem
volume; asserção casando com ícone decorativo; e um roteiro que passava
em dois dias da semana e reprovava nos outros cinco. O último é o pior:
ensina quem lê a ignorar o vermelho.

**Lista escrita à mão envelhece.** A guarda de fuso, a de idioma e a de
chaves do runtime nasceram como listas e falharam pelo mesmo motivo —
não cobriam o arquivo que ninguém lembrou de acrescentar. As três viraram
varreduras do repositório.

**Documento que afirma o que o servidor não faz custa mais que documento
que não diz nada.** Aconteceu três vezes: a chave estrangeira composta
"em toda parte" que estava em dois apps, o isolamento de rede que nunca
existiu, e esta tabela dizendo que o HSTS estava **sem** subdomínios
quando `SECURE_HSTS_INCLUDE_SUBDOMAINS=True` no `.env` da VPS e o
cabeçalho em produção traz `includeSubDomains`. A terceira é a mais
perigosa das três: HSTS não tem volta, e um dia alguém publicaria algo em
`sub.neurodoc.app.br` sem HTTPS confiando nesta linha.

**Efeito colateral não pode derrubar o ato.** Uma entrega que falha tem
de virar linha vermelha numa lista, nunca uma tela de erro sobre um
documento que já foi assinado.

**O que sai da transação antes do commit mente.** O e-mail saía com um
token que a transação ainda não tinha gravado — e o paciente recebia um
link "inválido ou expirado". `on_commit` no backend de e-mail; token
gravado antes de enviar, para o SMS.

## 5. Como se opera

```bash
# Verificação (dentro do contêiner, sempre)
docker compose exec app python manage.py rodar_roteiros

# Publicar — build e deploy rodam NA VPS, nunca localmente
ssh deploy@23.106.44.46 "cd /srv/neurodoc && git pull --ff-only \
  && bash scripts/deploy.sh --check \
  && (setsid nohup bash scripts/deploy.sh > /tmp/deploy.log 2>&1 < /dev/null &)"
```

- O ambiente local **só sobe para rodar roteiros**, e desce depois.
- `rodar_roteiros` lê `checks/` **de dentro da imagem**: mudou roteiro,
  reconstrua (`docker compose build app`) ou empurre pela entrada padrão.
- Migração roda sozinha na subida (`prepare_release`). **Nunca**
  `manage.py migrate` à mão: o papel da aplicação não tem permissão no
  schema.
- O worker reinicia a cada deploy. Tarefa longa interrompida precisa
  retomar sozinha pelo estado, não pelo elo anterior.

## 6. Onde está o resto

| Assunto | Arquivo |
| --- | --- |
| Mapa do sistema, convenções | `CLAUDE.md` |
| Decisões e pendências com dono | `docs/decisions.md` |
| Homologação por funcionalidade | `docs/homologation/` |
| Operação, deploy, backup | `docs/operations/` |
| LGPD | `docs/governance/lgpd.md` |
| Especificação completa | `PRD.md` |
