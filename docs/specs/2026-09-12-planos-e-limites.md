# Planos, limites, convites e página de vendas

**Data:** 12/09/2026 · **Estado:** aprovado para implementação · **Domínio:** `neurodoc.app.br`

Especificação da oferta comercial do NeuroDoc: quatro planos com limite de
pacientes e de médicos, códigos de convite que carregam o que foi
contratado, uma página de vendas pública e um formulário de contato.

Fica em `docs/specs/` e não em `docs/superpowers/specs/` porque esta
documentação é publicada em `/technical-docs/` com uma taxonomia própria
(`decisions`, `governance`, `homologation`, `operations`, `reference`,
`security`); um diretório com nome de ferramenta destoaria dela.

## 1. Decisões tomadas

| ID | Decisão | Alternativa recusada, e por quê |
| --- | --- | --- |
| PL-01 | O catálogo de planos vive em **código** (`tenancy/plans.py`), não em tabela | Em tabela, mudar o limite do Básico de 500 para 400 alteraria em silêncio o direito de toda clínica já contratada, e o registro do que foi vendido sumiria junto. Em código é um commit, com data e autor |
| PL-02 | O desvio por clínica vive no **banco** (`patient_limit_override`, `doctor_limit_override`) | Criar um quinto plano para cada negociação faria o catálogo crescer com o número de clientes |
| PL-03 | Ilimitado é `None`, nunca um número grande | `999999` é um limite que um dia alguém bate, e na véspera ninguém sabe que existe |
| PL-04 | Acesso irrestrito da clínica-sede é o plano `custom` **sem overrides** | Uma exceção codificada por e-mail é invisível na tela, não aparece na trilha, e sobrevive à venda da empresa |
| PL-05 | O limite conta **pacientes ativos**; arquivar libera vaga | Contar todos puniria quem faz a limpeza correta do cadastro e travaria clínicas antigas por pacientes que não voltam há anos |
| PL-06 | Bater o limite **bloqueia**, com mensagem que resolve, e há aviso a partir de 80% | Deixar passar e cobrar depois é cobrança-surpresa; bloquear sem aviso deixa a recepção com o paciente no balcão |
| PL-07 | Downgrade **congela**: nada some, só não cresce | Apagar ou esconder prontuário por questão comercial é o que não se faz em sistema de saúde — a Lei 13.787/2018 fixa 20 anos de guarda, que não conhece plano de assinatura |
| PL-08 | Mudar plano de clínica existente é ato do console `/instalacao/`, com motivo e trilha | O admin técnico do Django serve, e não mostra uso contra limite: trocaria o plano sem ver se a clínica cabe nele |
| PL-09 | A página de vendas **não** terá depoimentos nem estatísticas fabricados | Depoimento inventado de médico é falso testemunho sobre produto de saúde; contador em zero anuncia que não há clientes |
| PL-10 | Nenhum preço na página, nesta versão | Preço errado em página pública é pior que preço ausente |

## 2. Entrega 1 — Planos e limites

### 2.1 Catálogo (`tenancy/plans.py`)

| Código | Nome | Pacientes | Médicos |
| --- | --- | --- | --- |
| `free` | Gratuito | 50 | 1 |
| `basic` | Básico | 500 | 2 |
| `complete` | Completo | 3.000 | 5 |
| `custom` | Personalizado | ilimitado | ilimitado |

Cada entrada carrega também o texto de venda (nome, resumo, lista de
recursos) que a Entrega 3 consome, para a página e o sistema não
divergirem sobre o que cada plano dá.

### 2.2 Modelo

`Tenant` ganha:

- `plan` passa a ter `choices` e validação em `clean()`. Hoje é
  `CharField` livre com default `'free'`, usada apenas para exibição numa
  listagem do console — uma casca vazia.
- `patient_limit_override`, `doctor_limit_override`:
  `PositiveIntegerField(null=True, blank=True)`. **Nulo = usa o plano.**
- `plan_note`: texto curto do porquê do plano atual (contrato, cortesia,
  piloto). É o que responde "por que esta clínica tem 1.200?" um ano
  depois.

Migration puramente *expand* — campos novos, com default e nulos. É o
único tipo que `NEURODOC_SCHEMA_CHANGE=expand` aceita.

### 2.3 Resolução e contagem (`tenancy/limits.py`)

```
patient_limit(tenant) -> int | None      # override, senão plano
doctor_limit(tenant)  -> int | None
patient_usage(tenant) -> int             # Patient ativos do tenant
doctor_usage(tenant)  -> int             # Membership ativos com papel doctor
limit_status(tenant)  -> uso, limite, percentual, bloqueado, em_aviso
assert_can_add_patient(tenant)           # levanta PlanLimitReached
assert_can_add_doctor(tenant)
```

`PlanLimitReached` carrega o recurso, o uso, o limite e o nome do plano —
a mensagem de tela é montada a partir disso, e não escrita em cada
chamador, para não divergirem.

**Aviso a partir de 80%**, na lista de pacientes e no painel. O bloqueio
não pode ser a primeira notícia.

### 2.4 Onde as travas entram

Paciente nasce em **dois** lugares, e os dois recebem trava:

| Local | O quê |
| --- | --- |
| `patients/views.py::PatientCreateView` | Cadastro completo |
| `scheduling/services.py` (pré-cadastro) | A secretária cria paciente **marcando horário**, sem passar pela tela de cadastro. É o que se esquece |

Médico entra por **quatro** caminhos, e os quatro recebem trava:

| Local | O quê |
| --- | --- |
| `tenancy/admin_views.py::MembershipRolesView` | Conceder o papel `doctor` a um vínculo existente |
| `tenancy/services.py::accept_collaborator_invitation_for_user` | Convite aceito por quem já tem conta |
| `tenancy/services.py::accept_collaborator_invitation_new_user` | Convite aceito por conta nova |
| `tenancy/admin_views.py::MembershipStatusView` | Reativar vínculo suspenso que tem o papel |

Além disso, **a emissão do convite de colaborador com papel `doctor` é
bloqueada quando a clínica já está no limite**. A verificação no aceite
continua existindo — é a autoritativa —, mas sem a da emissão o convidado
descobriria o problema depois de clicar no link, e quem pode resolvê-lo é
o dono da clínica, não ele.

`seed_demo` e importação passam por cima por parâmetro explícito: fixture
não é venda.

### 2.5 Fora de escopo desta entrega

Cobrança, checkout, gateway de pagamento e emissão fiscal continuam fora
da versão 1 (seção 2.2 do PRD). Nada aqui cobra de ninguém.

## 3. Entrega 2 — Convites que carregam o contratado

`Invitation` ganha `plan`, `patient_limit_override`, `doctor_limit_override`.
`accept_platform_invitation` passa a ler do convite em vez do `plan='free'`
hoje escrito na linha 54 de `tenancy/services.py`.

O token continua sendo 32 bytes aleatórios com hash, uso único e prazo. O
que muda é que ele carrega o que foi vendido.

Console:

- `/instalacao/convites/` — emitir escolhendo plano e limites, listar os
  pendentes com emissor e data, revogar.
- `/instalacao/organizacoes/` — passa a mostrar **uso contra limite** e a
  permitir trocar o plano, com motivo obrigatório.

É a **primeira escrita** no console, que hoje é só leitura. A exigência de
`is_superuser` mais MFA já está na base das views; cada ação vira
`AuditEvent`. O console continua sem tocar em prontuário — trocar plano é
ato administrativo sobre a organização, não sobre o paciente.

## 4. Entrega 3 — Landing e contato

Estrutura: **hero → problema/solução → funcionalidades → planos → FAQ →
contato → rodapé**, com o tema Duralux que o produto já usa.

As funcionalidades anunciadas são as homologadas: prontuário estruturado,
roteiro de exame neurológico (387 nós, 14 escalas), documentos com
assinatura PAdES e QR de verificação pública, agenda, portal do paciente,
IA com revisão médica. A IA é descrita como apoio que o médico revisa,
nunca como diagnóstico — **P-09** (enquadramento regulatório, possível
SaMD) segue aberta e proíbe divulgar finalidade clínica.

Quatro cards de plano, Completo destacado, sem preço. Cada um leva ao
formulário com o plano pré-selecionado.

`Lead` (nome, e-mail, telefone, clínica, plano de interesse, mensagem,
origem, versão do aviso de privacidade) é **gravado antes** de o e-mail
para `contato@neurodoc.app.br` ser enfileirado no outbox. Com o envio
direto, SMTP fora significaria lead perdido.

Rota pública sem conta, então as mesmas defesas do portal do paciente:
limite por IP, campo-armadilha contra robô, e **destinatário fixo no
servidor** — formulário público que aceita destinatário do cliente é um
relay aberto.

O lead é dado pessoal: retenção e base legal entram na revisão de
**P-06**.

## 5. Entrega 4 — Domínio

Já pronto: `docker-stack.yml` roteia `neurodoc.app.br` mais o wildcard com
resolvedor Cloudflare; o preflight exige as entradas de `ALLOWED_HOSTS` e
`CSRF_TRUSTED_ORIGINS`; `DEFAULT_FROM_EMAIL` é `no-reply@neurodoc.app.br`.

Falta o que depende de você: `ACME_EMAIL` real, token Cloudflare
(Zone:DNS:Edit + Zone:Zone:Read), `BACKUP_AGE_RECIPIENT` (chave pública
`age` gerada fora da VPS) e a caixa `contato@neurodoc.app.br` existindo de
fato.

## 6. Verificação

`checks/check_planos.py`, contra a pilha local, por entrega. Para a
Entrega 1, no mínimo:

- os limites de cada plano conferem com esta tabela;
- override vence o plano; nulo cai no plano; `custom` sem override é
  ilimitado;
- no limite, o cadastro completo **e** o pré-cadastro da agenda recusam,
  com mensagem que nomeia plano, uso e limite;
- arquivar libera vaga; desarquivar volta a ocupar;
- clínica acima do teto (downgrade) mantém os pacientes acessíveis e
  recusa apenas o próximo;
- os quatro caminhos de concessão de papel médico respeitam o limite;
- a emissão de convite de colaborador médico é recusada no limite;
- `seed_demo` continua rodando acima de qualquer limite;
- aviso aparece a partir de 80% e não antes.

## 7. Riscos aceitos

| Risco | Mitigação |
| --- | --- |
| A clínica arquiva e desarquiva para burlar a cota | Na prática dá mais trabalho que pagar, e o desarquivamento volta a ocupar vaga. Não se implementa detecção nesta versão |
| O bloqueio trava a recepção com o paciente presente | A mensagem traz o contato; e o aviso de 80% existe justamente para o bloqueio não surpreender |
| Limite alcançado entre a emissão e o aceite do convite | O aceite recusa, e a mensagem manda falar com a clínica. É corrida rara, e a alternativa — conceder acima do limite — quebraria a regra |
