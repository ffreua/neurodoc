# Diário do primeiro deploy — 25 e 26 de setembro de 2026

O que foi feito para pôr o NeuroDoc no ar pela primeira vez, na ordem em
que aconteceu, e **o que deu errado**. Esta última parte é a razão de o
arquivo existir: o passo a passo já está em `primeiro-deploy.md`, e o que
nenhum passo a passo carrega é a lista dos lugares onde ele não bate com a
realidade.

| | |
| --- | --- |
| Servidor | VPS na **Integrator**, Ubuntu 24.04.5, 6 vCPU, 16 GB |
| Domínio | `neurodoc.app.br`, DNS na Cloudflare, registros **cinza** (sem proxy) |
| E-mail | `contato@neurodoc.app.br`, Hostinger — só o e-mail é Hostinger |
| Usuário de operação | `<usuario>` (e não `neurodocops`, como o roteiro supõe; o nome fica fora do repositório público) |
| Projeto em | `/srv/neurodoc` |
| Release no ar | `205c5c79` · produto **1.0** |

---

## 1. O que foi feito, na ordem

**Preparação do servidor.** `sudo` sem senha para o usuário de operação; utilitários
(inclusive o `age`, que o backup exige); fuso `America/Sao_Paulo`;
`fail2ban` com jail de SSH; swap de 4 GB; UFW liberando só 22, 80 e 443;
*tuning* de produção no `sysctl`; Docker 29.8.1 com `daemon.json` de
produção; Swarm iniciado; rótulo `neurodoc_data=true`; as três redes
overlay com o isolamento conferido (`false` / **`true`** / `false`); tmpfs
das chaves de assinatura.

**Segredos.** Os 15 do `docker-stack.yml`: seis aleatórios, as duas
chaves-mestras Fernet (44 caracteres, conferidos), quatro fornecidos
(Cloudflare, SMTP, NVIDIA, SMSDEV) e três `DISABLED`.

**Publicação.** `git clone` por HTTPS com token, `.venv-ops`, login no
`ghcr.io`, `.env`, registro de homologação, preflight, `deploy.sh`.
Certificado de teste primeiro, de produção depois.

**Pós-deploy.** Superadministrador com MFA; convite da clínica-sede
(plano `custom`); CMED importada (26.242 apresentações); timers de backup
e de limpeza de chaves; primeiro backup provado.

---

## 2. Os defeitos que o deploy real encontrou

Seis, e nenhum deles aparecia em ambiente de desenvolvimento.

| Commit | Defeito | Onde doía |
| --- | --- | --- |
| `a7d8132` | Cloudflare recusa o User-Agent padrão do `urllib` | Deploy morria com `HTTP 403` **depois** de 20 min de build e do push |
| `2ded652` | `docker stack deploy` ignora a chave curta `tmpfs:` | Worker em laço; e o `app` ficava `healthy` **sem `/tmp` gravável** |
| `8880b87` | Ninguém criava `/srv/neurodoc-backups` | Backup falharia às 03:00 toda noite, no journal, em silêncio |
| `e6918bf` | O gerador do ambiente local não acompanhou o `2ded652` | `KeyError` — ninguém mais subiria o ambiente de desenvolvimento |
| `c1d6f80` | 404 para quem não confirmou o e-mail | Primeira tela depois de entrar era um "Not Found" cru |
| `bb1e4d8` | 403 sem estilo ao sair e entrar na mesma aba | Página crua do Django, sem explicação nem saída |

**O `2ded652` é o que vale reler.** O `app` **passava no healthcheck**:
servir HTML não toca `/tmp`. O deploy ficava verde, o sistema parecia
perfeito, e a falha esperaria o primeiro anexo de exame, OCR, exportação
ou receita assinada. Quem denunciou foi o Celery reiniciando em laço,
porque o `billiard` precisa de `/tmp` só para nascer.

O padrão dos seis é o mesmo, e é o que este diário quer registrar: **a
falha longe da causa**. Nenhum apareceu onde foi escrito.

---

## 3. O incidente da chave de backup

Perdemos a primeira chave privada do backup, e vale saber como.

Os dois comandos foram dados **juntos**: um que copiava a chave para o PC
e outro que a apagava do servidor. O primeiro falhou — o PowerShell estava
em `C:\WINDOWS\System32`, onde o Windows não deixa gravar — e o segundo
rodou assim mesmo. A chave sumiu, e com ela o backup daquela noite.

Não houve prejuízo: o banco tinha um usuário e nenhum paciente. Mas a
lição vale o susto: **comando que apaga nunca vai colado no que copia.**
Copiar, conferir que chegou, e só então apagar. Foi assim que o par
seguinte foi feito.

---

## 4. Duas decisões de produto tomadas aqui

**Preço por tipo de atendimento** (`205c5c7`). A agenda sempre distinguiu
primeira consulta, seguimento e retorno; o honorário não. O tipo entrou no
`FeeSchedule` como a dimensão **menos** significativa da cascata: ele
desempata dentro de uma combinação de médico/plano/procedimento e nunca
vence uma mais específica. No topo, "primeira consulta" ganharia de "plano
X" e a clínica cobraria o particular de uma paciente com convênio.

**Os roteiros não rodam contra produção.** São 54, e `rodar_roteiros` não
tem trava de ambiente: 17 deles criam clínica, paciente e usuário sem
apagar. O lugar deles é o ambiente local, antes do deploy. Contra a
instalação real só entra verificação somente-leitura.

---

## 5. O primeiro drill de restauração — 26/09

Feito na **máquina de trabalho**, não na VPS: um backup restaurado no
mesmo servidor que o gerou não prova nada, porque um incêndio leva os dois
juntos. Usou o backup do **timer**, não um feito à mão.

Voltaram: 109 migrations, a clínica com plano e estado corretos, as
contas, CID-10 (14.233) e CMED (26.242), e a última migration publicada —
o backup automático pegou o esquema de depois do deploy do dia. O aceite
do contrato voltou com a cópia integral do texto, e o SHA-256 recalculado
dela bate com o hash gravado.

O drill encontrou sete pré-condições que `restore.md` não listava. Estão
lá agora.

---

## 5-A. A bateria de verificação estava muda fora do ambiente local

Descoberto ao montar um ambiente de prova na própria VPS, com a
configuração de produção: **40 dos 56 roteiros falhavam**, e quase todos
pelo mesmo motivo bobo. O cliente de teste do Django fala HTTP; com
`DEBUG=False`, `SECURE_SSL_REDIRECT` devolve `301` para tudo, e o roteiro
passava a medir o redirecionamento em vez da tela. As asserções falhavam
por `301` — o que parece defeito no código testado, e manda quem
investiga para o lugar errado.

Cada roteiro que usa o cliente de teste passou a declarar
`SECURE_SSL_REDIRECT = False` junto do `ALLOWED_HOSTS` que ele já
declarava. No ambiente local, onde `DEBUG=True`, a linha não muda nada.

| | |
| --- | --- |
| Antes | 40 falhas de 56 — 29% passando |
| Depois | **8 falhas de 57 — 86% passando**, zero regressões |

**Por que isso vale o trabalho.** A rede de proteção existia e estava
desligada em quase todo lugar onde seria usada: só o ambiente local
completo a acionava, e ele exige uma máquina que aguente um build de vinte
minutos. Com a correção a bateria roda em qualquer ambiente descartável —
que é como esta sessão pegou o `AttributeError` do motor de preço (que
quebraria a primeira consulta finalizada) e o `g-5` sem variante
responsiva (que quebrava a página de vendas no celular).

**As 8 que sobram são dado de catálogo, não produto**, e ficam registradas
para não serem reinvestigadas: `check_receitas` precisa da CMED importada;
`check_codigos` precisa do CID-10 completo, e o `seed_demo` cria só um
subconjunto; as demais dependem de estado que a subida real monta e um
ambiente efêmero não tem. `check_chave` estava entre elas por culpa do
ambiente — as duas chaves-mestras tinham sido geradas com o mesmo valor, e
o roteiro existe exatamente para acusar isso. Corrigido o ambiente, passou.

## 6. O que fica em aberto

> **Em 2026-10-22**, esta tabela é a de setembro. Desde então: HSTS ligado
> (2026-10-02, com subdomínios), proxy da Cloudflare ligado com a origem
> fechada às faixas dela (2026-10-19), TUSS parcial e se retomando de hora
> em hora; o `--activate` segue sem ter sido feito. O estado corrente está
> em `docs/ESTADO-ATUAL.md`.

| | |
| --- | --- |
| **TUSS** | Vazia. A API da ANS não respondeu em nenhuma tentativa. O timer refaz aos domingos às 4h. Não bloqueia: CID-10 e CMED estão completos |
| **HSTS** | `SECURE_HSTS_SECONDS=0`. Ligar só depois de alguns dias de uso — o navegador guarda a instrução por um ano e não há como voltar atrás pelo servidor |
| **`--activate`** | A outra metade do drill, que mede o tempo de volta ao ar (RTO). Exige as chaves-mestras reais numa máquina separada; só vale quando houver dado real |
| **`accepted_name` vazio** | O aceite do contrato guardou e-mail, IP e texto, mas não o nome de quem aceitou. Veio assim da produção — vale conferir o formulário |
| **Proxy da Cloudflare** | Desligado (nuvem cinza). Ligá-lo esconde o IP do servidor, mas o proxy costuma bufferizar SSE, que é o que o chat da equipe e o streaming da IA usam |

### Verificação da TUSS em 28/09/2026

A tabela continua vazia, mas a fronteira da falha está comprovada. Do worker
de produção, `/ANS/source` respondeu HTTP 200 em 0,63 s, enquanto
`/ANS/concepts/tuss-22?page=1` excedeu 35 s. A tentativa automática de domingo
registrou a mesma falha depois das quatro repetições previstas. Portanto a VPS
tem DNS e egresso normais; é o endpoint de conceitos da **ANS** que permanece
indisponível. TUSS é ANS; a Anvisa é a fonte da CMED de medicamentos.

---

## 7. Consolidação da v1.0 — 29/09/2026

A captura local por scanner foi retirada por decisão de produto (DEC-53).
Saíram agente, serviços, rotas, telas, menu e artigo próprio da ajuda. O
percurso vigente é simples: a clínica digitaliza no software do equipamento
ou do sistema operacional e envia o arquivo pronto em **Anexos**. As tabelas
antigas não foram apagadas: permanecem somente leitura para preservar
proveniência sem uma migration destrutiva.

A mesma consolidação acrescentou o **exame neurológico em texto livre** ao
atendimento estruturado e passou a mostrar, na agenda mensal, cada vaga livre
em verde e cada horário ocupado em vermelho. A semana escreve “Livre” e a
hora dentro da própria célula.

Por decisão explícita, esta entrega ainda é **v1.0**. O número fica no
programa (`base/version.py`) e a próxima atualização funcional começa em
**v1.1**; a política completa está em `docs/operations/versionamento.md`.
