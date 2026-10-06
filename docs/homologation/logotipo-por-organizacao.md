# O logotipo é o da organização aberta

**Defeito encontrado em uso real, em 2026-10-05.** Uma secretária que
atende em duas clínicas — Freua Serviços Médicos e CALDAS, REGO E URBANO
SERVICOS MEDICOS LTDA — entrou, escolheu a primeira, trocou para a
segunda, e **o logotipo continuou o da primeira**. O nome da clínica no
menu mudou; a imagem ao lado dele, não.

A pergunta que isso levanta é a certa, e a resposta é tranquilizadora
pela metade: **não houve vazamento entre inquilinos**. O servidor sempre
respondeu com a imagem da organização da sessão. O que mostrou a imagem
errada foi o **cache do navegador**, e o furo era nosso.

## O que foi conferido no servidor antes de concluir isso

Na própria instalação em produção, com as duas organizações reais:

| Organização | `logo_path` | md5 do arquivo |
| --- | --- | --- |
| Freua Serviços Médicos | `/data/media/7883ef6f…/branding/logo.png` | `4d995abe…` (680 131 bytes) |
| CALDAS, REGO E URBANO | `/data/media/8c980d53…/branding/logo.png` | `481ad6e0…` (47 942 bytes) |

Dois diretórios, dois arquivos, dois conteúdos. E, reproduzindo a troca
de organização **na mesma sessão** do vínculo real da secretária, o
servidor devolveu `4d995abe…` na primeira e `481ad6e0…` na segunda. O
banco e o disco estavam corretos o tempo todo.

## A causa

`/app/org/clinica/logotipo.img` é o **mesmo endereço para todas as
clínicas**, de propósito: a rota não aceita id de organização porque um
endereço que aceitasse seria um enumerador de logotipos de toda a
instalação. O que ela devolve depende do `tenant_id` que está **dentro da
sessão**.

O cache do navegador não enxerga sessão. Ele indexa por URL e pelos
cabeçalhos que o `Vary` indicar. A resposta trazia `Vary: Cookie`, posto
pela sessão do Django — e esse `Vary` não separa nada aqui, porque
**trocar de organização não troca o cookie**: `switch_tenant` escreve
`tenant_id` na mesma sessão, com a mesma chave e o mesmo cookie.

Resultado: URL igual, cookie igual, e um `Cache-Control: private,
max-age=300` dizendo ao navegador que podia reusar o que tinha por cinco
minutos sem perguntar nada. Dentro dessa janela, a troca de organização
exibia o logotipo anterior. Fora dela, funcionava — o que explica por que
o defeito nunca apareceu em teste: quem testa troca de organização
raramente espera cinco minutos entre uma coisa e outra, e quem *espera*
cinco minutos não vê defeito nenhum.

Vale registrar o que o defeito **não** alcançava:

- `private` impede cache compartilhado, e `Vary: Cookie` separa sessões.
  A imagem ficou no navegador de quem tinha vínculo com as duas clínicas
  e nunca chegou a um terceiro.
- Os documentos em PDF nunca erraram. O timbre é desenhado no servidor,
  por `documents/pdf/common.py::_logo_flowable`, que lê o arquivo da
  clínica do documento — não passa por cache de navegador nenhum.
- O menu só desenha a imagem quando a clínica **tem** logotipo
  (`nd_clinic_has_logo`, recalculado a cada requisição). Uma clínica sem
  logotipo mostra o escudo genérico, nunca a imagem de outra. O caso
  relatado é o das duas clínicas com logotipo.

## A correção

Em `tenancy/admin_views.py::ClinicLogoFileView`, a resposta passou de
`private, max-age=300` para **`private, no-cache` com `ETag`**, e o
validador vem de `tenancy/branding.py::logo_etag` — um HMAC sobre o
`tenant_id`, a data do envio e o tamanho do arquivo.

`no-cache` não é `no-store`: a imagem continua guardada no navegador, só
que ele pergunta antes de usar. Quando nada mudou, a resposta é um 304 de
algumas dezenas de bytes — contra os 680 KB de um logotipo real, o ganho
é o mesmo de antes, sem a janela de cinco minutos mostrando a clínica
errada. E como o validador carrega o inquilino, a pergunta do navegador
com o `ETag` da clínica anterior **não** pode ser respondida com 304.

Ele é HMAC, e não `tenant_id` cru, porque validador é cabeçalho que o
cliente guarda e devolve: ele não precisa dizer qual é a organização para
fazer o seu trabalho.

### A alternativa recusada

Pôr `?v=<data do envio>` na URL — que é o que a tela de identidade da
clínica (`templates/tenancy/clinic.html`) **já fazia**. Resolve, e foi
exatamente o que falhou: a correção morava no template, uma tela a tinha,
a outra não, e quem desenhasse a próxima tela com o logotipo não teria
como saber que precisava lembrar dela. O remendo foi retirado junto com a
correção; agora não há o que lembrar.

## A regra que fica

**Um endereço só pode ficar guardado por tempo fixo no navegador quando a
própria URL diz o que ele devolve.** Se o que ele devolve depende da
sessão, `max-age` é promessa que o servidor não pode cumprir.

A foto do paciente (`/app/patients/<uuid>/foto.img`) continua com
`private, max-age=300` e está certa pela regra: o id na rota é único na
instalação inteira, então a entrada de cache já distingue o que serve.
`check_logotipo.py` **procura** no código quem serve com prazo fixo e
reprova o que não estiver na lista justificada — a mesma forma de
`check_idioma.py`, pelo mesmo motivo: lista escrita à mão envelhece.

## Verificação

`checks/check_logotipo.py`, em sete seções:

1. Cada clínica grava o seu arquivo, em caminhos distintos.
2. A mesma sessão, trocando de organização, recebe bytes diferentes — e
   os validadores das duas são diferentes.
3. **O defeito, reproduzido:** revalidar com o `ETag` da clínica anterior
   depois da troca tem de devolver 200 com a imagem nova, nunca 304. E o
   contrário, para a correção não virar "rebaixar 680 KB a cada tela":
   revalidar sem mudança tem de devolver 304.
4. Trocar o logotipo chega na hora a quem tem o anterior em cache.
5. A varredura do `max-age` descrita acima, mais o cabeçalho da resposta.
6. Nenhum template remenda o cache por conta própria.
7. A fronteira de antes continua: sem sessão não há logotipo, e a rota
   continua sem aceitar id de organização.

## O que a revisão de isolamento não tinha olhado

`docs/homologation/isolation.md` tem uma seção "Cache" que conclui, com
razão no que examina, que nada sensível ao inquilino passa pelo cache
compartilhado do Django. O que ela não examinou foi o **cache do
navegador** — que não é infraestrutura nossa, e por isso não aparece numa
busca por `cache.set` no código-fonte. É uma classe inteira de
isolamento: não a de dados que vazam entre contas, mas a de uma tela que
mostra a organização errada para quem tem acesso às duas.
