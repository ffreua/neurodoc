# Auditoria Pré-Deploy — NeuroDoc 1.0

**Data:** 2026-09-24 · **Revisão auditada:** `00e094e` + correções desta auditoria
**Escopo:** repositório inteiro (826 arquivos versionados, ~113 mil linhas)

---

## Leia isto antes do resto

Esta auditoria combinou duas fontes, e o documento **as mantém separadas de
propósito**:

1. **Verificação determinística**, feita diretamente — varreduras de código,
   execução dos 52 roteiros, testes em navegador e em contêiner. É prova.
2. **Varredura assistida por 19 auditores automáticos**, cada um com uma
   dimensão. Produziu 81 achados brutos.

**Nenhum achado automático entrou neste relatório como fato sem eu ter
aberto o código e confirmado.** O que confirmei está na §5–§8 com a
evidência. O que não deu tempo de confirmar está na §25, marcado como **não
verificado** — e não deve ser tratado como defeito até que alguém o confirme.

As duas primeiras rodadas foram interrompidas pelo limite de uso da sessão.
**As 19 dimensões foram completadas numa terceira rodada** (2026-09-25):
19 auditores, 116 achados brutos, 277 arquivos lidos só nas cinco últimas.
O que continua valendo é a regra do parágrafo acima — 13 achados verificados
por mim, 103 não; a §25 separa os dois.

---

## 1. Resumo executivo

O sistema está **bem construído**. A varredura determinística não encontrou
nenhum dos defeitos que costumam aparecer num pré-deploy: zero SQL cru, zero
`mark_safe`, zero segredo versionado, zero divergência de caixa entre Windows
e Linux, zero migration pendente, zero erro de sintaxe em 479 arquivos, e os
52 roteiros de verificação passam inteiros.

Os defeitos que apareceram estão nas **bordas** — no que sai do sistema, no
que entra por um campo de texto, e no que acontece fora do horário comercial.
Oito foram confirmados com prova e corrigidos:

| # | Defeito | Severidade | Estado |
| --- | --- | --- | --- |
| 1 | Alerta de erro por e-mail levava as senhas do Redis e do RabbitMQ em texto claro, e o nome do paciente da busca | **CRÍTICO** | corrigido e verificado |
| 2 | Texto clínico era silenciosamente alterado no PDF assinado (`T < 38` sumia) | **ALTO** | corrigido e verificado |
| 3 | XSS armazenado pelo nome do paciente na lista do chat de IA | **ALTO** | corrigido e verificado |
| 4 | `age` nunca instalado na VPS: a cópia de segurança cifrada não roda | **ALTO** | corrigido |
| 5 | `/admin/login/` sem limitador de tentativas | **ALTO** | corrigido |
| 6 | As duas entradas de dinheiro sem validação: `150,00` devolvia 500, e `NaN` era aceito | **ALTO** | corrigido e verificado |
| 7 | Exportação do acervo clínico: a capacidade valia para pedir e não para **baixar** | **ALTO** | corrigido e verificado |
| 8 | Data do sistema lida em UTC: das 21h à meia-noite, financeiro e painel abriam no dia errado | **MÉDIO** | corrigido e verificado |

Dois achados confirmados **não** foram corrigidos porque a correção muda
regra de negócio — estão marcados como `DECISÃO DE NEGÓCIO NECESSÁRIA` (§9).

**Status:** ver §27.

---

## 2. Arquitetura identificada

```
Navegador → Traefik (TLS, Let's Encrypt) → Django ASGI (uvicorn) → PostgreSQL 17
                                                  ↓
                                        RabbitMQ → Celery worker → PostgreSQL
                                                        ↓        ↘ IA / SMTP / SMSDEV / TUSS
                                                     Redis → SSE de volta ao app
```

Monólito modular Django, SSR com Django Templates. Sete serviços permanentes
(`app`, `celery_worker`, `celery_beat`, `db`, `rabbitmq`, `redis`, `traefik`)
em Docker Swarm.

**Multi-inquilino em três camadas**, e esta é a decisão que organiza o resto:
`TenantMiddleware` (atua só em `/app/`), `AccessContext` (imutável, reconstruído
do banco a cada requisição) e uma matriz de capacidades em código. No banco, o
isolamento é reforçado por chave estrangeira composta `(tenant_id, id)` — mas
**só em `clinical` e `teamchat`**; nos demais apps o que separa é o filtro por
inquilino em cada consulta.

**Regra de rede que explica muito código:** em produção o processo `app` não
tem saída para a internet; quem alcança é o worker. Por isso e-mail, SMS, IA e
TUSS saem sempre por tarefa Celery.

## 3. Tecnologias e versões

| Camada | O quê |
| --- | --- |
| Linguagem | Python 3.14.7 |
| Framework | Django 6.1.1 |
| Banco | PostgreSQL 17 (extensão `btree_gist`) |
| Fila | Celery 5.6.3 + RabbitMQ |
| Cache / SSE | Redis |
| Proxy | Traefik + Let's Encrypt |
| Frontend | **Vanilla** — sem `package.json`, sem build, sem TypeScript |
| Dependências | 125 pacotes fixados por versão **e hash** (`--require-hashes`) |
| PDF / assinatura | ReportLab + pyHanko (PAdES) |
| Antivírus / OCR | ClamAV, Tesseract (pt) |

**Inventário:** 479 `.py` (55.860 linhas), 126 `.html` (18.030), 16 `.js`
(5.542), 8 `.css` (16.459), 60 `.md` (14.498). 236 rotas, 102 models, 213
views, 14 tarefas Celery, 86 migrations, **52 roteiros de verificação**.

## 4. Fluxos críticos

| # | Fluxo | Onde vive |
| --- | --- | --- |
| 1 | Cadastro por convite → aceite do contrato → clínica criada | `tenancy/invitations.py`, `contract.py` |
| 2 | Login → MFA → escolha de organização → `/app/` | `accounts/`, `tenancy/context.py` |
| 3 | Cadastrar paciente (com trava de plano) | `patients/`, `tenancy/limits.py` |
| 4 | Marcar consulta (sem sobreposição) | `scheduling/services.py` |
| 5 | Atender: prontuário estruturado ou texto livre → finalizar | `clinical/` |
| 6 | Emitir documento → assinar PAdES → entregar por link opaco | `documents/`, `communications/` |
| 7 | Verificação pública do documento pelo QR (na farmácia) | `documents/verification.py` |
| 8 | Portal do paciente: pedido sem conta, com janela de 180 dias | `documents/portal*.py` |
| 9 | Finalizar atendimento → evento → recebível | `events/`, `finance/handlers.py` |
| 10 | Exportar o acervo (MD/JSON), expira em 24 h | `reporting/acervo.py` |
| 11 | Backup cifrado com `age` → restauração | `ops/backup.py`, `ops/restore.py` |
| 12 | Deploy por SHA, com preflight e rollback | `ops/deploy.py` |

---

## 5. Problemas críticos encontrados

### C-01 · O alerta de erro por e-mail levava segredos e dado de paciente

| | |
| --- | --- |
| **Arquivo** | `core/settings.py:333` (handler), `base/logging.py` |
| **Severidade** | **CRÍTICO** — corrigido e verificado |

**O problema.** Com `ALERT_ADMIN_EMAILS` preenchido, todo 500 não tratado faz
o `AdminEmailHandler` do Django mandar um relatório por SMTP. Medido antes da
correção: **16.876 caracteres**, contendo o despejo dos **206 settings**.

**Por que vazava.** A filtragem do Django decide pelo **nome** do setting
(`API|TOKEN|KEY|SECRET|PASS|SIGNATURE`). As senhas de infraestrutura moram
**dentro da URL de conexão**, em settings cujo nome não casa com nenhum desses
termos:

```python
REDIS_BASE       = f'redis://:{senha}@redis:6379'
CELERY_BROKER_URL = f'amqp://neurodoc:{senha}@rabbitmq:5672/neurodoc'
```

O `RedactSensitiveDataFilter` que existia não alcança isso: ele age sobre a
mensagem do registro de log, e o corpo do e-mail é montado à parte, pelo
`ExceptionReporter`.

**Impacto.** Senha do Redis e do RabbitMQ em texto claro, por SMTP, para a
caixa de quem opera o servidor — a cada erro não tratado. Junto ia a URL
inteira e o `QUERY_STRING`, e **a busca de paciente é por query string**
(`/app/patients/?q=Carlos`): nome de paciente por e-mail.

**Reprodução (medida, não suposta).**
```
Redis em claro no corpo    : True
RabbitMQ em claro no corpo : True
termo de busca "Carlos"    : True
```

**Correção.** Três mudanças em `base/logging.py`, cada uma fechando uma saída:

1. `cleanse_setting` passa a esconder pelo **valor** (`esquema://user:senha@`)
   e não pelo nome — assim um setting novo com credencial já nasce escondido;
2. `NoQueryStringExceptionReporter` (novo, ligado por `DEFAULT_EXCEPTION_REPORTER`)
   suprime a query string da `Request URL` e da seção `GET`;
3. `get_safe_request_meta` suprime `QUERY_STRING`, onde o mesmo texto reaparecia.

**Resultado após a correção** (mesma medição): as três linhas viram `False`, e
o caminho da tela continua no relatório — sem ele o alerta não serviria.

**Teste:** `checks/check_alerta_erro.py` (novo, 6 seções).

> **Nota de método.** A primeira tentativa de correção escreveu
> `get_traceback_data` na classe do *filtro*, onde ele não existe: virou
> método que ninguém chama. Só a medição do corpo do e-mail denunciou. Está
> registrado no comentário da classe.

---

## 6. Problemas de alta prioridade

### A-01 · Texto clínico silenciosamente alterado no PDF assinado

| | |
| --- | --- |
| **Arquivo** | `documents/pdf/common.py` + `prescription.py`, `referral.py`, `report.py`, `request.py` |
| **Severidade** | **ALTO** — corrigido e verificado |

**O problema.** `reportlab.platypus.Paragraph` não recebe texto puro: recebe a
mini-linguagem de marcação do ReportLab (`<b>`, `<font>`, `<br/>`, `<img/>`).
Todo valor de banco entrava nela por f-string, **sem escape nenhum** — `grep`
por `escape` em `documents/pdf/*.py` não devolvia nada.

**Medido gerando PDF de verdade e extraindo o texto com `pdftotext`:**

| Digitado | Saía no PDF |
| --- | --- |
| `Ana <x> Souza` | `Ana Souza` — o trecho **sumiu** |
| `Ana <b>Paula</b> Souza` | em negrito, tags consumidas |
| `<font color="white">SEGREDO</font>` | renderizado invisível |

**Impacto — e por que é pior que uma falha.** Um médico escrevendo
`Usar se T < 38` ou `dor > 7/10` na receita perde tudo até o próximo `>`. O
documento é então **assinado em PAdES** e entregue: a via que a farmácia retém
fica diferente do que foi prescrito, sem nada avisar. Isso é integridade de
documento médico, não estética.

**Correção.** Dois helpers em `common.py` — `texto_seguro()` (escapa) e
`paragrafo_de_texto()` (escapa **e depois** converte a quebra de linha em
`<br/>`, nessa ordem; invertida, o `<br/>` também seria escapado). Aplicados
nos 14 pontos de interpolação. A marcação que o módulo escreve de propósito
continua valendo, porque é concatenada depois do escape.

**Verificação (PDF real, texto extraído):** `T < 38 C`, `dor > 7/10` e
`Ana <x> Souza` aparecem **literais**; `<b>` e `<font>` não são mais aplicados;
a quebra de linha deliberada continua funcionando.

---

### A-02 · XSS armazenado pelo nome do paciente

| | |
| --- | --- |
| **Arquivo** | `static/ai/chat-shell.js:94,129` e `static/catalogs/search.js:11,21` |
| **Severidade** | **ALTO** (chat) / **MÉDIO** (catálogo) — corrigidos e verificados |

**O problema.** Os dois arquivos montavam marcação por concatenação e passavam
o valor por um `escapar()` escrito assim:

```js
var div = document.createElement('div');
div.textContent = texto;
return div.innerHTML;          // escapa & < >  —  NUNCA " nem '
```

A serialização de um nó de texto não escapa aspas, porque aspa só precisa de
escape dentro de atributo. E o retorno era colado **justamente dentro de um
atributo**: `'data-nome="' + escapar(p.full_name) + '"'`.

**Cadeia confirmada, elo por elo:**
- `patients/forms.py::clean_full_name` (279-283) só faz `strip()` — aspa passa;
- `PatientAutocompleteView` devolve `full_name` cru no JSON;
- **não há CSP global** — as duas únicas linhas de `Content-Security-Policy`
  do projeto estão em respostas de imagem;
- a tela do chat **não confere `AI_ENABLED`**: ela abre nesta release.

Quem grava o nome é a secretária; quem executa é o médico que abre a lista.

**Prova em navegador real (Chromium):**

```
ANTES : atributos=['data-nome', 'onmouseover']   onmouseover=True
DEPOIS: atributos=['data-nome']                  onmouseover=False
```

**Correção.** O helper passa a escapar `"` e `'` — a menor alteração que
fecha o contexto de atributo nos dois arquivos, sem reescrever a montagem.

**Teste:** `checks/check_js_atributo.py` (novo). Ele distingue **marcação** de
**seletor CSS** — sem essa distinção acusava `duralux/app.js` e
`patients/patient_form.js`, que só montam seletor, e um roteiro que acusa o
inocente é desligado na primeira vez que atrapalha.

> **Varredura completa:** conferi os 16 arquivos `.js`. Exatamente dois
> montavam atributo de marcação por concatenação; os outros usam
> `createElement`/`textContent`.

---

### A-03 · A cópia de segurança cifrada não roda: `age` nunca é instalado

| | |
| --- | --- |
| **Arquivo** | `scripts/setup_deploy.sh:297` |
| **Severidade** | **ALTO** — corrigido |

`ops/backup.py:30` executa `subprocess.run(['age', '-r', destinatário], ...)`
para cifrar o dump e os volumes. O roteiro que prepara a VPS instala
`curl git htop iotop net-tools unzip jq ca-certificates`, `fail2ban` e
`python3-venv` — **`age` não está na lista.**

**Impacto.** Numa VPS preparada por este roteiro, o timer noturno estoura com
`FileNotFoundError` na primeira madrugada. O alerta que faltaria seria
justamente o de que **não há backup** — num sistema com guarda legal de 20
anos (Lei 13.787/2018).

**Correção.** `age` entra na lista, e o roteiro **para** se ele não estiver
disponível na distribuição (Debian 11 e derivados antigos não o têm),
apontando o release oficial. Parar ali é melhor que descobrir na primeira
madrugada: o passo seguinte configura o backup, e configurá-lo sem o cifrador
é escrever um timer que nunca vai funcionar.

---

### A-04 · `/admin/login/` sem limitador de tentativas

| | |
| --- | --- |
| **Arquivo** | `base/admin.py`, `accounts/forms.py` |
| **Severidade** | **ALTO** — corrigido (rebaixado de CRÍTICO, ver abaixo) |

`/accounts/login/` conta tentativa errada, aplica atraso progressivo e bloqueia
(`accounts/throttling.py`, via `ThrottledAuthenticationForm`). `/admin/login/`
usa o formulário do próprio Django e **não passava por nada disso**.

**O que confirmei — e o que refutei.** O auditor automático classificou como
CRÍTICO ("segunda porta de login sem MFA"). **Testei:**

```
POST /admin/login/ com usuário comum e senha CORRETA -> autenticado: False
```

`AdminAuthenticationForm` recusa quem não é `is_staff`, e
`TechnicalAdminSite.has_permission` exige `is_superuser` **e** `is_verified()`
(MFA). O mesmo vale para `/instalacao/`. **Não é entrada franca.**

O que sobra, e é real: a senha do **superadministrador** — a única conta que
abre `/instalacao/` e os painéis técnicos — podia ser tentada sem limite e sem
deixar rastro na trilha.

**Correção.** `ThrottledAdminAuthenticationForm` herda dos dois formulários: o
`clean` com limitador vem de um, a recusa de quem não é `is_staff` vem do
outro. Mora em `accounts/forms.py` e é resolvido por propriedade em
`base/admin.py` — importá-lo no topo daquele módulo derruba o processo com
`AppRegistryNotReady`, porque `AdminConfig` o carrega **durante** a carga dos
apps. (Descoberto quebrando o boot e consertando.)

---

### A-05 · As duas entradas de dinheiro não validavam nada

| | |
| --- | --- |
| **Arquivo** | `finance/views.py:67-103`, `finance/pricing.py::quantize_brl` |
| **Severidade** | **ALTO** — corrigido e verificado |

`RecordPaymentView` e `ApplyAdjustmentView` — as duas únicas rotas que lançam
dinheiro no produto — liam `request.POST.get('amount')` e entregavam o texto
cru a `quantize_brl`, que faz `Decimal(valor)`. As views capturavam
`except ValueError`, e **`decimal.InvalidOperation` herda de `ArithmeticError`,
não de `ValueError`**.

Medido, chamada a chamada:

| Digitado | Resultado |
| --- | --- |
| `150,00` — o jeito brasileiro | `InvalidOperation` → **500** |
| campo vazio | `InvalidOperation` → **500** |
| campo ausente | `TypeError` → **500** |
| `1e999` | `InvalidOperation` → **500** |
| `NaN` | **passava**, e viraria um pagamento NaN no banco |
| 14 dígitos | passava, e estouraria o `numeric(12,2)` no `INSERT` |

O resto do produto já fazia certo: `finance/fee_forms.py` usa `DecimalField`
com limites, e o cadastro de paciente usa `BrazilianDecimalField` justamente
porque "quem digita peso digita com vírgula". Estas duas rotas ficaram de
fora — e são as que mexem em dinheiro.

**Correção.** `finance/forms.py` (novo): `PaymentForm` e `AdjustmentForm`
sobre o `BrazilianDecimalField` que já existia, com `max_digits=12,
decimal_places=2` — exatamente as colunas. O tipo do ajuste passou a
`ChoiceField`, o motivo virou obrigatório (ele vai para a trilha), e a forma
de pagamento ganhou o limite da coluna.

**Teste:** `checks/check_dinheiro.py` (novo, 6 seções).

---

### A-06 · A capacidade da exportação valia para pedir, não para baixar

| | |
| --- | --- |
| **Arquivo** | `reporting/views.py:137-148, 189-205` |
| **Severidade** | **ALTO** — corrigido e verificado |

O projeto declara a capacidade **por relatório** (`reporting/apps.py`), e
`CLAUDE.md` explica por quê: o nome do relatório chega pelo POST, então a
verificação mora em `request_export` e não na view. O acervo clínico exige
`MANAGE_ORGANIZATION` **e** `READ_CLINICAL`.

O que faltou: a lista de exportações recentes e o download eram escopados
**apenas por inquilino**. Um dono que não é médico não conseguia *pedir* o
acervo clínico — mas via na lista o arquivo que um médico pediu, e podia
baixá-lo. É o prontuário de todos os pacientes num arquivo só.

**Correção.** `reporting/services.py::pode_ver_export` responde a pergunta
num lugar só, e as três portas passaram a usá-la: a lista mostra apenas o
que o vínculo poderia baixar, e detalhe e download devolvem 404. Relatório
fora do catálogo não é baixável por ninguém — uma linha órfã no banco não
vira arquivo aberto.

**Teste:** seção nova em `checks/check_exportacao.py`, que cobra que "pode
pedir" e "pode baixar" concordem para **todos** os vínculos da clínica.

---

## 7. Problemas médios

| # | Arquivo | Problema | Estado |
| --- | --- | --- | --- |
| M-01 | `ai/admin_views.py:214,291` | **SSRF**: `base_url` do provedor de IA vem do POST sem validação de esquema ou destino, e é chamado a partir do processo `app` | confirmado · §9 |
| M-02 | `documents/retention.py:88` | `garbage_collect` só é chamado por `checks/check_backup.py` — **nunca roda em produção** | confirmado · §9 |
| M-03 | `tenancy/admin_views.py:373` | `PhysicianProfile` é global por usuário: o responsável da clínica A editar o CRM reflete na clínica B e zera a verificação lá | confirmado, severidade rebaixada |
| M-04 | `requirements.txt` | `cryptography 48.0.1` (3 avisos) e `pymdown-extensions 10.21.3` (2 avisos) | ver §13 |
| M-05 | `finance/views.py`, `reporting/views.py`, +4 | **Data lida em UTC.** O contêiner roda em `Etc/UTC` e o produto em `America/Sao_Paulo`: das 21h à meia-noite `date.today()` já devolve o dia seguinte. O período padrão do financeiro e do painel abria em "amanhã" — e no último dia do mês, já no mês seguinte, com tudo zerado | **corrigido** (`timezone.localdate()` nos 6 pontos) |
| M-06 | `integrations/capture.py:32` | `complete_pairing` não tem rota: o pareamento do scanner **não pode ser concluído por HTTP**. Só `checks/check_perimetro.py` o chama | confirmado · coerente com a pendência P-08 |
| M-07 | `scheduling/publishing.py:85` | `appointments_outside_rules` é definido e **nunca chamado**: o aviso de que encurtar a grade deixa consultas órfãs não existe na prática | confirmado |

**Sobre M-03 — o que o código faz certo.** Trocar o CRM **rebaixa a
verificação para PENDENTE** antes de gravar, e a comparação é feita *antes* do
`is_valid()` justamente porque `ModelForm` muta a instância — com comentário
explicando a armadilha. O auditor automático classificou como CRÍTICO
("escalonamento de privilégio"); **refutei**: sem verificação não se assina
documento. Sobra o efeito colateral entre clínicas, que é MÉDIO.

## 8. Problemas de baixa prioridade

Confirmados por mim, e deliberadamente **não corrigidos** — são de qualidade
de dado, não de correção:

| # | Arquivo | Problema |
| --- | --- | --- |
| B-01 | `patients/forms.py:318` | `clean_postal_code` só remove não-dígitos: um CEP de 3 dígitos é aceito e gravado |
| B-02 | `patients/forms.py:325` | `clean_birth_date` só barra o futuro: um nascimento em 1800 passa |
| B-03 | `documents/issuance.py:141` | O número do documento vem de `COUNT(*) + 1` e **não há `UNIQUE` em `document_number`**. Não é explorável hoje — `discard_document` recusa apagar documento emitido, e rascunho não tem número —, mas a constraint é seguro barato |
| B-04 | `templates/registration/password_reset_email.html` | Morto: o projeto sobrescreve `email_template_name`. **Deixado no lugar de propósito** — é o caminho padrão do Django, e removê-lo transforma um futuro `TemplateDoesNotExist` numa surpresa |

## 9. `DECISÃO DE NEGÓCIO NECESSÁRIA`

Dois achados confirmados cuja correção altera regra de negócio. **Não os
corrigi** — a escolha é sua.

### D-01 · SSRF pelo `base_url` do provedor de IA

O produto **documenta e oferece** servidor próprio (Ollama, vLLM) via
`base_url` — que, por definição, é um endereço de rede interna. Bloquear
faixas privadas fecharia o SSRF **e quebraria o caso de uso documentado**.

As opções, com o que cada uma custa:

| Opção | Fecha o SSRF | Mantém Ollama/vLLM |
| --- | --- | --- |
| Exigir `https://` e recusar faixa privada | sim | **não** |
| Lista explícita de hosts permitidos por instalação | sim | sim, com configuração |
| Manter como está | não | sim |

A mensagem de erro distinta por status (401/404/timeout) também dá um oráculo
limpo de varredura de porta interna. Mitigação parcial já em vigor: só
`MANAGE_INTEGRATIONS` alcança a tela, e o gate por plano (commit `00e094e`)
recusa o POST em planos sem IA.

### D-02 · Coleta de lixo do disco nunca executada

`garbage_collect()` é cuidadoso: idade mínima, respeita a guarda de 20 anos,
nunca toca arquivo ainda referenciado, segura a trava de backup e audita a
passagem. Ele foi **escrito para rodar** — e não roda: `beat_schedule` tem seis
tarefas e nenhuma é essa.

**Consequência hoje:** o arquivo de um anexo apagado pelo usuário permanece
legível em disco, para sempre, e o disco só cresce.

**Por que não liguei sozinho:** `dry_run=True` é o padrão da função, e
agendá-la com `dry_run=False` é autorizar apagamento permanente de arquivo
clínico. Isso é decisão do controlador, não do auditor. A mudança é de uma
entrada em `CELERY_BEAT_SCHEDULE` — me diga a periodicidade e eu faço.

---

## 10. Segurança

| Frente | Resultado |
| --- | --- |
| SQL injection | **Zero superfície.** 0 `.raw()`, 0 `RawSQL`, 0 `.extra()`. As 11 chamadas de `cursor.execute` são *advisory locks* do PostgreSQL, todas com parâmetro ligado |
| XSS em template | Apenas 2 `\|safe`, ambos alimentados por `ai/rendering.py::render_markdown`, que **escapa antes de converter** e neutraliza `javascript:`/`data:` em `href`/`src`. 0 `mark_safe`, 0 `format_html` |
| XSS no cliente | **2 defeitos encontrados e corrigidos** (A-02) |
| Injeção de marcação no PDF | **1 defeito encontrado e corrigido** (A-01) |
| Command injection | Nenhum `shell=True`, nenhum `os.system` |
| Path traversal | `documents/validators.py::sanitize_filename` usa lista branca; `ops/staticfiles.py` e `ops/docs.py` confirmam `is_relative_to` após `resolve()` |
| Injeção de fórmula em CSV | `reporting/exporters.py::sanitize_cell` cobre `= + - @ \t \r` |
| SSRF | **1 confirmado** (D-01) |
| CSRF | Django padrão; a única rota sem CSRF é o agente de captura, com credencial própria |
| IDOR / escopo por inquilino | O auditor leu 68 arquivos e **não achou um único `get_object_or_404(Model, id=...)` sem filtro de inquilino** nas views de `/app/`, nem `ModelForm` com `fields='__all__'` |
| MFA | Exigida em `/admin/`, `/instalacao/` e nos painéis técnicos (`is_superuser` **e** `is_verified()`) — confirmado lendo as três guardas |
| Limitador de login | Existia só na porta da frente; **corrigido** (A-04) |
| Segredos no repositório | **Nenhum.** `.gitignore` cobre `.env`, `.secrets/`, `*.pem`, `*.key`, `*.pfx`; nada versionado |
| Segredos no histórico | O `.env` do primeiro commit foi removido em `9241365` — e **todas as chaves sensíveis dele estavam vazias** (`SECRET_KEY=`, `DATABASE_URL=`, as três de IA). Conferido chave a chave, sem expor valor |
| Senhas | `AUTH_PASSWORD_VALIDATORS` com mínimo de 12 caracteres, similaridade, lista comum e numérica. Hash padrão do Django. Nenhuma senha em texto claro |

## 11. Banco de dados

| O quê | Resultado |
| --- | --- |
| Migrations pendentes | **Nenhuma** (`makemigrations --check --dry-run`) |
| Esquema do zero | **86 migrations aplicam sem erro** num PostgreSQL 17 limpo, após o `ops/postgres_init.sh` (papéis, `ALTER DEFAULT PRIVILEGES`, `btree_gist`) |
| Separação de papéis | `neurodoc_owner` cria; `neurodoc_app` só `SELECT/INSERT/UPDATE/DELETE`. `REVOKE CREATE ON SCHEMA public FROM PUBLIC` |
| Dinheiro | `DecimalField` em toda parte; nenhum `float` |
| Imutabilidade da trilha | Gatilho em `audit/migrations/0003_auditevent_imutavel.py` |
| Isolamento composto | `(tenant_id, id)` em `clinical` e `teamchat`; nos demais apps, filtro por inquilino |

**Ressalva de cobertura:** a dimensão `banco-esquema` (índices faltando,
`on_delete` inadequado, `unique` ausente) **não chegou a rodar** — §25.

## 12. Performance

Nove achados de N+1 e consulta cara vieram da varredura automática (§25).
**Nenhum foi confirmado por mim**, e nenhum foi medido. Não trate esta seção
como diagnóstico.

O que é fato: nenhum roteiro da bateria mede tempo, e não há teste de carga.
Para uma clínica nova — que começa vazia — isso não bloqueia o deploy; para a
clínica de 12.000 pacientes do plano Completo, é o primeiro lugar a olhar.

## 13. Dependências

`pip-audit` sobre os 125 pacotes fixados:

| Pacote | Versão | Avisos | Correção |
| --- | --- | --- | --- |
| `cryptography` | 48.0.1 | PYSEC-2026-3552/3553/3554 | 49.0.0 / 50.0.0 |
| `pymdown-extensions` | 10.21.3 | PYSEC-2026-3609/3654 | 11.0.0 / 11.0.1 |

**Não atualizei.** `cryptography` sustenta a assinatura PAdES (pyHanko) e a
cifragem de segredos (`base/crypto.py`): subir *major* sem exercitar a
assinatura de ponta a ponta é trocar um risco conhecido por um desconhecido na
véspera do deploy. **Recomendação:** subir `cryptography` para 49.0.0 e rodar
`check_receitas` + emissão real assinada, num ciclo próprio, antes ou logo
depois do deploy. `pymdown-extensions` só alimenta o MkDocs da documentação
técnica — risco baixo.

Pontos fortes: instalação com `--require-hashes` e `pip check` no `Dockerfile`.
Nenhuma dependência de frontend (sem `npm`, sem `package.json`).

## 14. Testes existentes

Não há suíte automatizada, por decisão registrada (DEC-20). O substituto são
**52 roteiros de verificação** em `checks/`, cada um tentando quebrar o
comportamento e saindo com código 1 ao falhar.

**Linha de base, antes de qualquer alteração minha:** 50 roteiros, **nenhuma
falha** (1.157 s).

## 15. Testes criados

| Roteiro | O que cobre | Seções |
| --- | --- | --- |
| `checks/check_js_atributo.py` | Dado do servidor colado em atributo HTML pelo JavaScript; distingue marcação de seletor CSS; confere que o nome do paciente **continua aceitando aspas** (a correção é na saída — recusar `O'Brien` na entrada não resolveria nada) | 5 |
| `checks/check_alerta_erro.py` | Segredo e PII no e-mail de alerta; inclui um caso que cria um setting novo com credencial para provar que a filtragem decide pelo **valor**, não por lista de nomes | 6 |
| `checks/check_dinheiro.py` | As duas entradas de dinheiro: vírgula decimal e separador de milhar aceitos; vazio, ausente, `NaN`, infinito, 14 dígitos, negativo e zero recusados **com mensagem**; limites do formulário conferidos contra a coluna do banco; e a data do produto lida no fuso da clínica | 6 |
| `checks/check_exportacao.py` (seção nova) | "Pode pedir" e "pode baixar" têm de concordar para todos os vínculos da clínica | 1 |

## 16. Resultado dos testes

| Momento | Roteiros | Resultado |
| --- | --- | --- |
| Linha de base (antes de qualquer alteração) | 50 | **nenhuma falha** (1.157 s) |
| Após a 1ª rodada de correções | 52 | **nenhuma falha** (342 s) |
| Final (8 correções, 3 roteiros novos) | **53** | **nenhuma falha** (350 s) |

Nenhuma correção desta auditoria quebrou comportamento existente. Os dois
roteiros novos falham de verdade contra o código anterior — foram escritos
depois de ver o defeito, e conferidos contra ele.

## 17. Resultado do build

`docker compose build app` conclui sem erro. O `Dockerfile` roda
`pip install --require-hashes`, `pip check` e `mkdocs build --strict` — um
aviso no MkDocs quebra o build, de propósito. Imagem final roda como UID
10001, sistema de arquivos somente-leitura, `HEALTHCHECK` próprio.

Sem build de frontend: CSS e JS são servidos como estão.

## 18. Configuração de produção

`manage.py check --deploy` em configuração de produção: **2 avisos, ambos
deliberados** — `SECURE_HSTS_INCLUDE_SUBDOMAINS` e `SECURE_HSTS_PRELOAD`.
`SECURE_HSTS_SECONDS` começa em `0` de propósito: o navegador guarda a
instrução e não há como voltar atrás pelo servidor.

Confirmado por leitura: `DEBUG` não tem default permissivo, `SECRET_KEY` e
`ALLOWED_HOSTS` são obrigatórios, cookies `Secure`/`HttpOnly`/`SameSite`,
`TRUSTED_PROXIES` restringe de quais proxies o `X-Forwarded-For` é aceito, e o
preflight do deploy recusa `DEBUG=True`.

## 19. Variáveis de ambiente necessárias

42 documentadas em `.env.example`, 32 lidas por `env()` no código, 9 segredos
por `secret()` (arquivo em `.secrets/`, nunca no `.env`).

**Conferi as duas direções:**

- **Usadas e não documentadas:** 6 — `DB_HOST`, `RUN_MIGRATIONS`,
  `SERVER_EMAIL`, `SERVICE_ROLE`, `STATIC_PREPARATION_ROOT`, `RELEASE_ID`.
  **Nenhuma é defeito:** todas têm default seguro e são escritas por papel
  pelo `ops/make_runtime.py` (`SERVICE_ROLE=app|worker|beat`,
  `RUN_MIGRATIONS=True` só no `app`).
- **Documentadas e não usadas:** 18 — **falso positivo meu.** São lidas por
  `config['NOME']` em `ops/deploy.py`, `ops/backup.py` e `ops/make_runtime.py`,
  que leem o `.env` como dicionário. Conferido caso a caso.

Nenhum segredo real no `.env.example`.

## 20. Migrations

86 no total. **Aplicam do zero sem erro** num PostgreSQL 17 limpo (§11).
`makemigrations --check` limpo. A release é **expand**: o banco nasce do zero,
nada é migrado.

`tenancy/0017` contém `RemoveField` — **não é contração**: remove duas colunas
que a `0016` criou horas antes, nenhuma delas publicada.

**Ressalva:** a leitura migration a migration (operação destrutiva sem aviso,
`RunPython` sem `reverse_code`, consulta pesada sem lote) veio da dimensão
`deploy-migrations`, que rodou — mas os achados dela **não foram verificados**
por mim (§25).

## 21. Backup

- `ops/backup.py`, cifrado com `age`, trava única compartilhada com o arquivo
  morto (`ops/locks.py::BACKUP_LOCK`).
- Unidades systemd (`neurodoc-backup.service/.timer`) para a cópia noturna.
- **Corrigido nesta auditoria:** o `age` não era instalado (A-03).
- **Aberto (P-10):** destino externo do backup e titular da chave de
  recuperação. `BACKUP_DIR` local resolve "apaguei sem querer"; não resolve "a
  máquina morreu".

## 22. Rollback

`ops/deploy.py` publica por digest e sabe voltar à versão anterior. A pergunta
"como retorno à versão anterior se o deploy falhar?" tem resposta: republicar
o digest anterior. Como o banco nasce do zero nesta release, **não há
migration a reverter**.

## 23. Procedimento de deploy

Ver `DEPLOY.md` (criado nesta auditoria) e, para o passo a passo canônico e
mais detalhado, `docs/operations/primeiro-deploy.md`.

## 24. Procedimento de validação pós-deploy

Ver `DEPLOY.md` §Validação e `DEPLOY_CHECKLIST.md`.

---

## 25. Problemas conhecidos restantes

### 25.1 · Cobertura das dimensões

As 19 dimensões foram completadas. As cinco que o limite de sessão havia
cortado rodaram em 2026-09-25 e leram 277 arquivos:

| Dimensão | Arquivos lidos | Achados | O que rendeu |
| --- | --- | --- | --- |
| `validacao` | 62 | 7 | **A-05** (dinheiro sem validação) e **M-05** (data em UTC) |
| `banco-esquema` | 61 | 8 | **B-03**; o resto refutado ou já coberto |
| `frontend` | 48 | 6 | `data-nd-busy` não alcança botão ligado por `form=` |
| `codigo-morto` | 62 | 8 | **M-06** e **M-07** |
| `lgpd-privacidade` | 44 | 6 | **A-06** (download do acervo clínico) |

Os quatro censos do auditor de frontend, que conferi por conta própria:
**150 formulários POST, zero sem `csrf_token`**; zero `id` duplicado real;
zero `href` literal para rota inexistente; zero CSS ou JS morto; nenhum
resíduo do tema escuro. Dos 18 formulários sem `data-nd-busy`, **todos os 18
são idempotentes** — descartar, remover, revogar, arquivar, sair. Nenhum cria
registro, então não há defeito de duplo submit.

### 25.2 · Achados automáticos **não verificados**

81 achados brutos; verifiquei 8 em profundidade. **Os demais não são fatos** —
são pistas. Listados por dimensão, para quem continuar:

**Transações e atomicidade** (7): `documents/issuance.py` (falha de assinatura
descartada pelo `atomic` que a envolve); `communications/services.py` (mensagem
publicada antes do commit do token); `documents/request_views.py` (três
transações soltas); `reporting/services.py`; `ai/handlers.py` (`.delay()` dentro
da transação); `documents/storage.py`.

**Concorrência** (7): `finance/adjustments.py` (ler-modificar-gravar em
`charged_amount`); `clinical/finalization.py` (sobrescreve o autosave);
`finance/payments.py` (duplo clique lança dois pagamentos);
`tenancy/limits.py` (COUNT sem serialização); `scheduling/handlers.py`;
`teamchat/services.py`; `communications/marketing.py`.

**Tratamento de erro** (8): ausência de `handler404`/`handler500` e de
templates de erro; `SigningFailed` não capturada na view; data malformada na
tela financeira virando 500; `events/dispatcher.py` engolindo exceção sem
registrar.

**Consultas** (8): N+1 em indicadores, financeiro, entregas, campanhas e
balcão do dia; `LIMIT` sem `ORDER BY` na busca de catálogo.

**Integrações, uploads, borda pública, configuração** (16): entre eles, dois
que merecem atenção — `communications/services.py` (reenvio de documento
revoga o link que acabou de criar) e `.env.example` (`TRUSTED_PROXIES` não
inclui as faixas da Cloudflare, que o próprio deploy põe na frente).

**Das cinco dimensões novas** (24 achados não verificados): rascunho de
prontuário no `localStorage` sem prazo; `data-nd-busy` que não alcança botão
ligado ao formulário por `form=`; cancelar a confirmação deixando o botão
desabilitado; remoção de anexo sem confirmação; foto do paciente gravada com
permissão padrão; trilha guardando conteúdo clínico em alguns eventos; IP
nunca gravado na trilha; `protect_ip` sem máscara de IPv6 comprimido;
desidentificação da IA que não remove data de nascimento nem endereço; o
gatilho de imutabilidade não cobrir `TRUNCATE`; `ai/tools/administrative.py`
como módulo morto; resíduo legado em `documents/storage.py`.

### 25.2b · Achados que **refutei** ao verificar

Registrados porque a refutação também é resultado — e porque quem repetir a
auditoria vai encontrá-los de novo:

| Achado | Por que não procede |
| --- | --- |
| `/admin/login/` como "segunda porta sem MFA" (CRÍTICO) | Testado: usuário comum com senha **correta** não autentica (`is_staff` exigido), e `/admin/` e `/instalacao/` exigem `is_verified()`. Sobrava o limitador, corrigido em A-04 |
| Responsável escreve no CRM → "escalonamento de privilégio" (CRÍTICO) | Trocar o CRM **rebaixa a verificação para PENDENTE** antes de gravar, com a comparação feita antes do `is_valid()` porque `ModelForm` muta a instância |
| Número de documento colide ao apagar (ALTO) | `discard_document` recusa apagar documento emitido, e rascunho não tem número. Sobra a fragilidade (B-03) |
| Portal do paciente como "oráculo de CPF" | `check_g10` §6 já cobra que os casos de falha sejam indistinguíveis, e §7 o bloqueio por IP |
| 10 cópias de `TenantScopedView` como duplicação | Cada uma declara uma **capacidade diferente**: é configuração por app sobre `CapabilityRequiredView`, o padrão documentado |
| Duas `ManagerRequiredView` homônimas | Corpos diferentes, métodos auxiliares diferentes. Nome repetido, lógica não |
| `registration/password_reset_email.html` órfão | Morto de fato, mas é o caminho padrão do Django: mantido de propósito (B-04) |

### 25.3 · Pendências externas já conhecidas

P-02 (VPS real), P-03 (SMTP/SMS/IA reais), P-05 (certificado A1 do médico),
P-08 (scanner real), P-09 (enquadramento da IA), P-10 (destino externo do
backup). Ver `docs/decisions.md`.

## 26. Riscos residuais

1. **Cobertura incompleta** — 5 dimensões não varridas, 73 achados não
   verificados. A ausência de defeito encontrado não é prova de ausência de
   defeito.
2. **Duas vulnerabilidades conhecidas em dependências** (§13), deliberadamente
   não corrigidas na véspera.
3. **Sem coleta de lixo em produção** (D-02) — o disco só cresce, e arquivo
   apagado pelo usuário permanece legível.
4. **SSRF em aberto** (D-01), mitigado por capacidade e por plano.
5. **Nenhuma medição de desempenho** sob carga.
6. **Primeiro deploy**: nada aqui foi exercitado numa VPS real.

## 27. Checklist final

`DEPLOY_CHECKLIST.md` traz a lista operacional. As respostas objetivas que o
roteiro de auditoria exige:

| # | Pergunta | Resposta |
| --- | --- | --- |
| 1 | Todo o repositório foi analisado? | Sim. Determinístico: 826 arquivos. Assistido: **19 de 19 dimensões** |
| 2 | Os fluxos principais foram identificados? | Sim — §4 |
| 3 | Os fluxos principais têm testes? | Sim — 52 roteiros; lacunas em `TEST_MATRIX.md` |
| 4 | A suíte passa? | **Sim — 53/53** |
| 5 | O build funciona? | Sim |
| 6 | Dependências auditadas? | Sim — 2 pacotes com aviso (§13) |
| 7 | Segurança revisada? | Sim — §10 |
| 8 | Autorização revisada? | Sim; nenhum IDOR encontrado |
| 9 | O banco foi revisado? | Sim — 84 tabelas, 209 FKs, 154 constraints únicas, **zero FK sem índice**; trilha imutável em duas camadas (papel sem `UPDATE`/`DELETE` **e** gatilho) |
| 10 | Migrations verificadas? | Sim — 86 do zero, nenhuma pendente |
| 11 | Configuração de produção revisada? | Sim — §18 |
| 12 | Segredos procurados? | Sim, incluindo o histórico do git |
| 13 | `.env.example` está completo? | Sim — §19 |
| 14 | Backup planejado? | Sim, e **um defeito impeditivo foi corrigido** (A-03) |
| 15 | Rollback planejado? | Sim — §22 |
| 16 | Deploy documentado? | Sim — `DEPLOY.md` |
| 17 | Smoke tests definidos? | Sim — `TEST_MATRIX.md` |
| 18 | Há problemas críticos conhecidos? | **Não.** O único crítico encontrado foi corrigido e verificado |

---

## STATUS TÉCNICO PARA DEPLOY

### TECNICAMENTE PREPARADO PARA STAGING

A auditoria não deixou bloqueador conhecido. O crítico encontrado foi
corrigido e verificado por medição; os quatro de alta prioridade também.

**A ausência de erro encontrado não é prova de ausência de erro.** As 19
dimensões rodaram, mas dos 116 achados automáticos verifiquei 13 — os outros
103 estão na §25 como pistas, não como fatos. Sete deles eu **refutei** ao
abrir o código (§25.2b), o que dá a medida de quanto uma varredura assistida
precisa ser conferida antes de virar decisão.

**Duas decisões suas antes de produção** (§9): D-01 (SSRF do `base_url` da IA)
e D-02 (agendar a coleta de lixo do disco).
