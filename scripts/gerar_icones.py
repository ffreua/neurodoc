"""Gera a familia de icones da marca a partir de uma geometria so.

Roda **a mao**, e o que ele escreve vai versionado em `static/brand/`.
Nao e tarefa de deploy nem de requisicao: o desenho muda uma vez por ano,
e gerar PNG em tempo de resposta so acrescentaria uma dependencia de
imagem ao caminho que serve prontuario.

    python scripts/gerar_icones.py

**Duas variantes da mesma marca, e a razao e tamanho.** A completa tem o
monograma sobre um tracado de pulso -- o sinal "neuro" que faz a marca
nao ser mais uma letra num quadrado. Em 16 px, porem, o pulso tem meio
pixel de espessura: some no antialiasing e deixa uma sujeira cinza
embaixo do N. Entao favicon pequeno (ICO, SVG de aba) leva so o
monograma, maior para ocupar o quadrado; e apple-touch, PWA e Open Graph
levam a marca completa, onde o pulso tem onde aparecer.

Tudo e desenhado em 4x e reduzido com LANCZOS. `ImageDraw` nao faz
antialiasing, e um N de 32 px desenhado direto sai serrilhado.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / 'static' / 'brand'

#: O primario do tema Duralux (`--bs-primary`). O degrade escurece para
#: baixo porque o icone e visto sobre fundo claro na maioria das abas, e
#: um bloco chapado some contra a barra do navegador no Windows.
AZUL_CLARO = (52, 84, 209)
AZUL_ESCURO = (33, 54, 148)
BRANCO = (255, 255, 255)

#: Geometria num quadrado de 512, para o resto ser uma multiplicacao.
LADO = 512
RAIO = 112

#: O N em um traco so: sobe a esquerda, desce a diagonal, sobe a direita.
N_COMPLETO = [(164, 292), (164, 108), (348, 292), (348, 108)]
N_GROSSURA = 46
#: Na variante pequena o N ocupa o quadrado inteiro -- sem o pulso
#: embaixo, sobrar margem so faz a letra encolher na aba.
N_SOZINHO = [(150, 392), (150, 120), (362, 392), (362, 120)]
N_SOZINHO_GROSSURA = 56

#: O pulso. Linha de base, subida, descida funda, retorno, linha de base.
PULSO = [(140, 380), (194, 380), (224, 338), (256, 428), (286, 380), (372, 380)]
PULSO_GROSSURA = 26

ESCALA = 4


def _fundo(lado, raio):
    """Quadrado arredondado com degrade vertical, em RGBA."""
    degrade = Image.new('RGB', (1, lado))
    for y in range(lado):
        t = y / max(lado - 1, 1)
        degrade.putpixel((0, y), tuple(
            round(claro + (escuro - claro) * t)
            for claro, escuro in zip(AZUL_CLARO, AZUL_ESCURO)
        ))
    degrade = degrade.resize((lado, lado))
    mascara = Image.new('L', (lado, lado), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, lado - 1, lado - 1], raio, fill=255)
    imagem = Image.new('RGBA', (lado, lado), (0, 0, 0, 0))
    imagem.paste(degrade, (0, 0), mascara)
    return imagem


def _tracar(desenho, pontos, grossura, k, cor=BRANCO):
    """Polilinha com junta e ponta redondas.

    `ImageDraw.line` com `joint='curve'` arredonda as juntas mas deixa as
    **pontas** em corte reto; os dois circulos nas extremidades sao o que
    fecha o traco.
    """
    escalados = [(x * k, y * k) for x, y in pontos]
    largura = round(grossura * k)
    desenho.line(escalados, fill=cor, width=largura, joint='curve')
    raio = largura / 2
    for x, y in (escalados[0], escalados[-1]):
        desenho.ellipse([x - raio, y - raio, x + raio, y + raio], fill=cor)


def marca(lado, completa=True):
    """A marca, no tamanho pedido."""
    k = ESCALA * lado / LADO
    grande = _fundo(round(LADO * k), round(RAIO * k))
    desenho = ImageDraw.Draw(grande)
    if completa:
        _tracar(desenho, N_COMPLETO, N_GROSSURA, k)
        _tracar(desenho, PULSO, PULSO_GROSSURA, k)
    else:
        _tracar(desenho, N_SOZINHO, N_SOZINHO_GROSSURA, k)
    return grande.resize((lado, lado), Image.LANCZOS)


def _traco_sozinho(lado):
    """So o desenho branco, sem o quadrado azul atras."""
    k = ESCALA * lado / LADO
    tela = Image.new('RGBA', (round(LADO * k), round(LADO * k)), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(tela)
    _tracar(desenho, N_COMPLETO, N_GROSSURA, k)
    _tracar(desenho, PULSO, PULSO_GROSSURA, k)
    return tela.resize((lado, lado), Image.LANCZOS)


def maskable(lado):
    """A variante do Android, que recorta o icone em qualquer forma.

    A especificacao reserva 20% de cada borda como zona de corte seguro:
    a marca encolhe para 60% do quadrado e o resto vira fundo chapado.
    Sem isso, um launcher que recorta em circulo come o canto do N.

    O quadrado arredondado nao entra aqui de proposito: quem arredonda e
    o launcher, e dois cantos arredondados um sobre o outro aparecem.
    """
    fundo = Image.new('RGBA', (lado, lado), AZUL_ESCURO + (255,))
    interno = round(lado * 0.6)
    traco = _traco_sozinho(interno)
    fundo.paste(traco, ((lado - interno) // 2, (lado - interno) // 2), traco)
    return fundo


def _fonte(nomes, tamanho):
    for nome in nomes:
        for pasta in ('C:/Windows/Fonts/', '/usr/share/fonts/truetype/dejavu/', ''):
            try:
                return ImageFont.truetype(pasta + nome, tamanho)
            except OSError:
                continue
    return ImageFont.load_default(tamanho)


def open_graph():
    """A imagem do compartilhamento: 1200x630, o que o WhatsApp mostra.

    Texto grande e poucas palavras: o cartao aparece com 300 px de
    largura numa conversa, e qualquer linha de corpo vira borrao.
    """
    largura, altura = 1200, 630
    degrade = Image.new('RGB', (1, altura))
    for y in range(altura):
        t = y / (altura - 1)
        degrade.putpixel((0, y), tuple(
            round(c + (e - c) * t) for c, e in zip(AZUL_CLARO, AZUL_ESCURO)
        ))
    imagem = degrade.resize((largura, altura))

    # Sobre o degrade azul a marca repetiria o proprio fundo; aqui vai so
    # o traco branco.
    traco = _traco_sozinho(236)
    imagem.paste(traco, (92, 198), traco)

    desenho = ImageDraw.Draw(imagem)
    titulo = _fonte(['segoeuib.ttf', 'arialbd.ttf', 'DejaVuSans-Bold.ttf'], 86)
    corpo = _fonte(['segoeui.ttf', 'arial.ttf', 'DejaVuSans.ttf'], 35)
    miudo = _fonte(['segoeuisl.ttf', 'arial.ttf', 'DejaVuSans.ttf'], 25)
    desenho.text((348, 168), 'NeuroDoc', font=titulo, fill=BRANCO)
    desenho.text((352, 288), 'Prontuário eletrônico inteligente',
                 font=corpo, fill=(214, 224, 255))
    desenho.text((352, 336), 'para neurologia — e para qualquer especialidade',
                 font=corpo, fill=(214, 224, 255))
    desenho.line([(352, 406), (1104, 406)], fill=(140, 164, 240), width=2)
    desenho.text((352, 432),
                 'Exame estruturado · Receita assinada · Agenda · IA revisada pelo médico',
                 font=miudo, fill=(188, 202, 248))
    return imagem


def svg(completa):
    """A mesma geometria em SVG, para o `rel=icon` que o Chrome prefere."""
    pontos = N_COMPLETO if completa else N_SOZINHO
    grossura = N_GROSSURA if completa else N_SOZINHO_GROSSURA
    caminho = 'M ' + ' L '.join(f'{x} {y}' for x, y in pontos)
    pulso = ''
    if completa:
        traco = 'M ' + ' L '.join(f'{x} {y}' for x, y in PULSO)
        pulso = ('\n  <path d="%s" fill="none" stroke="#fff" stroke-width="%d" '
                 'stroke-linecap="round" stroke-linejoin="round"/>'
                 % (traco, PULSO_GROSSURA))
    claro = '#%02x%02x%02x' % AZUL_CLARO
    escuro = '#%02x%02x%02x' % AZUL_ESCURO
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'role="img" aria-label="NeuroDoc">\n'
        '  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="%s"/>'
        '<stop offset="1" stop-color="%s"/></linearGradient></defs>\n'
        '  <rect width="%d" height="%d" rx="%d" fill="url(#g)"/>\n'
        '  <path d="%s" fill="none" stroke="#fff" stroke-width="%d" '
        'stroke-linecap="round" stroke-linejoin="round"/>%s\n'
        '</svg>\n'
        % (LADO, LADO, claro, escuro, LADO, LADO, RAIO, caminho, grossura, pulso)
    )


def main():
    DESTINO.mkdir(parents=True, exist_ok=True)
    escritos = []

    def salvar(nome, imagem, **kwargs):
        caminho = DESTINO / nome
        imagem.save(caminho, **kwargs)
        escritos.append((nome, caminho.stat().st_size))

    # ICO com tres tamanhos dentro: 16 e 32 sao o que a aba usa, 48 e o
    # que o Windows poe no atalho da area de trabalho.
    salvar('favicon.ico', marca(256, completa=False),
           format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
    salvar('favicon-32.png', marca(32, completa=False), format='PNG')
    salvar('apple-touch-icon.png', marca(180), format='PNG')
    salvar('icon-192.png', marca(192), format='PNG')
    salvar('icon-512.png', marca(512), format='PNG')
    salvar('icon-maskable-512.png', maskable(512), format='PNG')
    salvar('og-image.png', open_graph(), format='PNG')

    for nome, conteudo in [('neurodoc-mark.svg', svg(completa=False)),
                           ('neurodoc-mark-full.svg', svg(completa=True))]:
        (DESTINO / nome).write_text(conteudo, encoding='utf-8')
        escritos.append((nome, (DESTINO / nome).stat().st_size))

    for nome, tamanho in escritos:
        print('  %-28s %8d bytes' % (nome, tamanho))
    print('\n%d arquivos em %s' % (len(escritos), DESTINO))


if __name__ == '__main__':
    sys.exit(main())
