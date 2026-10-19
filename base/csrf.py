"""A tela de quando o token CSRF nao confere.

O padrao do Django e um 403 sem estilo, sem explicacao e sem saida --
"CSRF verification failed. Request aborted." Ele nao aparece so em
tentativa de ataque: aparece no caso mais banal que existe, que e sair do
sistema e tentar entrar de novo na aba que ja estava aberta.

**Por que acontece.** `auth_login` chama `rotate_token`, que troca o
cookie CSRF. O formulario de login que ficou na aba -- ou que o navegador
restaura quando se volta uma pagina -- carrega o token de antes. O
servidor compara com o cookie novo, nao bate, e recusa. Abrir outra aba
"resolve" porque busca a pagina de novo e recebe token fresco, e e por
isso que o defeito chega relatado como "em aba nova funciona": a frase
nao parece ter nada a ver com token, e manda quem investiga procurar
sessao, replica ou cache.

**O que esta tela NAO faz:** reenviar o formulario sozinha. Reenviar um
POST que o servidor acabou de recusar por seguranca e precisamente o que
o CSRF existe para impedir, e um "tentar de novo" automatico aqui
transformaria a protecao em enfeite. Ela oferece o caminho de volta; quem
clica chega a um formulario com token novo e reenvia por conta propria.
"""

from django.shortcuts import render


def csrf_failure(request, reason='', template_name='base/csrf_failure.html'):
    """Assinatura fixada pelo Django (`CSRF_FAILURE_VIEW`).

    `reason` fica de fora do que se mostra de proposito: e texto interno,
    em ingles, que descreve o mecanismo ("CSRF token from POST incorrect")
    e nao ajuda quem esta do outro lado. Ele ja vai para o log do
    servidor, que e onde alguem investigando vai procurar.
    """
    # O portal do paciente e as paginas publicas nao tem "tela de entrada":
    # quem esta ali nao tem conta. Mandar o paciente para o login do
    # sistema, como a tela fazia, era um beco sem saida -- o caminho de
    # volta dele e a propria pagina, com token novo (2026-10-18).
    publico = request.path.startswith(('/solicitacoes/', '/d/', '/verificar/'))
    return render(
        request, template_name,
        {
            'caminho_de_volta': request.path,
            'autenticado': request.user.is_authenticated,
            'publico': publico,
            # O arquivo escolhido nao volta: o navegador nao deixa
            # repreencher campo de arquivo, e a tela precisa dizer isso.
            'tinha_arquivo': bool(request.FILES) if publico else False,
        },
        status=403,
    )
