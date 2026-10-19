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
| **Versão** | 1.17 "os exames do paciente" (`base/version.py`) |
| **Em produção** | <https://neurodoc.app.br> — em uso real desde 02/10/2026 |
| **Licença** | [MIT](LICENSE) — código aberto |
| **Verificação** | 111 roteiros em `checks/`, nenhuma falha |
| **Stack** | Python 3.14 · Django 6.1 · PostgreSQL 17 · Celery · RabbitMQ · Redis · Traefik · Docker Swarm |

## Apoie o projeto

O NeuroDoc é escrito e mantido por um neurologista, no tempo entre um
atendimento e outro. Se ele for útil para você:

- ⭐ **deixe uma estrela** neste repositório — é o que mostra a outros
  médicos que o projeto existe e é usado;
- 💚 **contribua com qualquer valor pelo PIX:** `fernando.freua@gmail.com`;
- 🐛 **abra uma issue** com o defeito que encontrou ou com o que falta para
  a sua especialidade.

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
público onde o paciente pede receita, relatório ou pedido de exames sem
criar conta, e **envia os laudos dos exames que fez** (PDF, direto no
prontuário, com alerta ao médico até o "Ciente"); outbox de entrega
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
instalação. A **comunicação em massa** é a exceção: está em todos os
planos e sai só pelo servidor de e-mail da própria clínica. O nome
fantasia é editado pela própria clínica; razão social e CNPJ continuam
vindo do convite.

**Plataforma.** Multi-inquilino com três camadas de autorização, trilha de
auditoria imutável, backup cifrado com `age` e cópia externa, console de
superadministrador, central de ajuda pública e página de vendas.

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
são baixados da internet; rode-os quando for usar receita e naturalidade:

```bash
docker compose exec celery_worker python manage.py import_cmed        # medicamentos da Anvisa (~12 MB)
docker compose exec celery_worker python manage.py import_municipios  # municípios do IBGE
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
semeada e o `import_cmed` rodado:

```bash
docker compose exec app python manage.py rodar_roteiros            # todos (~8 min)
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
GitHub Container Registry e identificada pelo SHA do commit, e o Traefik
emitindo o certificado do Let's Encrypt.

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
monitoramento: [`docs/operations/`](docs/operations/).

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
registro em [`docs/releases/`](docs/releases/).

| Versão | Data | Nome | O que entrou |
| --- | --- | --- | --- |
| **1.17** | 2026-10-19 | os exames do paciente | **Alterar a medicação** do atendimento pelo **lápis** ao lado da lixeira: o cadastro abre já preenchido logo abaixo da linha, e mudar a dose não exige mais excluir e incluir de novo — o "em uso desde", a indicação e a observação ficam. Só com o atendimento aberto; a trilha registra quais campos mudaram, sem os valores. E **uma pergunta por ação**: limpar avisos (e toda ação com confirmação) mostrava a caixa do navegador, o modal do sistema e a caixa de novo; agora só o modal. E o **código aberto**: o repositório fica público sob a MIT, a página de vendas aponta para ele com o pedido de estrela e a chave PIX, e o contrato de adesão passa à **versão 1.1**, com o item 16.3 dizendo que ele rege o serviço hospedado e não o código. |
| **1.16.2** | 2026-10-19 | os exames do paciente | Textos do portal e da vitrine: em urgência, o portal manda ao **serviço de urgência e emergência mais próximo** (e não mais "ligue para a clínica"); o rodapé deixa de oferecer remarcar consulta, que o portal não faz; e a **página de vendas** e a **central de ajuda** (artigo do portal, avisos, identidade da clínica e perguntas frequentes) contam que o portal também **recebe os laudos dos exames**. |
| **1.16.1** | 2026-10-18 | os exames do paciente | O primeiro envio real de exame foi recusado: o formulário do portal estava aberto antes de um **login no mesmo navegador**, que troca o token de segurança. Agora entrar no sistema **encerra a identificação do portal**, a recusa explica e oferece abrir a página de novo (e não manda o paciente ao login), há **Encerrar identificação** nas telas do portal, e os textos e o aviso de privacidade dizem que o portal também **recebe laudos** — com o aviso vermelho já na página de solicitação. |
| **1.16** | 2026-10-18 | os exames do paciente | O paciente **envia laudos de exame em PDF pelo portal** (até 5 por envio, 3 MB cada, com qual exame, data e local), que entram direto no prontuário e acendem um **alerta vermelho** para o médico até ele marcar "Ciente"; a janela de retorno de 180 dias barra o pedido, não o laudo. E a lista de anexos ganha a coluna **Anexado em** antes do nome. |
| **1.15** | 2026-10-15 | a agenda | **Bloquear este horário** no modal do horário livre, ao lado de Excluir: o bloqueado fica na agenda e **conta** na estatística do mês, o excluído some e não conta; a célula bloqueada se libera com um clique. E a consulta futura gravada com a duração de outro tipo (o retorno de 80 min, de antes da 1.13) volta à duração do seu, liberando o horário seguinte; a remarcação passa a gravar a duração do tipo. |
| **1.14.2** | 2026-10-15 | a agenda | O mesmo aviso não chega mais **duas vezes na mesma caixa**: quando o paciente tem dois contatos com o mesmo e-mail (ou o mesmo celular), aviso de horário, lembrete, aviso de retorno e entrega de documento saem uma vez por endereço, registrados no contato do próprio paciente. |
| **1.14.1** | 2026-10-15 | a agenda | O horário excluído **some** da agenda, em vez de aparecer "fechado" (no mês, o dia inteiro aparecia fechado), e **Incluir horário** no mesmo lugar o traz de volta — antes era recusado como "já é horário de atendimento". Os excluídos na 1.14 são convertidos. |
| **1.14** | 2026-10-15 | a agenda | **Excluir este horário** no modal que abre ao clicar num horário livre, nas visões de mês, semana e dia: o horário passa a aparecer fechado, com o motivo; o que tinha sido incluído pela agenda simplesmente some. Para quem pode configurar aquela agenda. |
| **1.13** | 2026-10-13 | a agenda | **Trocar o tipo** do horário passa a mudar a duração: encolher libera o horário que sobra, esticar só onde o tempo seguinte estiver livre. Botão **Incluir horário** ao lado do dia nas visões de mês, semana e dia. **Idade** do paciente ao lado do nome na ficha e no prontuário (no atendimento, a idade na data dele); sai o selo interno "versão N". |
| **1.12.3** | 2026-10-09 | o rodapé | Lote 2 da auditoria independente: **remarcar** recusa consulta já cancelada (e diz por quê); falha ao **assinar** — inclusive senha errada do certificado — fica na trilha de auditoria e deixa de virar erro 500; **descartar** evolução em texto livre pede motivo; a confirmação de entrega do **SMS** usa a conta da própria clínica, e a recusa do provedor deixa de aparecer como aceita; **exportação** vencida não baixa mais; e a IA confere o papel médico na hora de executar. |
| **1.12.2** | 2026-10-09 | o rodapé | Lote 1 da auditoria independente: o **PDF de receita e relatório** deixa de aparecer como anexo comum — a recepção baixa e imprime o documento **emitido**, não abre o rascunho, e ninguém o remove pela lista de anexos; **finalizar** não grava mais por cima do último trecho salvo pelo autosave; o **reenvio** para e-mail e SMS deixa os dois links valendo; o pedido do **portal** não cai mais na ficha de outro paciente identificado no mesmo navegador; o retorno depois do **MFA** não sai do domínio; e uma entrega não sai duas vezes. |
| **1.12.1** | 2026-10-09 | o rodapé | Correções do processamento assíncrono apontadas por auditoria externa: quem **perdeu a posse** de um evento não o processa nem sobrescreve o desfecho; o consumidor roda **fora** de transação externa (o link do documento existe antes de o SMS sair); o **lembrete não sai** para consulta cancelada, remarcada ou já começada; o aviso de horário mede a idade pelo instante em que o fato aconteceu; job de IA parado na fila é **retomado**; falha de consumidor deixa log com nome. Sem migração. |
| **1.12** | 2026-10-08 | o rodapé | A **assinatura do médico**, com o QR, e no controle especial o **quadro do comprador e do fornecedor**, passam a ficar sempre no **pé da folha**, em todo documento: cabeçalho no alto, corpo no meio, rodapé embaixo. Se o corpo enche a folha, o rodapé vai inteiro para o pé da seguinte, e nunca se parte. Os rótulos do quadro do fornecedor deixam de sair cortados por uma linha. |
| **1.11** | 2026-10-08 | a caixa limpa | **Limpar todas as notificações**, no sino e na central, com confirmação. Apaga a caixa da pessoa naquela clínica (lidas e não lidas) e nada além: a caixa da outra clínica e a de outra pessoa ficam, e o que cada aviso apontava (pedido do portal, resultado, exportação) continua onde está. |
| **1.10** | 2026-10-08 | a recepção | O **tipo de consulta** de um horário marcado passa a ser trocado no próprio modal da agenda (clicando no rótulo ou em "Alterar o tipo de consulta"), só antes da chegada, porque no check-in o tipo define o preço da cobrança, e sem mexer no horário. O **CRM já registrado em outra conta** deixa de ser recusado em inglês ("Physician profile com este Crm number...") e passa a dizer o caminho: convidar a conta onde o registro está. A unicidade do CRM continua, e é ela que impede alguém de assinar no nome de outro médico. |
| **1.9** | 2026-10-08 | o e-mail da clínica | **Comunicação em massa em todos os planos**, saindo só pelo servidor SMTP da própria clínica. Antes bastava o remetente ativo, e remetente sem servidor saía pelo SMTP da instalação, que entrega a confirmação de conta de todas as clínicas. Sem servidor próprio, a área explica o que falta e não envia, e o envio que perde o servidor no meio pausa. A página de vendas passa a dizer que o Gratuito se comunica por e-mail, pelo NeuroDoc ou pelo servidor da clínica. |
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
| `documents` | anexos com antivírus, documentos médicos, assinatura PAdES, QR público, portal do paciente (solicitações e envio de laudos), OCR |
| `communications` | outbox, links opacos com OTP, aviso de horário, campanhas com consentimento, credenciais da clínica |
| `finance` | honorários com vigência, recebíveis, pagamentos, ajustes |
| `ai` | jobs com revisão médica, desidentificação, chat com streaming, relatório do paciente, leitura de laudo |
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
| [`docs/ESTADO-ATUAL.md`](docs/ESTADO-ATUAL.md) | **leia primeiro** — o retrato de hoje: o que está provado, o que está aberto, as lições que custaram caro |
| [`PRD.md`](PRD.md) | a especificação completa (matriz de permissão §4, roteiro de homologação §21) |
| [`docs/index.md`](docs/index.md) | índice da documentação técnica, publicada em `/technical-docs/` (MFA) |
| [`docs/decisions.md`](docs/decisions.md) | decisões (DEC-xx) e pendências (P-xx) com dono e condição de liberação |
| [`docs/governance/lgpd.md`](docs/governance/lgpd.md) | matriz de tratamento, operadores, medidas técnicas e o roteiro que verifica cada uma |
| [`docs/operations/`](docs/operations/) | deploy, rollback, backup, cópia externa, monitoramento |
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

---

## Licença

Código sob a [licença MIT](LICENSE) · © 2026 Fernando Freua.

O serviço hospedado em <https://neurodoc.app.br> é oferecido às clínicas
por contrato de adesão próprio, publicado em
<https://neurodoc.app.br/contrato/>; ele rege a prestação do serviço e não
altera os direitos que a licença MIT concede sobre este código.
