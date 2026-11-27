"""Artigo da central de ajuda: instalar o sistema como aplicativo (PWA).

**O mesmo arquivo nos dois produtos** (NeuroDoc e ProntDoc): o texto recebe
o nome do produto, e `help_content.py` de cada lado o inclui. Mudou um passo
aqui, copie o arquivo inteiro para o outro repositório.

O nome dos menus dos navegadores muda de uma versão para outra, e o texto diz
isso onde muda, em vez de prometer um caminho que amanhã não existe. A página
do artigo ganha ainda o bloco `templates/help/_instalar_agora.html`, que
mostra o botão "Instalar agora" quando o navegador oferece a instalação e
reconhece o aparelho que já está com o app aberto. Decisões em
`docs/homologation/pwa.md`.
"""

SLUG = 'instalar-app'


def artigo(produto):
    """O artigo `instalar-app`, no formato de `help_content.ARTICLES`."""
    passos = [
        ('**O que é.** O {p} pode ficar na tela inicial do celular, do tablet ou do '
         'computador como um aplicativo: com o ícone dele, abrindo em tela cheia, sem a '
         'barra do navegador. É o mesmo sistema, com a mesma conta — **sem loja de '
         'aplicativos e sem custo**, e cada versão nova chega sozinha. Nenhum dado de '
         'paciente fica guardado no aparelho.'),
        ('**iPhone e iPad.** Abra o {p} no **Safari** e toque no botão **Compartilhar** '
         '(o quadrado com uma seta para cima; nas versões mais novas do iOS ele pode estar '
         'dentro do menu **⋯** da barra). Na lista, toque em **Adicionar à Tela de '
         'Início** e depois em **Adicionar**. No iOS 16.4 ou mais novo, o Chrome e o Edge '
         'do iPhone oferecem a mesma opção pelo botão Compartilhar.'),
        ('**Android.** No **Chrome**, toque no menu **⋮** (três pontos, no alto) e em '
         '**Instalar app** — em algumas versões aparece **Adicionar à tela inicial** e, '
         'depois, **Instalar**. Se surgir o aviso de instalar o {p} na parte de baixo da '
         'tela, basta tocar nele. No **Samsung Internet**: menu **☰** → **Adicionar página '
         'a** → **Tela inicial**.'),
        ('**Computador (Windows ou Mac).** No **Chrome** ou no **Edge**, aparece um ícone '
         'de instalar na ponta direita da barra de endereço. Também pelo menu: no Chrome, '
         '**⋮** → **Transmitir, salvar e compartilhar** → **Instalar página como app**; '
         'no Edge, **⋯** → **Aplicativos** → **Instalar este site como um aplicativo**. O '
         'nome do menu muda conforme a versão do navegador. No **Safari do Mac** (macOS '
         'Sonoma ou mais novo): **Arquivo** → **Adicionar ao Dock**. O Firefox não '
         'instala sites como aplicativo.'),
        ('**Atalhos.** No Android e no computador, segurar o ícone (ou clicar nele com o '
         'botão direito) mostra **Agenda** e **Pacientes**, que abrem direto nessas telas. '
         'O iPhone não mostra atalhos.'),
        ('**Avisos no celular.** Em **Notificações** (o sino → Central de notificações), '
         'toque em **Ativar neste aparelho** e permita as notificações. Chegam os avisos '
         'do sino, as mensagens da equipe e os pedidos e exames enviados pelo portal. A '
         'notificação diz **só o tipo** do aviso, nunca o nome do paciente; ao tocar, o '
         '{p} abre. No **iPhone e iPad**, só pelo app instalado e no iOS 16.4 ou mais '
         'novo. **Sair** desliga os avisos naquele aparelho.'),
        ('**Sem internet.** O {p} precisa de internet para abrir as telas: sem conexão, '
         'aparece uma tela própria com o botão **Tentar de novo**. O rascunho do '
         'atendimento que você estava escrevendo continua guardado no navegador e volta '
         'quando a tela abrir.'),
        ('**Segurança.** O aplicativo usa a mesma conta, a mesma senha e o mesmo segundo '
         'fator, e a sessão termina no mesmo prazo do navegador. Em aparelho emprestado '
         'ou compartilhado, use **Sair** ao terminar. Para tirar o aplicativo, remova o '
         'ícone como qualquer outro — no computador, pelo menu da janela do próprio app.'),
    ]
    return {
        'slug': SLUG,
        'title': 'Instalar o app no celular, tablet ou computador',
        # Curto: `base/seo.py` acrescenta uma frase fixa, e a descrição na
        # busca tem de caber em 175 caracteres.
        'summary': f'O {produto} como aplicativo no celular, no tablet ou no computador, '
                   'sem loja e sem custo.',
        'audience': 'Toda a equipe',
        'steps': [(texto.replace('{p}', produto), '', '') for texto in passos],
    }
