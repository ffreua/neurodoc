"""Como o NeuroDoc se apresenta a quem ainda não é cliente.

Título, descrição, canônica, Open Graph, dados estruturados, `robots.txt`
e `sitemap.xml` saem todos **desta lista**, e não de cada template. A
razão é a mesma que põe preço e limite em `tenancy/plans.py`: quando a
mesma informação é escrita em dois lugares, um dos dois envelhece sem que
ninguém perceba — e aqui os dois lugares seriam o `<meta name="robots">`
de uma página e a linha dela no `sitemap.xml`. Um sitemap que anuncia uma
página marcada `noindex` é o erro clássico, e o Search Console o reporta
como "Página excluída por 'noindex'" semanas depois, sem dizer de onde
veio.

**A lista é de permissão, nunca de negação.** `PAGINAS` enumera o que
pode ser indexado; tudo que não está aqui sai com `noindex, nofollow` —
`/app/`, `/accounts/`, `/instalacao/`, o portal do paciente, o link de
entrega de documento e a verificação por token. Escrito ao contrário, uma
rota nova nasceria indexável por omissão, e a primeira a vazar seria
justamente a que ninguém lembrou de listar. É a mesma escolha de
`nd_can`: errar para o lado de esconder.

**O título não mora no template.** Morava, em `{% block title %}` — e não
funcionava: `partials/head.html` entra por `{% include %}`, e bloco não
atravessa include. Toda página do produto servia `<title>NeuroDoc</title>`
desde sempre, inclusive a de vendas, que declarava o próprio título três
linhas acima e era ignorada. O `<title>` passou para dentro de cada shell
(`base.html`, `base_public.html`, `base_auth.html`), onde o bloco de fato
chega; o que vem daqui é o padrão de quem não declara nenhum.

**Dados estruturados sem inventar nada.** O JSON-LD repete o que já está
em `base/content.py` e `tenancy/plans.py` — preço de oferta lido do
catálogo, pergunta e resposta lidas do FAQ da própria página. Marcação
que afirma o que a página não mostra é penalizada pelo Google e, num
produto de saúde, é promessa falsa com outro nome.
"""
import json
from dataclasses import dataclass
from datetime import date

from django.conf import settings

from tenancy.contract import CONTRATADO

#: Data da última revisão do conteúdo público, para o `lastmod` do
#: sitemap. À mão de propósito: `localdate()` faria toda página parecer
#: atualizada em toda publicação, o rastreador aprenderia que o sinal não
#: significa nada e passaria a ignorá-lo. Mexer no texto é mexer aqui.
ATUALIZADO = date(2026, 10, 29)

#: O que o produto responde quando perguntam "isso é o quê". Entra na
#: descrição da raiz, no JSON-LD e no cartão de compartilhamento.
RESUMO = (
    'Prontuário eletrônico com exame neurológico estruturado, escalas, '
    'receita assinada, agenda e IA revisada pelo médico. '
    'Atende qualquer especialidade.'
)

#: `max-snippet:-1` e `max-image-preview:large` pedem ao Google o trecho e
#: a imagem sem corte. O padrão europeu, herdado da diretiva de direitos
#: autorais, encolhe os dois — e um resultado de busca com duas linhas de
#: trecho perde clique para um com cinco.
INDEXAVEL = 'index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1'
OCULTO = 'noindex, nofollow'


@dataclass(frozen=True)
class Pagina:
    """Uma página que pode ser indexada."""

    caminho: str
    titulo: str
    descricao: str
    prioridade: str = '0.5'
    frequencia: str = 'monthly'
    atualizado: date = ATUALIZADO
    #: Construtor do JSON-LD. Função, e não o dicionário pronto, para o
    #: custo de montar a vitrine de planos só existir em quem a pede.
    dados: object = None
    #: Nome do campo que vira o título quando a rota é dinâmica.
    dinamica: bool = False


def absoluta(caminho):
    """Absoluta a partir de `PUBLIC_BASE_URL`.

    Absoluta, e não relativa ao `Host:` da requisição, porque esse
    cabeçalho é do cliente. Um pedido com `Host: exemplo.ru` geraria uma
    canônica apontando para lá — e canônica é exatamente a instrução de
    "o original é aquele outro endereço".
    """
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    return base + caminho


# --------------------------------------------------------------------------
# Dados estruturados (schema.org)
# --------------------------------------------------------------------------
# Os `@id` são âncoras no próprio site: assim a Organização descrita na
# raiz e a citada como editora de um artigo de ajuda são o mesmo nó para
# o Google, em vez de duas organizações homônimas.

def _id(fragmento):
    return absoluta('/') + '#' + fragmento


def organizacao():
    return {
        '@type': 'Organization',
        '@id': _id('organizacao'),
        'name': 'NeuroDoc',
        'url': absoluta('/'),
        'email': settings.LEADS_EMAIL,
        'logo': {'@type': 'ImageObject', 'url': absoluta('/icon-512.png'),
                 'width': 512, 'height': 512},
        'description': RESUMO,
        'founder': {'@id': _id('fernando-freua')},
        # A empresa que mantém o produto, como qualificada no contrato.
        'legalName': CONTRATADO['nome'],
        'taxID': CONTRATADO['cnpj'],
        'areaServed': {'@type': 'Country', 'name': 'Brasil'},
    }


def autor():
    """O médico que escreveu o sistema.

    Entra porque prontuário é assunto de saúde, e o Google trata conteúdo
    de saúde pela origem: quem assina, com que formação. É a mesma razão
    pela qual a seção existe na página — só que legível por máquina.
    """
    from .content import AUTOR

    return {
        '@type': 'Person',
        '@id': _id('fernando-freua'),
        'name': AUTOR['nome'].replace('Dr. ', ''),
        'honorificPrefix': 'Dr.',
        'jobTitle': 'Médico neurologista',
        'description': AUTOR['resumo'],
        'alumniOf': {'@type': 'CollegeOrUniversity',
                     'name': 'Universidade de São Paulo'},
        'knowsAbout': ['Neurologia', 'Neurogenética', 'Doenças neurológicas raras',
                       'Prontuário eletrônico', 'Informática médica'],
        'url': absoluta('/') + '#autor',
    }


def produto():
    """O software, com os planos como ofertas.

    Preço lido de `tenancy.plans`: a marcação e o cartão na tela não
    podem divergir, e divergiriam no dia seguinte a um reajuste se o
    número fosse escrito aqui. O Personalizado fica de fora das ofertas —
    `price` sem valor não é oferta, é ruído.
    """
    from tenancy.plans import MESES_NO_ANO, PLANS, PUBLIC_ORDER

    from .content import RECURSOS

    ofertas = []
    for code in PUBLIC_ORDER:
        plano = PLANS[code]
        centavos = plano.get('price_monthly')
        if centavos is None:
            continue
        reais, resto = divmod(centavos * MESES_NO_ANO, 100)
        ofertas.append({
            '@type': 'Offer',
            'name': 'Plano ' + plano['label'],
            # Aritmetica inteira, como no resto do produto: o preco anual
            # e doze vezes o mensal em centavos, e `8700 * 12 / 100` em
            # ponto flutuante e por onde o centavo some.
            'price': '%d.%02d' % (reais, resto),
            'priceCurrency': 'BRL',
            'category': 'Assinatura anual',
            'url': absoluta('/') + '#planos',
            'availability': 'https://schema.org/InStock',
        })
    return {
        '@type': 'SoftwareApplication',
        '@id': _id('produto'),
        'name': 'NeuroDoc',
        'applicationCategory': 'HealthApplication',
        'applicationSubCategory': 'Prontuário eletrônico e gestão de consultório',
        'operatingSystem': 'Navegador web',
        'url': absoluta('/'),
        'inLanguage': 'pt-BR',
        'description': RESUMO,
        'publisher': {'@id': _id('organizacao')},
        'author': {'@id': _id('fernando-freua')},
        'featureList': [item['titulo'] for item in RECURSOS],
        'offers': ofertas,
        # Sem `aggregateRating`: não há avaliação medida, e nota inventada
        # é a infração que o Google pune com remoção do resultado rico.
    }


def _faq(perguntas):
    return {
        '@type': 'FAQPage',
        'mainEntity': [
            {'@type': 'Question', 'name': item['pergunta'],
             'acceptedAnswer': {'@type': 'Answer', 'text': item['resposta']}}
            for item in perguntas
        ],
    }


def _trilha(itens):
    """BreadcrumbList: a trilha que o Google mostra no lugar da URL."""
    return {
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': posicao, 'name': nome,
             'item': absoluta(caminho)}
            for posicao, (nome, caminho) in enumerate(itens, 1)
        ],
    }


def dados_da_raiz():
    from .content import FAQ

    return [
        {'@type': 'WebSite', '@id': _id('site'), 'name': 'NeuroDoc',
         'url': absoluta('/'), 'inLanguage': 'pt-BR',
         'publisher': {'@id': _id('organizacao')}},
        organizacao(), autor(), produto(), _faq(FAQ),
    ]


def dados_da_ajuda():
    return [
        _trilha([('Início', '/'), ('Ajuda', '/ajuda/')]),
        {'@type': 'CollectionPage', 'name': 'Manual de uso do NeuroDoc',
         'url': absoluta('/ajuda/'), 'inLanguage': 'pt-BR',
         'isPartOf': {'@id': _id('site')},
         'publisher': {'@id': _id('organizacao')}},
        organizacao(),
    ]


def dados_das_perguntas():
    from .help_content import FAQ_USO

    return [
        _trilha([('Início', '/'), ('Ajuda', '/ajuda/'),
                 ('Perguntas frequentes', '/ajuda/perguntas/')]),
        _faq(FAQ_USO), organizacao(),
    ]


def dados_do_artigo(artigo):
    caminho = '/ajuda/%s/' % artigo['slug']
    return [
        _trilha([('Início', '/'), ('Ajuda', '/ajuda/'),
                 (artigo['title'], caminho)]),
        {'@type': 'TechArticle',
         'headline': artigo['title'],
         'description': artigo['summary'],
         'url': absoluta(caminho),
         'inLanguage': 'pt-BR',
         'isPartOf': {'@id': _id('site')},
         'author': {'@id': _id('fernando-freua')},
         'publisher': {'@id': _id('organizacao')},
         'about': {'@id': _id('produto')}},
        organizacao(), autor(),
    ]


def dados_do_contrato():
    return [
        _trilha([('Início', '/'), ('Contrato de adesão', '/contrato/')]),
        organizacao(),
    ]


# --------------------------------------------------------------------------
# O catálogo de páginas públicas
# --------------------------------------------------------------------------
# A chave é `namespace:url_name` como `request.resolver_match` a monta —
# sem namespace, só o nome. Mudar uma rota de nome a tira daqui e a
# página cai para `noindex`: uma falha visível no roteiro, e não um
# sitemap apontando para 404.

PAGINAS = {
    'onboarding:landing': Pagina(
        caminho='/',
        titulo='Prontuário Eletrônico Inteligente para Neurologia | NeuroDoc',
        descricao=RESUMO,
        prioridade='1.0', frequencia='weekly',
        dados=dados_da_raiz,
    ),
    'onboarding:help': Pagina(
        caminho='/ajuda/',
        titulo='Manual de uso do NeuroDoc | Central de ajuda',
        descricao='O passo a passo das telas do NeuroDoc, com as imagens ao lado: '
                  'cadastrar paciente, marcar na agenda, escrever o prontuário e '
                  'emitir documento assinado.',
        prioridade='0.8', frequencia='monthly',
        dados=dados_da_ajuda,
    ),
    'onboarding:help-faq': Pagina(
        caminho='/ajuda/perguntas/',
        titulo='Perguntas frequentes sobre o NeuroDoc | Ajuda',
        descricao='As dúvidas de quem usa o sistema todo dia: prontuário finalizado, '
                  'assinatura digital, limite do plano, backup, exportação dos dados '
                  'e apoio por inteligência artificial.',
        prioridade='0.7', frequencia='monthly',
        dados=dados_das_perguntas,
    ),
    'onboarding:help-article': Pagina(
        caminho='/ajuda/', titulo='', descricao='',
        prioridade='0.6', frequencia='monthly',
        dinamica=True,
    ),
    'onboarding:contrato': Pagina(
        caminho='/contrato/',
        titulo='Contrato de adesão ao NeuroDoc',
        descricao='O contrato na íntegra, público e antes de qualquer cadastro: '
                  'prazos, proteção de dados pessoais, portabilidade do acervo e '
                  'o que acontece ao encerrar.',
        prioridade='0.4', frequencia='yearly',
        dados=dados_do_contrato,
    ),
    # A tela de verificação **sem token**: o formulário em branco que a
    # farmácia abre para digitar o código. Indexável e útil. A rota com
    # token (`verify-document-token`) fica fora desta lista de propósito —
    # ela mostra tipo de documento, médico e data, e isso não vai para
    # índice de busca nenhum.
    'verify-document': Pagina(
        caminho='/verificar/',
        titulo='Verificar a autenticidade de um documento médico | NeuroDoc',
        descricao='Confira se uma receita, um laudo ou um atestado emitido pelo '
                  'NeuroDoc é autêntico. Informe o código impresso no documento '
                  'ou leia o QR — sem precisar de conta.',
        prioridade='0.3', frequencia='yearly',
    ),
}


def pagina_do_artigo(slug):
    """A página de um artigo do manual, montada do próprio artigo.

    Vinte e quatro artigos com título e descrição copiados para cá seriam
    vinte e quatro chances de o manual mudar e a descrição ficar. O texto
    tem um dono só: `base/help_content.py`.
    """
    from .help_content import article_by_slug

    artigo = article_by_slug(slug)
    if artigo is None:
        return None
    return Pagina(
        caminho='/ajuda/%s/' % slug,
        titulo='%s | Ajuda do NeuroDoc' % artigo['title'],
        # O `summary` sozinho tem de quarenta a setenta caracteres: serve
        # ao cartão do índice, onde há o título logo acima, e é curto
        # demais para o resultado de busca, que mostra cento e cinquenta e
        # preenche o que falta com um trecho qualquer da página. O sufixo
        # é o mesmo para todos de propósito — descrever o formato do
        # manual é verdade sobre todos os artigos, e inventar uma frase
        # diferente por artigo seria texto sem dono para envelhecer.
        descricao='%s Passo a passo com as telas do sistema, no manual '
                  'público do NeuroDoc.' % artigo['summary'],
        prioridade='0.6', frequencia='monthly',
        dados=lambda: dados_do_artigo(artigo),
    )


def pagina_de(rota, kwargs):
    """A página do catálogo para esta rota, ou `None` se ela não é pública."""
    pagina = PAGINAS.get(rota)
    if pagina is None:
        return None
    if pagina.dinamica:
        return pagina_do_artigo(kwargs.get('slug', ''))
    return pagina


def paginas_do_sitemap():
    """Tudo que entra no `sitemap.xml`, na ordem em que será listado.

    Mesma fonte do `<meta name="robots">`: o que sai `noindex` não tem
    como aparecer aqui, porque nem está em `PAGINAS`.
    """
    from .help_content import ARTICLES

    paginas = []
    for rota, pagina in PAGINAS.items():
        if not pagina.dinamica:
            paginas.append(pagina)
    for artigo in ARTICLES:
        paginas.append(pagina_do_artigo(artigo['slug']))
    return paginas


# --------------------------------------------------------------------------
# O que o template recebe
# --------------------------------------------------------------------------

def _rota(request):
    match = getattr(request, 'resolver_match', None)
    if match is None:
        return '', {}
    nome = match.url_name or ''
    if match.namespace:
        nome = '%s:%s' % (match.namespace, nome)
    return nome, (match.kwargs or {})


def contexto(request):
    """Processador de contexto: `{{ nd_seo }}` em toda página.

    Roda em **toda** requisição, inclusive nas de dentro de `/app/`, onde
    só precisa dizer `noindex`. Por isso não toca no banco e não levanta:
    um erro aqui não seria uma meta tag faltando, seria a tela inteira em
    500.
    """
    rota, kwargs = _rota(request)
    try:
        pagina = pagina_de(rota, kwargs)
    except Exception:                                       # noqa: BLE001
        pagina = None

    dados = {
        'robots': OCULTO,
        'titulo': 'NeuroDoc',
        'descricao': '',
        'canonica': '',
        'imagem': absoluta('/og-image.png'),
        'tipo': 'website',
        'jsonld': '',
        'verificacao': getattr(settings, 'GOOGLE_SITE_VERIFICATION', ''),
    }
    if pagina is None:
        return {'nd_seo': dados}

    dados.update({
        'robots': INDEXAVEL,
        'titulo': pagina.titulo,
        'descricao': pagina.descricao,
        'canonica': absoluta(pagina.caminho),
        'tipo': 'article' if pagina.caminho.startswith('/ajuda/') and
                pagina.caminho != '/ajuda/' else 'website',
    })
    if pagina.dados is not None:
        try:
            grafo = pagina.dados()
        except Exception:                                   # noqa: BLE001
            grafo = None
        if grafo:
            dados['jsonld'] = _para_script(
                {'@context': 'https://schema.org', '@graph': grafo})
    return {'nd_seo': dados}


def _para_script(grafo):
    """JSON pronto para ir dentro de um `<script>`, sem escape de HTML.

    O template imprime isto com `|safe`, então o escape é problema deste
    lugar. `ensure_ascii=False` mantém o acento legível — e é justamente
    o que torna o escape obrigatório: a saída passa a conter caracteres
    crus, e um `</script>` dentro de qualquer texto do catálogo fecharia
    o bloco no meio e jogaria o resto do JSON na tela.

    Em JSON, `<`, `>` e `&` só aparecem **dentro** de string (nenhum é
    caractere estrutural), então trocá-los por escape unicode em todo o
    texto não quebra a sintaxe e dispensa um analisador.
    """
    texto = json.dumps(grafo, ensure_ascii=False, separators=(',', ':'))
    return texto.translate(ESCAPE_NO_SCRIPT)


#: A mesma tabela que o `|json_script` do Django usa para o mesmo problema.
ESCAPE_NO_SCRIPT = {ord('<'): '\\u003C', ord('>'): '\\u003E', ord('&'): '\\u0026'}
