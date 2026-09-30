"""Onde o navegador deposita o que a política teria bloqueado.

O modo de relatório só vale se alguém ler os relatórios. Esta view é o
ouvido: recebe o que o navegador manda, registra o essencial no log da
aplicação, e não guarda nada no banco.

**Por que log e não tabela.** Relatório de CSP é ruído de alta frequência
e baixa densidade: extensão de navegador injeta script em toda página e
gera um relatório por carregamento, para sempre. Uma tabela encheria sem
ninguém olhar, e a decisão que interessa — "esta diretiva bloqueia tela
nossa?" — se toma lendo uma semana de log, não consultando cinco anos de
linhas.

**Por que sem autenticação.** O navegador manda o relatório sozinho, sem
sessão e sem CSRF. Exigir qualquer das duas faria o endereço recusar
exatamente o que ele existe para receber — e o resultado seria a política
parecendo limpa por nunca receber notícia.

Ser aberto é o que obriga o resto: teto por IP, corpo pequeno, e só os
campos que interessam indo para o log. Sem isso, seria um canal de
inserção de texto arbitrário no log da instalação, que é um jeito
conhecido de sujar investigação.
"""
import json
import logging

from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from base.net import client_ip

logger = logging.getLogger('neurodoc.csp')

#: Teto de relatórios por IP na janela. Uma página com extensão barulhenta
#: gera dezenas por minuto; acima disto não há informação nova, só volume.
LIMITE_POR_IP = 30
JANELA_SEGUNDOS = 60

#: Corpo maior que isto não é relatório, é tentativa de entupir o log.
#: Relatório real fica bem abaixo de 4 KB.
MAX_CORPO = 8 * 1024

#: O que vai para o log. Só isto: a diretiva violada e o recurso bloqueado
#: respondem à pergunta inteira, e `script-sample` — que alguns navegadores
#: mandam — traria trecho de página para dentro do log.
CAMPOS = ('violated-directive', 'effective-directive', 'blocked-uri', 'document-uri')

#: Quanto de cada campo é registrado. URI de documento pode carregar
#: identificador na rota; cortar cedo mantém o log legível e curto.
MAX_CAMPO = 200


@method_decorator(csrf_exempt, name='dispatch')
class CspReportView(View):
    """Recebe `application/csp-report`. Responde 204 sempre que aceita."""

    def post(self, request):
        if self._excedeu_o_limite(request):
            # 429 sem corpo: o navegador não lê a resposta, e o texto só
            # serviria para quem estivesse sondando o endereço.
            return HttpResponse(status=429)

        corpo = request.body[:MAX_CORPO]
        try:
            dados = json.loads(corpo.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return HttpResponseForbidden()

        relatorio = dados.get('csp-report') if isinstance(dados, dict) else None
        if not isinstance(relatorio, dict):
            return HttpResponseForbidden()

        resumo = {
            campo: str(relatorio.get(campo, ''))[:MAX_CAMPO]
            for campo in CAMPOS
            if relatorio.get(campo)
        }
        if resumo:
            logger.warning('csp: %s', json.dumps(resumo, ensure_ascii=False, sort_keys=True))
        return HttpResponse(status=204)

    def _excedeu_o_limite(self, request):
        """Conta por IP. Falha **aberta**, ao contrário do convite.

        Aqui o pior caso de não conseguir contar é log a mais; o pior caso
        de fechar é perder o relatório que denunciaria a tela quebrada —
        que é a única razão de tudo isto existir. Com o Redis fora, este
        caminho continua ouvindo.
        """
        chave = f'csp-report:{client_ip(request)}'
        try:
            cache.get_or_set(chave, 0, JANELA_SEGUNDOS)
            return cache.incr(chave) > LIMITE_POR_IP
        except Exception:                                   # noqa: BLE001
            return False
