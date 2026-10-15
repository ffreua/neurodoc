# Onde o NeuroDoc está — 2026-10-02

Leia isto antes de mexer em qualquer coisa. É o retrato do sistema no dia
em que ele passou a ser usado de verdade, com o que está provado, o que
está aberto e o que já quebrou antes.

**Versão:** 1.14 "a agenda" · **Produção:**
`https://neurodoc.app.br` (VPS Integrator, `ssh deploy@23.106.44.46`)

---

## 1. O que está no ar

Sete serviços em Docker Swarm, todos saudáveis: `app` (2 réplicas),
`celery_worker`, `celery_beat`, `db`, `rabbitmq`, `redis`, `traefik`.

**Duas** clínicas reais, conferidas em 05/10/2026 — e a segunda é o que
tirou o multi-inquilino do papel:

| Clínica | Plano | Pacientes | Vínculos ativos |
| --- | --- | --- | --- |
| Freua Serviços Médicos (Consultório Dr. Fernando Freua) | Personalizado | 2.231 | 3 |
| CALDAS, REGO E URBANO SERVICOS MEDICOS LTDA | Completo | 62 | 2 |

Dois médicos com CRM verificado. Nenhum dado de demonstração em
produção. **Há uma pessoa com vínculo nas duas** — a secretária — e foi
ela quem encontrou o primeiro defeito de isolamento que o sistema teve
em uso real (§4, o logotipo no cache do navegador). Vale como aviso de
onde procurar o próximo: a jornada que só existe quando alguém pertence
a mais de uma clínica não é exercitada por quem pertence a uma.

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

**100 roteiros de verificação, nenhuma falha.** São o que substitui a
suíte de testes (DEC-20). Rodar com `manage.py rodar_roteiros`, dentro do
contêiner.

## 3. O que está aberto, e o que custa

### ~~P-10 — Backup só existe na máquina que ele protege~~ — resolvida em 2026-10-02

O backup deixou de existir só na máquina que ele protege. Os **11
conjuntos** estão em `D:\neurodoc-backups` (SSD externo, 57,8 MB), cada
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

### O Postgres tem um patch pendente, e a tag é um alvo móvel

Descoberto em 06/10/2026, ao publicar a 1.7: `postgres:17.11-bookworm` é
tag **mutável**, e o Docker Hub a republicou — o digest que roda
(`639ab7ce…`) não é mais o que a tag resolve (`3645570c…`). O deploy
recusou-se a seguir, com `Infrastructure image changed`, que é o
comportamento certo: trocar a imagem do banco não é efeito colateral de
publicar aplicação.

Para publicar, o `.env` da VPS passou a fixar o Postgres pelo digest que
**já está rodando**. Nada mudou no banco.

**Aberto:** aplicar o rebuild de patch do Postgres numa janela própria,
com backup conferido antes. E decidir se as outras três imagens de
infraestrutura passam a ser fixadas por digest no `.env.example` — hoje
são tags, e tag é alvo móvel.

### Outras

- **A `LICENSE` diz MIT e o contrato diz o contrário.** A cláusula 16 do
  contrato de adesão afirma que o código-fonte pertence ao contratado e que
  o contrato "não transfere sua propriedade intelectual"; um arquivo MIT na
  árvore concede a qualquer um o direito de copiar, modificar, distribuir e
  sublicenciar. Com o repositório privado, nada foi concedido a ninguém — a
  contradição vira real no dia em que o código for para um terceiro.
  Trocar por nota proprietária é decisão do titular.
- **P-09** — enquadramento regulatório do apoio diagnóstico. Bloqueia M3.
- **TUSS incompleta**: ~3.200 de ~5.900 procedimentos. Ela se retoma
  sozinha de hora em hora desde 02/10; antes disso o laço morria a cada
  deploy.
- O `CLAUDE.md` lista parte dos 100 roteiros ("os mais relevantes") e 4 views
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

**Isolamento entre inquilinos não termina no servidor.** Em 2026-10-05,
em uso real, uma secretária com vínculo em duas clínicas trocou de
organização e continuou vendo o logotipo da anterior. O banco estava
certo, o disco estava certo e o servidor respondeu com a imagem certa nas
duas: o que mostrou a clínica errada foi o cache do **navegador** —
mesma URL (`/app/org/clinica/logotipo.img`, que não aceita id de
organização, de propósito), mesmo cookie (trocar de organização escreve
na mesma sessão), e um `max-age=300` prometendo o que o servidor não
podia cumprir. A revisão de isolamento tinha examinado o cache do Django
e concluído, corretamente, que nada vazava por ali; o cache que falhou
não é nosso e não aparece numa busca por `cache.set`. A regra que ficou:
**prazo fixo de cache só quando a própria URL diz o que ela devolve.**
Ver `docs/homologation/logotipo-por-organizacao.md` e `check_logotipo.py`.

**Um teste que não falha com o defeito presente não é teste.** Quatro
ocorrências: roteiro lendo a própria legenda; roteiro de paginação sem
volume; asserção casando com ícone decorativo; e um roteiro que passava
em dois dias da semana e reprovava nos outros cinco. O último é o pior:
ensina quem lê a ignorar o vermelho.

**Consumidor novo herda a história inteira do tópico, e mensagem a
pessoa não pode herdar nada.** Em 2026-10-07, o consumidor do aviso de
horário entrou no ar e encontrou 48 eventos `appointment_reserved`
pendentes **desde sempre** — o dispatcher deixa evento sem consumidor
pendente de propósito, para que "um deploy futuro possa registrar", e
isso está certo para integração de dados: um CRM que chega depois quer o
histórico. Está errado para e-mail: dez mensagens saíram à 01h15
dizendo "sua consulta está marcada", sobre consultas já realizadas e
canceladas. Quatro foram para pacientes reais.

A lição, que vale para todo consumidor novo que escreva para gente:
**perguntar a idade do evento antes de agir**. Ver `JANELA_DO_AVISO` em
`communications/handlers.py`.

**Provar não é concluir, e a diferença custou dezessete mensagens.** Em
2026-10-07, ao *provar* que o SMS funcionava — perguntando ao provedor
em vez de ler o nosso próprio registro —, apareceram dois defeitos que
nenhuma leitura de código teria achado: a confirmação de entrega era
lida com a forma errada (o provedor manda uma lista; esperávamos um
objeto com `items`), e o botão de testar a chave consultava saldo no
endereço de envio. Os dois eram código escrito contra esquema
**suposto**, e os dois docstrings diziam isso — a pendência P-03 existia
exatamente por não haver conta viva para conferir. Hoje há, e está
conferido. Lição: enquanto houver "não deu para homologar contra conta
real" escrito num docstring, aquele código é suposição com cara de
implementação.

**O padrão da instalação é um caminho sem dono, e foi onde doeu três
vezes.** Em 2026-10-05 e 06 apareceram três defeitos com a mesma
assinatura: só são exercitados por quem **não** configurou o seu próprio
— o logotipo que vinha do cache da clínica anterior, a IA apontando para
um modelo que o fornecedor aposentou em 26/08 (quarenta dias de `410
Gone`, sem alarme), e a confirmação de horário por SMS saindo de dentro
da requisição, onde o secret do SMSDEV não existe. Nos três, a primeira
clínica nunca viu nada: ela tem logotipo, chave de IA e chave de SMS
próprias. A lição é onde procurar o próximo: **o que a primeira clínica
nunca exercita.** Ver `docs/homologation/padrao-da-instalacao.md`.

**Validação rígida demais descarta o trabalho certo.** Em 2026-10-05 uma
leitura de laudo pela IA foi recusada inteira — trinta e um analitos
transcritos corretamente — porque `unreadable_sections`, o campo onde o
modelo diz o que **não** conseguiu ler, voltou `[]` em vez de `""`. Um
erro de validação, num campo vazio, anulando o artefato todo. A lição
não é "valide menos": é que **forma** (como o modelo serializou) e
**conteúdo** (o que o prontuário exige) são coisas diferentes e estavam
sob a mesma régua. A forma passou a ser normalizada; as guardas clínicas
seguem intactas e agora têm roteiro provando que seguem. Ver
`docs/homologation/leitura-de-laudo-por-ia.md` e o §7-F do `CLAUDE.md`.

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
- **Bateria morta no meio deixa resíduo, e o resíduo reprova outro
  roteiro.** Cada roteiro limpa o que criou no fim; morto antes do fim, o
  que ficou no banco é paciente, atendimento e documento que o roteiro
  seguinte não consegue apagar (`ProtectedError`) ou que o faz contar
  errado. O sintoma é inconfundível: **falhas diferentes a cada rodada**.
  Aconteceu em 04/10/2026, quando o Docker Desktop caiu por falta de
  memória no meio da bateria — duas rodadas seguintes reprovaram
  `check_admin`+`check_g6` e depois `check_mes_e_estatisticas`, e os três
  passavam sozinhos. A cura é `docker compose down -v`, `seed_demo` e
  `import_cmed`; e é também a única bateria em que se pode acreditar.

## 6. Onde está o resto

| Assunto | Arquivo |
| --- | --- |
| Mapa do sistema, convenções | `CLAUDE.md` |
| Decisões e pendências com dono | `docs/decisions.md` |
| Homologação por funcionalidade | `docs/homologation/` |
| Operação, deploy, backup | `docs/operations/` |
| LGPD | `docs/governance/lgpd.md` |
| Especificação completa | `PRD.md` |
