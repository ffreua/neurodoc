"""A central de ajuda: manual por processo e perguntas de uso.

**Pública, sem login.** Duas razões: quem está avaliando o sistema precisa
ver como ele funciona antes de ter conta, e quem já usa costuma procurar
ajuda no celular, fora da sessão aberta no consultório. Não há dado de
paciente real aqui — as capturas saem do banco de demonstração.

Fica em `base`, junto da página inicial, porque é a mesma superfície
pública e o mesmo shell (`base_public.html`).
"""

from django.http import Http404
from django.shortcuts import render
from django.views import View

from .help_content import ARTICLES, FAQ_USO, article_by_slug


def _passos_renderizados(article):
    """Os passos com o texto de Markdown convertido em HTML.

    Convertido aqui, e nao no template com `|safe`: o texto do manual usa
    `**negrito**` e crase para nome de campo, e passar a string crua com
    `|safe` mostrava os asteriscos na tela.

    `render_markdown` escapa **antes** de converter, entao HTML literal
    escrito no manual vira texto inerte em vez de markup -- o que importa
    porque esta pagina e publica e o mesmo renderizador serve a saida da
    IA.
    """
    from ai.rendering import render_markdown

    return [
        {'texto': render_markdown(texto), 'imagem': imagem, 'legenda': legenda}
        for texto, imagem, legenda in article['steps']
    ]


class HelpIndexView(View):
    def get(self, request):
        return render(request, 'help/index.html', {
            'articles': ARTICLES,
            'faq': FAQ_USO,
            'leads_email': _leads_email(),
        })


class HelpArticleView(View):
    def get(self, request, slug):
        artigo = article_by_slug(slug)
        if artigo is None:
            raise Http404
        # Anterior e próximo: o manual se lê em ordem na primeira vez, e
        # voltar ao índice a cada processo quebra a leitura.
        indice = ARTICLES.index(artigo)
        return render(request, 'help/article.html', {
            'article': artigo,
            'passos': _passos_renderizados(artigo),
            'articles': ARTICLES,
            'anterior': ARTICLES[indice - 1] if indice > 0 else None,
            'proximo': ARTICLES[indice + 1] if indice + 1 < len(ARTICLES) else None,
            'leads_email': _leads_email(),
        })


class HelpFaqView(View):
    def get(self, request):
        return render(request, 'help/faq.html', {
            'faq': FAQ_USO, 'articles': ARTICLES, 'leads_email': _leads_email(),
        })


def _leads_email():
    from django.conf import settings

    return settings.LEADS_EMAIL
