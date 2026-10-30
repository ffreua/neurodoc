"""Os endereços fixos da raiz: robots, sitemap, ícones e manifesto.

Módulo próprio, sem `app_name`, e incluído em `core/urls.py` **antes** de
qualquer outro `path('')`. São nomes de arquivo, e nome de arquivo não
pertence a app de domínio nenhum: `/favicon.ico` é do navegador,
`/robots.txt` é do rastreador.

Sem namespace de propósito. Um `{% url 'onboarding:favicon' %}` seria uma
indireção para um caminho que, por definição, não pode mudar — o
navegador pede `/favicon.ico` literal, sem ler o HTML.
"""
from django.urls import path

from .seo_views import ATIVOS, AtivoDaRaiz, LlmsView, ManifestView, RobotsView, SitemapView

urlpatterns = [
    path('robots.txt', RobotsView.as_view(), name='robots'),
    path('sitemap.xml', SitemapView.as_view(), name='sitemap'),
    path('site.webmanifest', ManifestView.as_view(), name='webmanifest'),
    path('llms.txt', LlmsView.as_view(), name='llms'),
    # O nome que às vezes se pede no singular: o mesmo texto, sem redirecionar
    # (robô que não segue redirecionamento não perde a leitura).
    path('llm.txt', LlmsView.as_view(), name='llm'),
] + [
    path(nome, AtivoDaRaiz.as_view(), {'nome': nome}, name='ativo-%s' % nome)
    for nome in ATIVOS
]
