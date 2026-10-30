"""O que um rastreador pede antes de pedir uma página.

`robots.txt`, `sitemap.xml`, `favicon.ico`, os ícones do aplicativo
instalável e o cartão de compartilhamento. Tudo **na raiz**, e aqui está
a razão de existir um módulo em vez de uma pasta de arquivos estáticos:
nesta instalação o estático é servido em `/static/<sha>/`, com o SHA do
commit no caminho. Isso é ótimo para cache — nada expira errado — e
inútil para quem não lê HTML: o navegador pede `/favicon.ico` direto, o
Google pede `/robots.txt` direto, e o endereço deles não pode mudar a
cada publicação. O cartão do Open Graph tem o mesmo problema pelo outro
lado: o WhatsApp guarda a imagem por URL, e uma URL nova a cada deploy
faz o cartão ser rebaixado e rebaixado.

Então estes poucos arquivos saem daqui, por caminho fixo, lidos do
diretório de origem (`static/brand/`) e não do coletado — o coletado tem
o nome com hash, que é justamente o que não serve.

**`sitemap.xml` sai de `base/seo.py`**, da mesma lista que decide o
`<meta name="robots">` de cada página. Um sitemap escrito à parte
anunciaria, mais cedo ou mais tarde, uma página marcada `noindex`.
"""
import mimetypes
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.views import View

from . import seo

#: Onde o desenho mora. O diretório de origem, de propósito: o coletado
#: leva hash no nome e não responde por `favicon.ico`.
MARCA = Path(settings.BASE_DIR) / 'static' / 'brand'

#: Caminho público -> arquivo em `static/brand/`.
#:
#: `site.webmanifest` não está aqui porque é montado (precisa das URLs
#: absolutas); o resto é byte por byte o que o gerador escreveu.
ATIVOS = {
    'favicon.ico': 'favicon.ico',
    'apple-touch-icon.png': 'apple-touch-icon.png',
    # O iOS pede este nome quando a página não declara o `link`. Declarar
    # custa uma linha e economiza um 404 em todo iPhone que salva o atalho.
    'apple-touch-icon-precomposed.png': 'apple-touch-icon.png',
    'icon-192.png': 'icon-192.png',
    'icon-512.png': 'icon-512.png',
    'icon-maskable-512.png': 'icon-maskable-512.png',
    'og-image.png': 'og-image.png',
    'neurodoc-mark.svg': 'neurodoc-mark.svg',
}

#: Um dia. Não é `immutable` como o estático versionado: estes caminhos
#: são fixos, então o conteúdo deles **pode** mudar, e um ano de cache
#: tornaria a troca do ícone invisível por um ano.
CACHE = 'public, max-age=86400'


class AtivoDaRaiz(View):
    """Serve um dos arquivos de `ATIVOS` por caminho fixo."""

    def get(self, request, nome):
        arquivo = ATIVOS.get(nome)
        if arquivo is None:
            raise Http404
        caminho = MARCA / arquivo
        if not caminho.is_file():
            raise Http404
        tipo = mimetypes.guess_type(arquivo)[0] or 'application/octet-stream'
        return FileResponse(caminho.open('rb'), content_type=tipo, headers={
            'Cache-Control': CACHE,
            'X-Content-Type-Options': 'nosniff',
        })


class RobotsView(View):
    """`/robots.txt`.

    **O que é liberado é liberado por omissão; o que importa são as
    recusas.** Cada linha `Disallow` abaixo existe por uma razão
    diferente, e vale anotá-las porque a tentação de "simplificar isto
    num bloco só" aparece a cada leitura:

    - `/app/` e `/accounts/` devolvem 404 ou login a quem não tem
      vínculo. Rastreá-las não vaza nada, mas queima orçamento de
      rastreamento num site que tem seis páginas que valem a pena;
    - `/d/`, `/solicitacoes/` e `/descadastrar/` são **endereços de uma
      pessoa só** — a entrega de um documento, o pedido de uma receita, o
      descadastro de um contato. Não são segredo (o token é), e também
      não são página;
    - `/verificar/` é a exceção interessante: o formulário em branco é
      útil e entra no sitemap, mas `/verificar/<token>/` mostra tipo de
      documento, médico e data. Daí o `Allow` de uma linha só, com `$`,
      **antes** do `Disallow` da pasta;
    - `/instalacao/`, `/admin/` e `/technical-docs/` são o console de
      quem opera o servidor.

    `robots.txt` não é controle de acesso — quem obedece é robô educado.
    O que impede o acesso de verdade continua sendo `TenantMiddleware`, a
    sessão e o token; isto aqui só evita que o Google gaste a visita dele
    e a nossa em porta fechada.
    """

    def get(self, request):
        linhas = [
            'User-agent: *',
            'Allow: /verificar/$',
            'Disallow: /app/',
            'Disallow: /accounts/',
            'Disallow: /admin/',
            'Disallow: /instalacao/',
            'Disallow: /technical-docs/',
            'Disallow: /csp-report/',
            'Disallow: /d/',
            'Disallow: /solicitacoes/',
            'Disallow: /descadastrar/',
            'Disallow: /verificar/',
            'Disallow: /signup/',
            'Disallow: /invite/',
            'Disallow: /comecar-gratis/',
            '',
            'Sitemap: ' + seo.absoluta('/sitemap.xml'),
            # Não é diretiva do padrão: é o aviso, para quem lê o arquivo,
            # de onde está o resumo para modelos de linguagem.
            '# llms.txt: ' + seo.absoluta('/llms.txt'),
            '',
        ]
        return HttpResponse('\n'.join(linhas), content_type='text/plain; charset=utf-8',
                            headers={'Cache-Control': CACHE})


class SitemapView(View):
    """`/sitemap.xml`, montado de `seo.PAGINAS`.

    XML escrito à mão em vez de `django.contrib.sitemaps` por um motivo
    só: aquele app resolve o domínio pelo framework `sites` ou pelo
    cabeçalho `Host:` da requisição. O primeiro é uma tabela no banco
    para guardar o que já está no `.env`; o segundo é um valor que o
    cliente manda — e um sitemap com o domínio de outra pessoa é um
    presente. Aqui o endereço vem de `PUBLIC_BASE_URL`, como o resto.
    """

    def get(self, request):
        partes = ['<?xml version="1.0" encoding="UTF-8"?>',
                  '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for pagina in seo.paginas_do_sitemap():
            partes.append(
                '  <url><loc>%s</loc><lastmod>%s</lastmod>'
                '<changefreq>%s</changefreq><priority>%s</priority></url>' % (
                    escape(seo.absoluta(pagina.caminho)), pagina.atualizado.isoformat(),
                    pagina.frequencia, pagina.prioridade,
                )
            )
        partes.append('</urlset>')
        return HttpResponse('\n'.join(partes) + '\n',
                            content_type='application/xml; charset=utf-8',
                            headers={'Cache-Control': CACHE})


class LlmsView(View):
    """`/llms.txt` (e `/llm.txt`): o produto explicado a um modelo de linguagem.

    A proposta de llmstxt.org: um Markdown curto, na raiz, que um assistente
    lê antes de responder "o que é o NeuroDoc" ou "quanto custa". Montado
    das mesmas fontes da página — `base/seo.py`, `tenancy/plans.py`,
    `base/help_content.py` —, e nunca escrito à parte: um texto para robô
    que envelhece separado da vitrine responde preço antigo com toda a
    confiança, e é exatamente o número que o visitante vai conferir.

    Só o que é público: a vitrine, o manual e o contrato. Nada de `/app/`.
    """

    def get(self, request):
        from base.help_content import ARTICLES
        from tenancy.plans import PUBLIC_ORDER, PLANS, pricing

        def linha_do_plano(code):
            plano, preco = PLANS[code], pricing(code)
            medicos = plano['max_doctors']
            limites = (
                f"até {plano['max_patients']:,} pacientes ativos e {medicos} médico{'s' if medicos != 1 else ''}"
                .replace(',', '.')
                if plano['max_patients'] else 'pacientes e médicos sem limite fixo'
            )
            if preco['free']:
                valor = 'Grátis, sem prazo e sem cartão'
            elif not preco['quoted']:
                valor = 'Valores combinados caso a caso'
            else:
                valor = 'Pagamento ' + '; '.join(
                    f"{p['label'].lower()}: {p['mensal']}/mês ({p['pagamento']} {p['por']}, "
                    f"{p['ano']} em 12 meses{', ' + str(p['desconto']) + '% de desconto' if p['desconto'] else ', preço cheio'})"
                    for p in preco['periodos']
                )
            return f"- **{plano['label']}** — {limites}. {valor}."

        base = seo.absoluta('')
        partes = [
            '# NeuroDoc',
            '',
            '> ' + seo.RESUMO,
            '',
            'Prontuário eletrônico e gestão de consultório em português, feito por um '
            'neurologista para neurologia e neurocirurgia e utilizável por qualquer '
            'especialidade. Funciona no navegador; os dados ficam no Brasil, sob a LGPD.',
            '',
            '## Planos e preços',
            '',
            'Contrato de 12 meses. Nos planos pagos, o pagamento pode ser anual '
            '(desconto de lançamento), semestral (5% de desconto) ou trimestral (preço cheio).',
            '',
            *[linha_do_plano(code) for code in PUBLIC_ORDER],
            '',
            '## Páginas',
            '',
            f'- [Página do produto]({base}/): recursos, planos e perguntas frequentes',
            f'- [Manual de uso]({base}/ajuda/): os processos do sistema, passo a passo',
            f'- [Contrato de adesão]({base}/contrato/): o texto em vigor',
            f'- [Verificar documento]({base}/verificar/): conferir receita ou laudo assinado pelo QR',
            '',
            '## Manual',
            '',
            *[f"- [{a['title']}]({base}/ajuda/{a['slug']}/): {a['summary']}" for a in ARTICLES],
            '',
        ]
        return HttpResponse('\n'.join(partes), content_type='text/plain; charset=utf-8',
                            headers={'Cache-Control': CACHE})


class ManifestView(View):
    """`/site.webmanifest` — o que torna a página instalável no celular.

    Vale para um produto que se usa no consultório com o telefone na
    mão: salvo na tela inicial, abre em tela cheia e com o ícone certo em
    vez da miniatura da página.

    `start_url` aponta para `/app/`, e não para a raiz: quem instalou já
    é cliente, e a página de vendas não é a tela que essa pessoa quer ver
    ao tocar no ícone.
    """

    def get(self, request):
        import json

        dados = {
            'name': 'NeuroDoc — prontuário eletrônico',
            'short_name': 'NeuroDoc',
            'description': seo.RESUMO,
            'lang': 'pt-BR',
            'start_url': '/app/',
            'scope': '/',
            'display': 'standalone',
            'background_color': '#ffffff',
            # O primário do tema: é a cor da barra de status no Android.
            'theme_color': '#3454d1',
            'icons': [
                {'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
                {'src': '/icon-maskable-512.png', 'sizes': '512x512',
                 'type': 'image/png', 'purpose': 'maskable'},
            ],
        }
        return HttpResponse(json.dumps(dados, ensure_ascii=False, indent=2),
                            content_type='application/manifest+json; charset=utf-8',
                            headers={'Cache-Control': CACHE})
