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

**A Notificação de Receita (A, B, B2) segue o mesmo caminho**, com regras
dela (decisões D9 e I17 a I19): não leva CNPJ, o médico escolhe o lote (10
por padrão, até 50), a Anvisa limita 50 números por dia por tipo, e o
pedido incerto é **dado por perdido** pelo médico em vez de conferido no
portal — o prescritor não enxerga a numeração dele no SNCR.
"""

import logging
import re
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from audit.services import record_audit_event
from base.validators import is_valid_cnpj

from . import cliente as api
from .models import BlocoNumeracao, Configuracao, EstadoPedido, PedidoNumeracao, eh_notificacao
from .numeracao import registrar_bloco, registrar_lote, saldo
from .receita import LIMITE_MEDICAMENTOS

logger = logging.getLogger('neurodoc.sncr')

#: A Anvisa: até 3 blocos por mês, por tipo e inscrição (FAQ Integração P33).
PEDIDOS_POR_MES = 3
#: O `state` do SNCR expira em 5 minutos (Manual v5, notas de segurança).
PRAZO_DO_LOGIN = timedelta(minutes=5)
#: Pedido que ficou em `ENVIANDO` além disto é tratado como incerto: o
#: processo morreu no meio da chamada, e não se sabe se ela saiu.
PRAZO_DO_ENVIO = timedelta(minutes=2)
CHAVE_DA_SESSAO = 'sncr_pedido_pendente'

#: Notificação de Receita (Manual v5, §2.3.1.3 e §2.3.1.5): de 10 a 50
#: números por pedido, e até 50 por dia por tipo e prescritor, somando todas
#: as plataformas que ele usa. O lote padrão é o mínimo (decisão I17): a
#: Anvisa pede lotes fracionados, para a cota do dia não se esgotar numa
#: plataforma só (FAQ Integração P30), e cada número vem da cota que a
#: Vigilância Sanitária liberou — o que se retira e não se usa, se perde.
LOTE_PADRAO = 10
LOTE_MINIMO = 10
LOTE_MAXIMO = 50
LIMITE_DIARIO = 50
QUANTIDADES_DO_LOTE = (10, 20, 30, 40, 50)


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


def _inicio_do_dia():
    return timezone.make_aware(datetime.combine(timezone.localdate(), time.min))


def recebidos_hoje(medico, tipo, ambiente):
    """Números de Notificação que este médico recebeu hoje pelo NeuroDoc.

    Só os daqui: o limite diário da Anvisa soma todas as plataformas, e o
    que foi pedido noutra o SNCR recusa com a mensagem dele.
    """
    lotes = BlocoNumeracao.objects.filter(
        medico=medico, tipo=tipo, ambiente=ambiente, created_at__gte=_inicio_do_dia(),
    ).values_list('quantidade', flat=True)
    return sum(q or 0 for q in lotes)


def conferir(config, medico, tipo):
    """Os motivos que impedem pedir agora, em português. Lista vazia = pode."""
    motivos = []
    notificacao = eh_notificacao(tipo)
    if not config.ativo:
        motivos.append('A integração com o SNCR está desligada nesta instalação.')
    if not notificacao and not is_valid_cnpj(config.cnpj_mantenedora or ''):
        motivos.append('Falta o CNPJ da mantenedora do NeuroDoc na configuração do SNCR.')
    if medico is None:
        motivos.append('Só um médico com registro profissional pode pedir numeração.')
        return motivos
    if medico.verification_status != medico.VerificationStatus.VERIFIED:
        motivos.append('O registro profissional (CRM) ainda não foi validado no NeuroDoc.')
    if not (_so_digitos(medico.crm_number) and medico.crm_state):
        motivos.append('O CRM e a UF do registro profissional estão incompletos.')
    pedidos = PedidoNumeracao.objects.filter(medico=medico, tipo=tipo, ambiente=config.ambiente)
    if notificacao:
        return motivos + _conferir_notificacao(config, medico, tipo, pedidos)
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


def _conferir_notificacao(config, medico, tipo, pedidos):
    """O que impede retirar outro lote de Notificação de Receita agora.

    **Livres demais** impede (decisão I19): a Anvisa pede que a plataforma
    retire números "apenas à medida que o saldo em uso for consumido" (FAQ
    Integração P30), e o número retirado sai da cota da Vigilância. Mas o
    corte não é "zero", como no bloco da RCE: uma receita de três
    medicamentos gasta três números de uma vez, e com um ou dois livres o
    médico não teria como assinar nem como pedir. O corte é
    `LIMITE_MEDICAMENTOS`.
    """
    motivos = []
    if pedidos.filter(estado=EstadoPedido.ENVIANDO).exists():
        motivos.append('Há um pedido em andamento. Aguarde a resposta da Anvisa.')
    if pedidos.filter(estado=EstadoPedido.INCERTO).exists():
        motivos.append(
            'Há um pedido anterior com resultado incerto. Dê os números dele por perdidos, no quadro '
            'de pedidos, para pedir outros.'
        )
    if LIMITE_DIARIO - recebidos_hoje(medico, tipo, config.ambiente) < LOTE_MINIMO:
        motivos.append(f'O limite da Anvisa é de {LIMITE_DIARIO} números de {tipo} por dia, e ele já foi '
                       'usado hoje. Peça amanhã.')
    livres = saldo(medico, tipo, config.ambiente)
    if livres >= LIMITE_MEDICAMENTOS:
        motivos.append(
            f'Você ainda tem {livres} números livres. Peça outro lote quando restarem menos de '
            f'{LIMITE_MEDICAMENTOS} — o que uma receita com {LIMITE_MEDICAMENTOS} medicamentos gasta.'
        )
    return motivos


def quantidade_do_lote(valor):
    """O tamanho do lote pedido: vazio é o padrão; fora de 10 a 50, recusa."""
    if valor in (None, ''):
        return LOTE_PADRAO
    try:
        quantidade = int(str(valor).strip())
    except ValueError:
        quantidade = 0
    if not LOTE_MINIMO <= quantidade <= LOTE_MAXIMO:
        raise PedidoRecusado(f'A Anvisa entrega de {LOTE_MINIMO} a {LOTE_MAXIMO} números por pedido.')
    return quantidade


def iniciar(request, medico, tipo, tenant_id, quantidade=None):
    """Cria o pedido e devolve o endereço do login no SNCR."""
    config = Configuracao.carregar()
    motivos = conferir(config, medico, tipo)
    if motivos:
        raise PedidoRecusado(' '.join(motivos))
    notificacao = eh_notificacao(tipo)
    if notificacao:
        quantidade = quantidade_do_lote(quantidade)
        resta = LIMITE_DIARIO - recebidos_hoje(medico, tipo, config.ambiente)
        if quantidade > resta:
            raise PedidoRecusado(
                f'Hoje ainda cabem {resta} números de {tipo} no limite diário da Anvisa. Peça {resta} ou menos.'
            )
    else:
        quantidade = None
    pedido = PedidoNumeracao.objects.create(
        medico=medico, solicitado_por=request.user, tenant_id=tenant_id, tipo=tipo,
        ambiente=config.ambiente, uf=medico.crm_state.upper(), documento=_so_digitos(medico.crm_number),
        cnpj='' if notificacao else config.cnpj_mantenedora, quantidade=quantidade,
    )
    request.session[CHAVE_DA_SESSAO] = {'id': str(pedido.id), 'em': timezone.now().isoformat()}
    record_audit_event(
        request.user.id, tenant_id, 'sncr.pedido_iniciado', object_type='sncr_pedido',
        object_id=pedido.id, outcome='success',
        integrity_metadata={'tipo': tipo, 'ambiente': config.ambiente, 'quantidade': quantidade},
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
            EstadoPedido.INCERTO, EstadoPedido.FALHOU, EstadoPedido.PERDIDO) else 'denied'),
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
        # A conferência de novo, com o médico travado (auditoria de
        # 2026-11-11). `iniciar` confere, mas o pedido que espera o login do
        # Gov.br não barra outro: do computador e do celular, em duas
        # sessões, os dois passavam, e os dois iam à Anvisa — dois blocos e
        # dois dos três pedidos do mês, ou dois lotes da cota da Vigilância.
        # Travado o médico, o segundo espera o primeiro marcar "enviando" e
        # é recusado aqui, antes de qualquer chamada.
        from accounts.models import PhysicianProfile

        medico = PhysicianProfile.objects.select_for_update().get(pk=pedido.medico_id)
        motivos = conferir(Configuracao.carregar(), medico, pedido.tipo)
        if motivos:
            return _encerrar(pedido, EstadoPedido.RECUSADO, ' '.join(motivos))
        pedido.estado = EstadoPedido.ENVIANDO
        pedido.enviado_em = timezone.now()
        pedido.save(update_fields=['estado', 'enviado_em', 'updated_at'])

    config = Configuracao.carregar()
    cli = criar_cliente(config)
    notificacao = eh_notificacao(pedido.tipo)
    try:
        token = cli.trocar_sessao(session_id)
        if notificacao:
            resposta = cli.pedir_notificacoes(
                token, pedido.tipo, pedido.conselho, pedido.uf, pedido.documento, pedido.quantidade or LOTE_PADRAO,
            )
        else:
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
        return _encerrar(pedido, EstadoPedido.INCERTO, _texto_incerto(pedido.tipo, 'Erro inesperado durante o pedido.'))
    finally:
        cli.fechar()

    if notificacao:
        return _gravar_lote(pedido, resposta)
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


def _texto_incerto(tipo, comeco):
    if eh_notificacao(tipo):
        return (f'{comeco} Os números podem ter sido retirados da sua cota; se foram, se perderam. '
                'Dê-os por perdidos para pedir outros.')
    return f'{comeco} O bloco pode ter sido entregue: confira no portal do SNCR.'


def _gravar_lote(pedido, resposta):
    try:
        lote = registrar_lote(pedido, resposta)
    except Exception:
        logger.exception('sncr: lote recebido e não gravado, pedido %s', pedido.id)
        return _encerrar(
            pedido, EstadoPedido.INCERTO,
            f'O SNCR entregou {len(resposta["numeros"])} números ({resposta["numeros"][0]} a '
            f'{resposta["numeros"][-1]}), mas o NeuroDoc não conseguiu gravá-los. Avise o suporte com estes '
            'números.',
        )
    texto = f'{lote.quantidade} números de {pedido.tipo} recebidos ({lote.inicio} a {lote.fim}).'
    if lote.saldo_visa is not None:
        texto += f' Restam {lote.saldo_visa} na sua cota da Vigilância Sanitária.'
    if resposta.get('mensagem'):
        texto += f' Anvisa: {resposta["mensagem"]}'
    if not lote.utilizavel:
        texto += ' ' + lote.motivo_bloqueio
    return _encerrar(pedido, EstadoPedido.CONCLUIDO, texto)


def dar_por_perdido(pedido_id, medico, ator_id):
    """O médico dá por perdido o pedido incerto de Notificação de Receita (decisão I18).

    Na RCE, o incerto se concilia no portal do SNCR, onde o médico vê o
    bloco dele (I14). Na Notificação não dá: o prescritor não acessa o SNCR
    (orientação da Anvisa às Vigilâncias, 2026-09-29). E também não precisa
    — dar por perdido não arrisca número repetido, porque o NeuroDoc só usa
    número que ele mesmo recebeu e gravou; o custo é, no máximo, o lote que
    talvez tenha saído da cota. Só o próprio médico, e só pedido seu ainda
    incerto.
    """
    from .models import NOTIFICACOES

    with transaction.atomic():
        pedido = (PedidoNumeracao.objects.select_for_update()
                  .filter(pk=pedido_id, medico=medico, estado=EstadoPedido.INCERTO, tipo__in=NOTIFICACOES).first())
        if pedido is None:
            raise PedidoRecusado('Este pedido não está mais pendente.')
        return _encerrar(
            pedido, EstadoPedido.PERDIDO,
            'Dado por perdido pelo médico: os números que a Anvisa possa ter entregado por este pedido não '
            'serão usados.', pedido.http_status, actor_id=ator_id,
        )


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
        _encerrar(pedido, EstadoPedido.INCERTO, _texto_incerto(pedido.tipo, 'O pedido foi interrompido no meio.'))
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
        if eh_notificacao(pedido.tipo):
            raise PedidoRecusado('O pedido incerto de Notificação de Receita é dado por perdido, não conferido.')
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
