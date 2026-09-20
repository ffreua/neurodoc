# Mensagens da equipe — janela flutuante ao lado do sino

> **Estado: homologado na pilha local (2026-09-17).** Evidência coletada
> com `checks/check_mensagens.py` rodando dentro do contêiner contra o
> PostgreSQL e o Redis reais, e com `curl -N` **através do Traefik real**
> (`127.0.0.1:8080`, o mesmo roteador usado em produção) para a parte de
> SSE e presença, que o roteiro não alcança. As caixas de verificação
> manual no fim continuam desmarcadas: dependem de olho e de mouse.

## O que é

Um botão de balão ao lado do sino de notificações abre uma janela que
**flutua sobre a tela em que a pessoa está**, arrastável pela barra de
título e redimensionável pela alça do canto inferior direito. Dentro dela,
à esquerda, as pessoas com vínculo ativo na clínica, com uma bolinha verde
para quem está com o sistema aberto agora; à direita, a conversa.

Médico com secretária, médico com médico, secretária com secretária,
gestor com quem for: não há papel privilegiado aqui. Conversar não é uma
capacidade da matriz do PRD §4 — é o que qualquer vínculo ativo faz.

## As decisões, com a alternativa recusada

**1. App próprio (`teamchat`), e não dentro de `communications`.** Aquele
app fala com quem está *fora*: paciente, por e-mail e SMS, com
consentimento, outbox e reconciliação de entrega. Aqui nada sai da
instalação. Recusado juntar: toda mensagem de corredor passaria pelo
outbox, e todo ajuste no outbox arriscaria o chat.

**2. Isto não é prontuário, e a tela diz isso.** O risco é conhecido:
alguém vai escrever nome de paciente e conduta no chat. O que o sistema
faz — o conteúdo nunca aparece no sino nem em `Notification` (o cabeçalho
mostra um número, não um trecho); fica no PostgreSQL isolado por inquilino
como qualquer dado da clínica; e um aviso não dispensável no rodapé da
conversa lembra que o que precisa ficar registrado vai na evolução do
atendimento. O que o sistema **não** faz: escolher prazo de retenção e
expurgo. Isso é de quem responde pela LGPD na clínica (P-06/P-07 em
[decisões](../decisions.md)), e inventar um prazo aqui seria decidir no
lugar deles.

**3. Conversa de duas pessoas, com chave canônica.** `direct_key` é
`min(uuid):max(uuid)`, único por inquilino. Recusada a chave "quem abriu
primeiro": o médico abrindo a secretária e a secretária abrindo o médico
criariam duas conversas, cada um escrevendo numa que o outro não lê — um
defeito que não aparece em teste de uma pessoa só, e aparece no primeiro
dia de uso. Grupo com nome entra depois preenchendo `title` e deixando
`direct_key` vazio: o esquema já é N-ário (há tabela de participantes, não
duas colunas).

**4. Contador de não lidas denormalizado.** `ConversationMember.unread_count`
é somado no processador de contexto, que monta o cabeçalho de **toda**
requisição de `/app/`. Recusado `COUNT(*) WHERE created_at > last_read_at`:
seria uma varredura da tabela de mensagens por página aberta. O preço é o
de todo denormalizado — só `teamchat/services.py` escreve ali, e o roteiro
confere que a soma bate com a contagem real.

**5. SSE aberto enquanto a página existe, em uma aba só.** *(Revisto: a
primeira versão só mantinha o stream com a janela aberta, e a badge com a
janela fechada dependia de uma sondagem de 20 s. O aviso de que alguém
está tentando contato chegava com até 20 s de atraso, o que esvazia o
aviso.)* Agora o stream sobe com a página. O orçamento de conexões — seis
por origem em HTTP/1.1, que é o do ambiente local — é resolvido do outro
lado: as abas elegem **uma** líder por um aluguel no `localStorage`, só ela
abre o stream, e o que chega é repassado às demais por `BroadcastChannel`.
Uma conexão por navegador, não por aba; gasta menos do que a versão
anterior gastava com duas abas de chat abertas. Recusado o protocolo de
exclusão mútua para a eleição: `localStorage` não é atômico, mas quem
escreve confere depois se o aluguel continua seu, e o pior caso é uma aba a
mais com stream por alguns segundos — que era o estado normal antes. A
sondagem ficou em 30 s como rede de segurança (reconciliação de contadores
e presença).

**5b. O aviso são três sinais, não um.** O número no círculo vermelho, para
quem está olhando; um pulso curto de duas voltas quando o número cresce,
para o canto do olho; e `(3)` no título da aba, que é o único que atravessa
uma aba em segundo plano. Recusado o pulso contínuo: uma badge que pisca o
dia inteiro vira cenário e deixa de avisar. Quem pediu menos movimento no
sistema operacional (`prefers-reduced-motion`) recebe o número e o título,
sem o pulso.

O caso que obrigou a somar no total **antes** de saber de quem é a
mensagem: o primeiro contato. Quando escreve alguém com quem nunca se
conversou, a aba ainda não conhece o id daquela conversa — contar só o que
já está na lista deixaria a badge apagada exatamente quando alguém está
tentando contato pela primeira vez. Soma na hora, e uma recontagem com
1,2 s de atraso acerta em quem marcar.

**6. Presença é "deu sinal nos últimos 75 s", não "tem sessão válida".**
Uma sessão do Django continua válida por dias depois que a pessoa fechou o
navegador; dizer que ela está on-line por causa disso seria mentir na
tela. Um conjunto ordenado por inquilino no Redis (`ZADD` na escrita,
`ZRANGEBYSCORE` na leitura), e não uma chave por usuário — esta última
exigiria `SCAN` sobre o espaço de chaves a cada abertura da janela. Redis
fora do ar responde "não sei" (ninguém on-line) e a conversa continua
funcionando pelo PostgreSQL, que é onde a mensagem de fato está.

**7. Clínica suspensa congela o envio, não a leitura — nem a badge.** A
regra de verbo HTTP do `TenantMiddleware` recusa o `POST` de envio, como
recusa qualquer escrita. Mas `/app/mensagens/lida/` entrou em
`ALWAYS_ALLOWED_PREFIXES`, ao lado de `/app/notifications/`: zerar o
contador é estado do **usuário**, e sem essa exceção a badge ficaria com
um número vermelho impossível de baixar no cabeçalho de quem continua
trabalhando. Foi por isso que "marcar como lida" ganhou prefixo próprio em
vez de ficar sob a conversa.

## Superfície

| Rota | Método | O que faz |
| --- | --- | --- |
| `/app/mensagens/estado/` | GET | colegas, presença e não lidas; registra a própria presença |
| `/app/mensagens/abrir/` | POST | abre (ou reencontra) a conversa com um colega |
| `/app/mensagens/<id>/` | GET | últimas 50 mensagens, ou o que chegou desde `?desde=` |
| `/app/mensagens/<id>/enviar/` | POST | grava, incrementa os contadores, publica no Redis |
| `/app/mensagens/lida/<id>/` | POST | zera o não lido desta pessoa |
| `/app/mensagens/stream/` | GET | SSE da caixa de entrada do usuário |

Arquivos: `teamchat/` (modelos, serviços, views, SSE, presença),
`templates/partials/teamchat.html`, `static/teamchat/teamchat.{css,js}`,
e o botão em `templates/partials/header.html`.

## Roteiro de homologação

```bash
docker compose exec app python manage.py migrate
docker compose exec app python manage.py seed_demo
docker compose exec app python manage.py shell < checks/check_mensagens.py
```

O roteiro tenta quebrar, seção por seção, e sai com código 1 listando as
falhas. Rodou com `EXIT=0`:

- [x] abrir a conversa pelos dois lados dá **uma** conversa, não duas mudas
      (mesmo UUID pelos dois sentidos, uma linha com a chave canônica)
- [x] um terceiro da **mesma** clínica recebe 404 ao ler, ao escrever e ao
      marcar como lida a conversa alheia (o caso difícil: o escopo por
      inquilino não ajuda em nada aqui)
- [x] um id de usuário de **outro** inquilino é recusado em `open_direct` e
      com 400 pela rota; id malformado devolve a mesma recusa de quem não
      existe (400, sem 500)
- [x] a conversa de outra clínica responde 404 para quem está nesta
- [x] o contador não lido bate com a contagem real (3 = 3), e quem envia
      não incrementa o próprio (0)
- [x] marcar como lida zera, e o total do cabeçalho vai de 3 a 0
- [x] mensagem vazia e mensagem de 5.000 caracteres são recusadas com 400
- [x] clínica suspensa: leitura 200, envio **403**, marcar como lida **200**
- [x] o corpo atravessa intacto (`<script>alert("xss")</script> & <b>bold</b>`
      volta idêntico), servido como `application/json` com
      `X-Content-Type-Options: nosniff`, e o cliente não tem nenhuma escrita
      de HTML (`innerHTML`, `outerHTML`, `insertAdjacentHTML`,
      `document.write`) fora de comentário
- [x] vínculo revogado some da lista e não aceita conversa nova
- [x] conexão nova de SSE não reentrega o histórico retido no Redis, e o que
      chega depois continua sendo entregue
- [x] a página entrega o cookie `csrftoken` (de onde o cliente lê o token na
      hora do envio) e mantém o campo escondido como reserva

### Evidência de SSE e presença (fora do roteiro)

Colhida com `curl -N` através do Traefik real, com sessão de verdade:

- [x] `HTTP/1.1 200`, `Content-Type: text/event-stream`,
      `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Server: uvicorn`
- [x] mensagem enviada pela rota real (`POST .../enviar/`, com CSRF) chega
      na caixa da outra pessoa como um evento `mensagem` com `id:`
- [x] `: heartbeat` a cada 15 s mantém a conexão de pé através do proxy
- [x] o laço do SSE sustenta a presença: o `ZSET`
      `teamchat:online:<tenant>` passa a conter o usuário com carimbo
      recente enquanto a conexão está aberta
- [x] as chaves ficam no banco 3 do Redis (`teamchat:inbox:*`,
      `teamchat:online:*`), separadas do streaming da IA (banco 2) e do
      cache (banco 1)
- [x] a página renderiza o botão (`nd-tc-toggle`), a janela
      (`nd-teamchat`), a alça (`nd-tc-grip`), os dois estáticos e o aviso
      "não é prontuário"

## Revisão completa da implementação

Pedida depois de um relato de uso: com duas abas no mesmo Chrome, a aba
aberta como médico listava **o próprio médico**, em verde, e a secretária
não aparecia. Reproduzido no navegador, e o diagnóstico é o do parágrafo
sobre abas no fim da seção anterior — as duas abas dividem um cookie, a
segunda entrada troca a sessão da primeira, e a aba antiga passou a listar
os colegas *da conta nova* (onde o médico é colega e a secretária é a
própria pessoa, portanto excluída). Verde porque a presença do médico
ainda estava dentro dos 75 s.

Não era defeito do chat — mas era **defeito da tela**, que mentia em
silêncio. E a revisão que veio junto achou coisa pior.

**A conversa anterior ficava armada ao trocar de pessoa.** Se abrir a
conversa falhasse (rede caída, 400), `conversaAtual` continuava apontando
para a conversa **anterior** enquanto o cabeçalho já mostrava o novo nome:
escrever ali mandava a mensagem para a pessoa errada. O mesmo valia para o
clique rápido em duas pessoas — a resposta lenta da primeira chegava
depois e sobrescrevia a conversa da segunda. Num sistema em que se escreve
"a paciente das 15h piorou", isso não é um incômodo de interface. Corrigido
zerando a conversa ao trocar de pessoa, descartando resposta atrasada por
número de pedido, e recusando o envio (com aviso) quando não há conversa
aberta. Seção 14 do roteiro.

**A aba voltava morta do cache de retrocesso.** `pagehide` desligava os
temporizadores e o stream; voltar pelo botão do navegador pode restaurar a
página do bfcache em vez de recarregá-la, e nada religava nada. A aba
voltava viva na tela e morta por dentro — sem badge, sem mensagem
chegando, sem sinal de que parou. Religada no `pageshow` persistido.

**A tela agora avisa quando a sessão troca de dono.** `state_for` passou a
devolver de quem é a sessão; o cliente compara com o id que a página
trouxe ao ser montada e, se diferirem, troca a lista por uma explicação em
vez de mostrar os colegas de outra pessoa. Não recarrega sozinha: pode
haver um formulário preenchido embaixo. Conferido no navegador — a aba
obsoleta passou a dizer "Esta aba não é mais a sua sessão".

**A autorização do stream era refeita a cada segundo.** Copiado de
`ai/sse.py`, onde o stream dura o tempo de uma resposta. Aqui ele passou a
ficar aberto o dia inteiro, e isso virou um `SELECT` por segundo **por
pessoa on-line**. Passou para dez segundos: nenhuma requisição HTTP escapa
do `TenantMiddleware`, que confere o vínculo na hora, e o que a janela
permite é um stream já aberto entregar por mais dez segundos depois da
revogação.

**`desde` estava documentado como se fosse usado.** Não é — a janela
recarrega as últimas 50 ao abrir e a entrega ao vivo é do SSE. O
comentário passou a dizer isso.

Com dois navegadores de verdade (sessões separadas), cada lado lista o
outro corretamente e em verde, e a mensagem enviada depois de toda essa
mexida chegou: badge `1`, título `(1) NeuroDoc`, contador `1` na pessoa.

## Quatro defeitos encontrados ao homologar

**A badge contava a mesma mensagem duas vezes.** Encontrado dirigindo um
Chrome de verdade, com duas sessões: três mensagens enviadas, o servidor
dizendo `unread_count = 3` e a badge mostrando **4**. O caminho do
*desenho* já descartava id repetido (`vistas`), o caminho do *contador*
não — e o `EventSource` reconecta sozinho e pode reentregar o último
evento. A recontagem consertava o número 1,2 s depois, o que é pior do que
parece: um contador que se contradiz na frente da pessoa é um contador em
que ninguém confia. Um segundo conjunto de ids (`contadas`, com tempo de
vida diferente de `vistas`, que é zerado a cada conversa aberta) resolve.
Conferido no navegador reentregando o **mesmo** evento três vezes: a badge
foi a 4 e ficou em 4.

**Um 403 de CSRF se anunciava como "organização suspensa".** Relatado em uso
real, com duas abas no mesmo navegador: a secretária mandava e chegava, o
médico mandava e recebia "Organização suspensa: não é possível enviar
mensagens" — com a clínica ativa. Duas causas somadas. A primeira: o cliente
lia o token de CSRF do campo escondido, gravado quando a página foi montada,
e o Django troca o token a cada login — uma aba aberta antes de alguém entrar
com outra conta no mesmo navegador fica com o token anterior e leva 403. O
cliente passou a ler o token do **cookie**, na hora do envio, que é sempre o
da sessão atual; o campo continua como reserva. A segunda: qualquer 403 com
corpo em HTML era reportado como suspensão, o que manda a pessoa procurar
problema onde ele não está — e a suspensão nem sequer renderiza o campo de
escrever. O texto agora diz o que fazer, que é o mesmo nos três casos
possíveis (CSRF, suspensão superveniente, sessão encerrada). Seção 11 do
roteiro.

Vale registrar o que isso ensina sobre o teste: **duas abas do mesmo perfil
do Chrome compartilham os cookies**, então não são duas pessoas — são uma
sessão só, a última que entrou. Para valer, é uma janela normal e uma
anônima.

**O stream reentregava o histórico numa conexão nova.** Com `curl` através
do Traefik, uma conexão recém-aberta recebeu doze eventos de execuções
anteriores do roteiro — tudo o que o Redis ainda guardava dentro da hora de
TTL. No navegador o efeito seria a janela somando não lidas já contadas
assim que fosse aberta, até a sondagem seguinte desfazer o engano. A causa
era começar do id `0` quando não há `Last-Event-ID`. Corrigido com
`streaming.tail_id`: conexão nova começa do **fim** da caixa, porque o
cliente acabou de carregar o estado verdadeiro do PostgreSQL; reconexão
continua retomando exatamente de onde parou, que é o que o `EventSource`
manda sozinho. A seção 10 do roteiro trava a regressão.

**O próprio roteiro tinha duas asserções erradas.** A primeira exigia que o
JSON escapasse `<` — o que mutilaria a mensagem de quem legitimamente
escreve `<`, e que não é o que protege: um `<script>` dentro de
`application/json` não executa, e `nosniff` impede o navegador de adivinhar
outro tipo. Trocada pelas três camadas que de fato respondem (corpo
intacto, tipo correto com nosniff, cliente sem escrita de HTML). A segunda
procurava a palavra `innerHTML` no arquivo inteiro e acusava o próprio
cabeçalho do JavaScript, que diz em prosa que `innerHTML` não é usado — um
roteiro que falha por causa da documentação da regra que ele verifica é um
roteiro que será desligado na primeira vez que atrapalhar. Agora tira os
comentários antes de procurar.

### Verificação manual que o roteiro não cobre

- [ ] arrastar pela barra de título e soltar fora da tela: a janela volta
      com pelo menos 80 px visíveis
- [ ] redimensionar pela alça, recarregar a página: tamanho e posição
      voltam como estavam (`localStorage`)
- [ ] janela aberta, navegar para outra tela: continua aberta
- [ ] duas abas da mesma pessoa: a mensagem enviada numa aparece na outra,
      **uma vez só** (deduplicação por id da mensagem)
- [ ] abaixo de 576 px a janela ocupa a tela inteira, o arrasto some e o
      botão "voltar" alterna entre a lista e a conversa
- [ ] pele escura (`html.app-skin-dark`): janela, bolhas e lista legíveis
- [ ] com o Redis parado: a mensagem ainda é enviada e gravada; o que se
      perde é o aviso ao vivo e a bolinha de presença

## Pendências conhecidas

- **Retenção e expurgo não estão definidos** — ver decisão 2 acima. Nada é
  apagado por conta própria hoje.
- **Sem anexo, sem edição, sem apagar mensagem.** Deliberado nesta
  primeira versão: cada um deles é uma decisão de retenção disfarçada de
  funcionalidade.
- **Sem grupo.** O esquema comporta; a tela ainda não.
- **Sem registro em auditoria por mensagem.** A trilha existe para acesso a
  dado clínico; uma linha de `AuditEvent` por mensagem trocada encheria a
  trilha de ruído e tornaria mais difícil achar o que ela guarda. Abertura
  de conversa e envio ficam fora até haver uma decisão explícita.
