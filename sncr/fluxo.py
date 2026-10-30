"""O pedido de bloco, do clique do médico à resposta da Anvisa.

1. `iniciar` confere tudo o que dá para conferir **antes** de gastar o
   login (integração ligada, CNPJ, CRM validado, limite do mês, nenhum
   pedido incerto pendente), cria o pedido e devolve o endereço do login
   Gov.br no SNCR;
2. o SNCR volta a `/app/sncr/retorno/?session_id=`; `concluir` troca o
   `session_id` pelo token e pede o bloco **na mesma requisição**
   (decisão I5: o token vive 30 s).

**O retorno só vale para o navegador que começou.** O pedido pendente fica
na sessão do Django; um `session_id` que chega sem pedido pendente nesta
sessão é recusado sem falar com a Anvisa. É o que impede alguém de mandar
ao médico um link de retorno com o login de outra pessoa.

**Nada é repetido.** O pedido passa a `ENVIANDO` numa transação própria
**antes** da chamada; recarregar a página de retorno, ou dois retornos ao
mesmo tempo, encontram o pedido já em andamento e não pedem de novo.
"""

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from audit.services import record_audit_event
from base.validators import is_valid_cnpj

from . import cliente as api
from .models import Configuracao, EstadoPedido, PedidoNumeracao
from .numeracao import registrar_bloco, saldo

logger = logging.getLogger('neurodoc.sncr')

#: A Anvisa: até 3 blocos por mês, por tipo e inscrição (FAQ Integração P33).
PEDIDOS_POR_MES = 3
#: O `state` do SNCR expira em 5 minutos (Manual v5, notas de segurança).
PRAZO_DO_LOGIN = timedelta(minutes=5)
#: Pedido que ficou em `ENVIANDO` além disto é tratado como incerto: o
#: processo morreu no meio da chamada, e não se sabe se ela saiu.
PRAZO_DO_ENVIO = timedelta(minutes=2)
CHAVE_DA_SESSAO = 'sncr_pedido_pendente'


class PedidoRecusado(Exception):
    """O NeuroDoc não deixa nem começar. `str(exc)` vai ao médico."""


def criar_cliente(config):
    """Ponto único de construção — o roteiro troca o transporte aqui."""
    return api.Cliente(config.base_url, _origem())


def _origem():
    partes = urlsplit(settings.PUBLIC_BASE_URL)
    return f'{partes.scheme}://{partes.netloc}'


def url_de_retorno():
    return settings.PUBLIC_BASE_URL.rstrip('/') + reverse('sncr:retorno')


def _so_digitos(valor):
    return re.sub(r'\D', '', valor or '')


def _inicio_do_mes():
    hoje = timezone.localdate()
    return timezone.make_aware(datetime(hoje.year, hoje.month, 1))


def conferir(config, medico, tipo):
    """Os motivos que impedem pedir agora, em português. Lista vazia = pode."""
    motivos = []
    if not config.ativo:
        motivos.append('A integração com o SNCR está desligada nesta instalação.')
    if not is_valid_cnpj(config.cnpj_mantenedora or ''):
        motivos.append('Falta o CNPJ da mantenedora do NeuroDoc na configuração do SNCR.')
    if medico is None:
        motivos.append('Só um médico com registro profissional pode pedir numeração.')
        return motivos
    if medico.verification_status != medico.VerificationStatus.VERIFIED:
        motivos.append('O registro profissional (CRM) ainda não foi validado no NeuroDoc.')
    if not (_so_digitos(medico.crm_number) and medico.crm_state):
        motivos.append('O CRM e a UF do registro profissional estão incompletos.')
    pedidos = PedidoNumeracao.objects.filter(medico=medico, tipo=tipo, ambiente=config.ambiente)
    if pedidos.filter(estado=EstadoPedido.INCERTO).exists() or pedidos.filter(
        estado=EstadoPedido.ENVIANDO,
    ).exists():
        motivos.append(
            'Há um pedido anterior com resultado incerto. Ele precisa ser conferido no portal do '
            'SNCR antes de um pedido novo — repetir pode gastar mais um dos três pedidos do mês.'
        )
    no_mes = pedidos.filter(
        estado__in=[EstadoPedido.CONCLUIDO, EstadoPedido.INCERTO], enviado_em__gte=_inicio_do_mes(),
    ).count()
    if no_mes >= PEDIDOS_POR_MES:
        motivos.append(f'O limite da Anvisa é de {PEDIDOS_POR_MES} blocos de {tipo} por mês, e ele já foi usado.')
    if saldo(medico, tipo, config.ambiente) > 0:
        motivos.append('Ainda há números livres do bloco atual. Um bloco novo só quando este acabar.')
    return motivos


def iniciar(request, medico, tipo, tenant_id):
    """Cria o pedido e devolve o endereço do login no SNCR."""
    config = Configuracao.carregar()
    motivos = conferir(config, medico, tipo)
    if motivos:
        raise PedidoRecusado(' '.join(motivos))
    pedido = PedidoNumeracao.objects.create(
        medico=medico, solicitado_por=request.user, tenant_id=tenant_id, tipo=tipo,
        ambiente=config.ambiente, uf=medico.crm_state.upper(), documento=_so_digitos(medico.crm_number),
        cnpj=config.cnpj_mantenedora,
    )
    request.session[CHAVE_DA_SESSAO] = {'id': str(pedido.id), 'em': timezone.now().isoformat()}
    record_audit_event(
        request.user.id, tenant_id, 'sncr.pedido_iniciado', object_type='sncr_pedido',
        object_id=pedido.id, outcome='success',
        integrity_metadata={'tipo': tipo, 'ambiente': config.ambiente},
    )
    cli = criar_cliente(config)
    try:
        return pedido, cli.url_login(url_de_retorno())
    finally:
        cli.fechar()


def _encerrar(pedido, estado, mensagem, status=None, actor_id=None):
    pedido.estado = estado
    pedido.mensagem = mensagem[:500]
    pedido.http_status = status
    pedido.concluido_em = timezone.now()
    pedido.save(update_fields=['estado', 'mensagem', 'http_status', 'concluido_em', 'updated_at'])
    record_audit_event(
        actor_id or pedido.solicitado_por_id, pedido.tenant_id, f'sncr.pedido_{estado}',
        object_type='sncr_pedido', object_id=pedido.id,
        outcome='success' if estado == EstadoPedido.CONCLUIDO else ('error' if estado in (
            EstadoPedido.INCERTO, EstadoPedido.FALHOU) else 'denied'),
        integrity_metadata={'tipo': pedido.tipo, 'ambiente': pedido.ambiente, 'http_status': status},
    )
    return pedido


def concluir(request, session_id):
    """Troca a sessão pelo token e pede o bloco. Devolve o pedido encerrado."""
    pendente = request.session.pop(CHAVE_DA_SESSAO, None)
    if not pendente or not session_id:
        raise PedidoRecusado('Este retorno do Gov.br não corresponde a um pedido feito neste navegador.')
    with transaction.atomic():
        pedido = PedidoNumeracao.objects.select_for_update().filter(
            id=pendente.get('id'), solicitado_por=request.user,
        ).first()
        if pedido is None or pedido.estado != EstadoPedido.AGUARDANDO_LOGIN:
            raise PedidoRecusado('Este pedido já foi processado. Confira o resultado no painel do SNCR.')
        if timezone.now() - pedido.created_at > PRAZO_DO_LOGIN:
            _encerrar(pedido, EstadoPedido.EXPIRADO, 'O login no Gov.br demorou mais de 5 minutos. Peça de novo.')
            return pedido
        pedido.estado = EstadoPedido.ENVIANDO
        pedido.enviado_em = timezone.now()
        pedido.save(update_fields=['estado', 'enviado_em', 'updated_at'])

    config = Configuracao.carregar()
    cli = criar_cliente(config)
    try:
        token = cli.trocar_sessao(session_id)
        resposta = cli.pedir_bloco(token, pedido.tipo, pedido.conselho, pedido.uf, pedido.documento, pedido.cnpj)
    except api.Incerto as exc:
        logger.warning('sncr: pedido %s incerto (%s)', pedido.id, exc.status)
        return _encerrar(pedido, EstadoPedido.INCERTO, str(exc), exc.status)
    except api.Recusado as exc:
        return _encerrar(pedido, EstadoPedido.RECUSADO, str(exc), exc.status)
    except (api.Indisponivel, api.SessaoInvalida) as exc:
        return _encerrar(pedido, EstadoPedido.FALHOU, str(exc), exc.status)
    except Exception:
        # Erro nosso, depois de a chamada talvez ter saído: o seguro é
        # incerto, não falha — falha permitiria pedir de novo.
        logger.exception('sncr: erro inesperado no pedido %s', pedido.id)
        return _encerrar(
            pedido, EstadoPedido.INCERTO,
            'Erro inesperado durante o pedido. O bloco pode ter sido entregue: confira no portal do SNCR.',
        )
    finally:
        cli.fechar()

    try:
        bloco = registrar_bloco(pedido, resposta)
    except Exception:
        logger.exception('sncr: bloco recebido e não gravado, pedido %s', pedido.id)
        return _encerrar(
            pedido, EstadoPedido.INCERTO,
            f'O SNCR entregou o bloco {resposta["inicio"]} a {resposta["fim"]}, mas o NeuroDoc não '
            'conseguiu gravá-lo. Avise o suporte com estes números.',
        )
    texto = f'Bloco {bloco.inicio} a {bloco.fim} recebido.'
    if not bloco.utilizavel:
        texto += ' ' + bloco.motivo_bloqueio
    return _encerrar(pedido, EstadoPedido.CONCLUIDO, texto)


def pedidos_parados():
    """`ENVIANDO` além do prazo vira incerto: o processo morreu no meio.

    E o pedido que ficou **aguardando o login** além do prazo do Gov.br vira
    expirado: o médico fechou a aba, ou o login não voltou. Ele nunca falou
    com a Anvisa e não barrava nada, mas seguia no painel como "aguardando"
    — o primeiro pedido real, em 2026-10-29, deixou quatro assim antes do
    que deu certo, e o painel parecia ter quatro pedidos pendentes.
    """
    limite = timezone.now() - PRAZO_DO_ENVIO
    for pedido in PedidoNumeracao.objects.filter(estado=EstadoPedido.ENVIANDO, enviado_em__lt=limite):
        _encerrar(
            pedido, EstadoPedido.INCERTO,
            'O pedido foi interrompido no meio. O bloco pode ter sido entregue: confira no portal do SNCR.',
        )
    vencido = timezone.now() - PRAZO_DO_LOGIN
    for pedido in PedidoNumeracao.objects.filter(estado=EstadoPedido.AGUARDANDO_LOGIN, created_at__lt=vencido):
        _encerrar(pedido, EstadoPedido.EXPIRADO,
                  'O login no Gov.br não foi concluído. Nada foi pedido à Anvisa.')


#: O bloco de RCE e de RET tem 1.000 números (Manual v5). A faixa
#: conferida no portal e digitada à mão tem de ter exatamente isso: um
#: dígito errado no início ou no fim viraria um bloco de outro tamanho.
NUMEROS_POR_BLOCO = 1000


def resolver_incerto(pedido_id, medico, ator_id, *, gerado, inicio='', fim=''):
    """O médico conferiu no portal do SNCR o que aconteceu com o pedido incerto.

    É a reconciliação que a API não tem (decisão I14): ela não consulta nem
    cancela bloco, então quem sabe é o portal da Anvisa, onde o próprio
    médico vê a numeração que recebeu. Duas respostas:

    - **nenhum bloco foi gerado** — o pedido vira `FALHOU` (não conta no
      limite do mês, porque não gerou nada) e o médico pode pedir de novo;
    - **o bloco foi gerado** — o médico digita início e fim como o portal
      mostra; a faixa tem de ter os 1.000 números do bloco e não pode repetir
      número já registrado. O pedido vira `CONCLUIDO` com o bloco.

    Só o próprio médico, e só pedido seu ainda incerto.
    """
    from .numeracao import enumerar

    with transaction.atomic():
        pedido = (PedidoNumeracao.objects.select_for_update()
                  .filter(pk=pedido_id, medico=medico, estado=EstadoPedido.INCERTO).first())
        if pedido is None:
            raise PedidoRecusado('Este pedido não está mais pendente de conferência.')
        if not gerado:
            _encerrar(pedido, EstadoPedido.FALHOU,
                      'Conferido pelo médico no portal do SNCR: nenhum bloco foi gerado por este pedido.',
                      pedido.http_status, actor_id=ator_id)
            return pedido
        inicio, fim = (inicio or '').strip(), (fim or '').strip()
        numeros = enumerar(inicio, fim)
        if numeros is None or len(numeros) != NUMEROS_POR_BLOCO:
            raise PedidoRecusado(
                f'Início e fim não formam uma faixa de {NUMEROS_POR_BLOCO} números. Copie os dois '
                'exatamente como o portal do SNCR mostra, com os zeros à esquerda.'
            )
        bloco = registrar_bloco(pedido, {'inicio': inicio, 'fim': fim, 'quantidade': NUMEROS_POR_BLOCO})
        if not bloco.utilizavel:
            # A faixa repete número já registrado: o bloco fica gravado como
            # não utilizável, e o pedido, conferido — sem número adivinhado.
            mensagem = f'Conferido no portal do SNCR, mas não utilizável: {bloco.motivo_bloqueio}'
        else:
            mensagem = f'Conferido pelo médico no portal do SNCR: bloco {inicio} a {fim}.'
        _encerrar(pedido, EstadoPedido.CONCLUIDO, mensagem, pedido.http_status, actor_id=ator_id)
        return pedido
