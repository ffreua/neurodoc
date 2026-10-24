# SEO, ícones e indexação — homologação

**Data:** 2026-10-03 · **Roteiro:** `checks/check_seo.py` ·
**Código:** `base/seo.py`, `base/seo_views.py`, `base/public_urls.py`,
`templates/partials/head.html`, `scripts/gerar_icones.py`

---

## 1. O defeito que estava no ar

Antes desta entrega, **toda página do NeuroDoc servia
`<title>NeuroDoc</title>`** — inclusive a página de vendas, que declara o
próprio título na terceira linha do template.

A causa é de uma linha: `partials/head.html` entra por `{% include %}`, e
o `<title>` morava lá dentro, envolvido em `{% block title %}`. **Bloco
não atravessa include.** Os noventa e nove `{% block title %}` espalhados
pelos templates eram todos letra morta.

Nada quebra, nada vai para o log, e o sintoma só existe em dois lugares
onde ninguém olha ao conferir uma tela: a aba do navegador e a primeira
linha do resultado de busca.

O conserto foi mover o `<title>` para dentro de cada shell
(`base.html`, `base_auth.html`, `base_public.html`), onde o bloco do
filho de fato chega:

```html
<title>{% block title %}{{ nd_seo.titulo }}{% endblock %}</title>
```

O padrão — para quem não declara bloco nenhum — vem do catálogo.

Além do título, a instalação não tinha **nada**: sem `description`, sem
canônica, sem `robots`, sem Open Graph, sem dados estruturados, sem
`robots.txt` (404), sem `sitemap.xml` (404) e sem `favicon.ico` (404). O
ícone era um SVG embutido em `data:` com a letra N em fonte do sistema.

## 2. A decisão central: um catálogo, não uma anotação por página

`base/seo.py::PAGINAS` enumera **as páginas que podem ser indexadas**.
Dela saem, ao mesmo tempo:

- o `<title>` padrão, a `description` e a `<link rel=canonical>`;
- o `<meta name="robots">` de **toda** página do produto;
- as linhas do `sitemap.xml`;
- o grafo JSON-LD de cada página.

O que isso compra é a impossibilidade de uma contradição clássica: um
`sitemap.xml` que anuncia uma página marcada `noindex`. Como as duas
coisas leem a mesma lista, a contradição não tem onde nascer.

**A lista é de permissão.** O que não está nela sai `noindex, nofollow`
— `/app/`, `/accounts/`, `/instalacao/`, `/admin/`, o portal do paciente,
o link de entrega e a verificação por token. Uma rota nova nasce privada.
Escrita ao contrário (uma lista de exclusões), a primeira rota a vazar
seria justamente a que ninguém lembrou de listar. É a mesma escolha que
`nd_can` faz no menu: errar para o lado de esconder.

| Página | Indexada | Prioridade |
| --- | --- | --- |
| `/` | sim | 1.0 |
| `/ajuda/` | sim | 0.8 |
| `/ajuda/perguntas/` | sim | 0.7 |
| `/ajuda/<slug>/` (23 artigos) | sim | 0.6 |
| `/contrato/` | sim | 0.4 |
| `/verificar/` (formulário em branco) | sim | 0.3 |
| `/verificar/<token>/` | **não** | — |
| todo o resto | **não** | — |

Vinte e oito endereços no sitemap. O roteiro abre **todos** e confere que
cada um responde 200, sai `index` e aponta a canônica para si mesmo.

## 3. A canônica não segue o `Host:`

`seo.absoluta()` monta tudo a partir de `PUBLIC_BASE_URL`, nunca do
cabeçalho `Host:` da requisição — que é um valor do cliente. Com o
`Host:` um pedido forjado faria a página declarar que o original está em
outro domínio, que é exatamente o que uma canônica significa. O roteiro
cobra isso com um cliente de `Host` trocado.

É a mesma razão pela qual o `sitemap.xml` não usa `django.contrib.sitemaps`:
aquele app resolve o domínio pelo framework `sites` (uma tabela no banco
para guardar o que já está no `.env`) ou pelo `Host:`.

## 4. Dados estruturados sem inventar número

O JSON-LD da raiz declara `WebSite`, `Organization`, `Person`,
`SoftwareApplication` e `FAQPage`, ligados por `@id` para serem **um**
grafo e não cinco entidades soltas.

Nada ali é escrito à mão:

- o preço de cada `Offer` é `price_monthly × 12`, lido de
  `tenancy/plans.py`, em aritmética inteira de centavos;
- as perguntas do `FAQPage` são as de `base/content.py::FAQ`, as mesmas
  que a página mostra;
- `featureList` são os títulos de `RECURSOS`;
- o `Person` é o autor de `AUTOR` — formação e área, que é o sinal de
  origem que o Google pesa em assunto de saúde.

**Não há `aggregateRating`.** Nota inventada é a infração que o Google
pune com remoção do resultado rico, e aqui seria também falso
testemunho sobre produto de saúde — a mesma regra do topo de
`base/content.py`.

Dois cuidados técnicos que o roteiro cobra:

- o bloco leva `nonce="{{ nd_csp_nonce }}"`. `script-src` não tem
  `unsafe-inline`, e a política aplicada não distingue um bloco de JSON
  de um bloco de código: sem nonce o navegador **descarta o JSON-LD
  inteiro em silêncio**, e só o relatório de CSP contaria;
- `<`, `>` e `&` saem escapados em notação unicode de JSON (`\u003C` e
  companhia) — a mesma tabela do `|json_script` do Django, e a mesma
  razão. Sem isso, um `</script>`
  escrito em qualquer texto do catálogo fecharia o bloco no meio e
  jogaria o resto do JSON na tela.

## 5. Os ícones, e por que eles não saem de `{% static %}`

`scripts/gerar_icones.py` desenha a família inteira de **uma geometria
só** e escreve em `static/brand/`. Roda à mão; o resultado vai
versionado. Gerar PNG em tempo de resposta acrescentaria uma dependência
de imagem ao caminho que serve prontuário, para um desenho que muda uma
vez por ano.

A marca é o monograma **N** em traço único sobre um traçado de pulso.
São **duas variantes da mesma marca**, e a razão é tamanho: em 16 px o
pulso tem meio pixel de espessura, some no antialiasing e deixa uma
sujeira cinza sob o N. Então:

| Arquivo | Variante | Onde aparece |
| --- | --- | --- |
| `favicon.ico` (16/32/48) | só o monograma | aba, atalho do Windows |
| `neurodoc-mark.svg` | só o monograma | `rel=icon` vetorial, e a marca do cabeçalho e do rodapé |
| `apple-touch-icon.png` (180) | completa | atalho do iOS |
| `icon-192.png`, `icon-512.png` | completa | aplicativo instalável |
| `icon-maskable-512.png` | completa, 60% do quadrado | launcher do Android, que recorta |
| `og-image.png` (1200×630) | completa + texto | cartão do WhatsApp, LinkedIn, X |

**Servidos por caminho fixo da raiz** (`base/seo_views.py`), e não por
`{% static %}`. Nesta instalação o estático vai para `/static/<sha>/`,
com o SHA do commit no caminho — ótimo para cache e inútil aqui: o
navegador pede `/favicon.ico` sem ler o HTML, o Google pede
`/robots.txt` sem ler o HTML, e o WhatsApp guarda a imagem do cartão
**pela URL** — uma URL nova a cada publicação faz o cartão ser
redescoberto do zero toda vez.

O `Cache-Control` desses caminhos é de **um dia**, não `immutable`:
como o endereço é fixo, o conteúdo pode mudar, e um ano de cache tornaria
a troca do ícone invisível por um ano.

A marca também substituiu a letra `N` em CSS no cabeçalho público, no
rodapé, no cartão de autenticação e na barra lateral do aplicativo — o
mesmo desenho do favicon, para a aba e a tela não mostrarem marcas
diferentes.

## 6. O posicionamento: neuro, e qualquer especialidade

A página falava só de neurologia, de ponta a ponta. Um clínico, um
ortopedista ou um psiquiatra que chegasse por busca lia "pares cranianos,
NIHSS, Hoehn e Yahr" e concluía em dez segundos que o produto não era
para ele — e ia embora antes de ver o preço.

Entrou `base/content.py::ESPECIALIDADES` e a seção `#especialidades` na
página, **entre a lista de recursos e os planos**: é onde a objeção
nasce. Depois dos planos seria tarde; antes da lista seria responder
antes da pergunta.

A seção separa o que serve a qualquer especialidade (atendimento em
texto livre, agenda, receita com as 26 mil apresentações da CMED,
documento assinado, CID-10 e TUSS completos, convênio e honorário,
portal, IA) do que é de neurologia (o roteiro de 387 itens e as catorze
escalas).

**A linha de fecho responde "e eu, como uso isto?"** — a pergunta que as
duas colunas deixam em pé. Quem atende fora da neurologia evolui em
texto livre, a folha em branco com a consulta anterior ao lado, e usa o
resto inteiro. Sem essa frase, quem lê que o roteiro de exame é de
neurologia fica sem saber por onde entra.

A mesma resposta entrou no FAQ da página — "Como o NeuroDoc serve para
outras especialidades?", a **primeira** pergunta, porque enquanto ela não
é respondida nenhuma resposta sobre sigilo ou assinatura muda coisa
alguma para quem não é neurologista. Estando no FAQ, ela entra também no
`FAQPage` do JSON-LD, que é o que o Google pode mostrar a quem procura
"prontuário eletrônico" sem dizer especialidade nenhuma.

Também mudaram:

- o H1, de "O prontuário que entende o exame neurológico" para "O
  **prontuário eletrônico** que entende o exame neurológico" — o termo
  pelo qual se procura o produto era a única palavra que faltava numa
  frase que já estava certa;
- o selo acima do H1, que dizia "Neurologia e neurocirurgia" e passou a
  dizer "Neurologia, neurocirurgia — e qualquer especialidade";
- o parágrafo do rodapé, que é o último texto que o visitante lê.

## 7. Google Search Console

`GOOGLE_SITE_VERIFICATION` no `.env` emite
`<meta name="google-site-verification">` em todas as páginas. Vazio — o
padrão — não emite tag nenhuma, que é o certo para uma instalação que não
vai ser indexada.

Em variável de ambiente, e não escrito no template, porque é **por
instalação**: quem subir o NeuroDoc no próprio domínio tem outro token, e
um token fixo no HTML versionado faria toda instalação declarar a
propriedade da nossa. A chave entra em `OPTIONAL_KEYS` de
`ops/make_runtime.py`, junto com as outras que têm padrão.

Depois de verificado, o token **fica**: o Google revalida de tempos em
tempos e tira a propriedade de quem removeu a tag.

## 8. Resultado do roteiro

`checks/check_seo.py`, dez seções, nenhuma falha:

1. o título chega à página — o da raiz é o do catálogo, e o da tela de
   entrada é o que ela declara (a asserção que teria pego o defeito);
2. a lista é de permissão — raiz e ajuda `index`; entrada, lista de
   pacientes e verificação por token `noindex`, sem canônica e sem cartão;
3. `robots.txt` barra as seis famílias de rota privada e libera
   `/verificar/$` **antes** de barrar a pasta;
4. as 28 URLs do sitemap abrem, saem `index` e apontam a si mesmas;
5. a canônica não segue um `Host:` forjado;
6. nenhuma descrição curta ou longa demais, nenhum título longo demais;
7. JSON-LD válido, com nonce, com preço vindo de `tenancy.plans`, com o
   FAQ do mesmo tamanho do da página, e `</script>` escapado;
8. os ícones respondem na raiz com os bytes certos — o `.ico` é um ICO
   com três tamanhos dentro, o cartão mede 1200×630;
9. a seção de especialidades está na página, com a linha de fecho, e a
   pergunta de encaixe está no FAQ e no JSON-LD;
10. sem token configurado, nenhuma tag de verificação vazia é emitida.

Bateria completa: **89 roteiros**, nenhuma falha.
