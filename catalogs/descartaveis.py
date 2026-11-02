"""E-mail descartável: a lista, a atualização semanal e a pergunta do cadastro.

Em 2026-11-02 três clínicas foram criadas com CNPJ falso e e-mail de
caixa descartável (mailinator, guerrillamail) — o tipo de endereço que
some em uma hora e que existe justamente para não ser de ninguém. Quem
cria conta assim não recebe a verificação, a via do contrato nem a
recuperação de senha, e a clínica que fica é uma organização sem dono
alcançável. Este módulo recusa o endereço **no cadastro**, antes de a
conta existir.

**A lista vem de fora, e por isso é conferida antes de valer.** A fonte é
`Validemailchecker/disposable-email-domains` (MIT, atualizada todo dia,
~220 mil domínios). Ela é boa e não é perfeita: em 2026-11 trazia
`bol.com.br`, o e-mail gratuito do UOL, e domínios de clínicas e
escritórios brasileiros que foram usados para abuso em algum momento. Daí
as três defesas, nesta ordem:

1. ``SEMPRE_LIBERADOS``: os provedores grandes, em código. Nenhuma versão
   da lista os bloqueia — nem uma versão corrompida;
2. os **liberados no console** (`ListaDominiosDescartaveis.liberados`):
   o domínio corporativo que entrou por engano sai no mesmo dia, sem
   deploy;
3. a **conferência da lista baixada** (`ler`): formato, tamanho mínimo,
   queda brusca em relação à atual e as sentinelas. Uma lista que não
   passa não substitui a anterior, e quem opera o servidor recebe e-mail.

**O que não faz, de propósito:** não mexe em conta que já existe. Quem se
cadastrou antes de o domínio entrar na lista continua entrando — a
recusa é da porta de entrada, e bloquear quem já usa o sistema por causa
de uma lista de terceiros seria trocar um problema de cadastro por um de
assistência. Também não vale para o formulário de contato da página de
vendas: lá não se cria conta, e um lead perdido por falso positivo é a
falha que ninguém vê.
"""

import logging
import re

logger = logging.getLogger(__name__)

#: O arquivo bruto do repositório. O `main` e o caminho `data/domains.txt`
#: são o contrato com a fonte: se ela mudar de lugar, o download falha, a
#: lista anterior continua valendo e o aviso vai por e-mail.
URL = 'https://raw.githubusercontent.com/Validemailchecker/disposable-email-domains/main/data/domains.txt'
FONTE = 'github.com/Validemailchecker/disposable-email-domains'
TIMEOUT_SEGUNDOS = 60
#: Teto do download. A lista tinha 3,4 MB em 2026-11; dez vezes isso já não
#: é a mesma lista.
TAMANHO_MAXIMO_BYTES = 40 * 1024 * 1024

#: Abaixo disto a lista baixada não é a lista: é uma página de erro, um
#: arquivo truncado ou um repositório que mudou de conteúdo.
MINIMO_DE_DOMINIOS = 50_000
#: Uma lista nova menor que 70% da atual é recusada. Lista dessas cresce;
#: encolher um terço de uma semana para outra é sinal de arquivo errado, e
#: aceitar liberaria de uma vez tudo o que saiu.
QUEDA_MAXIMA = 0.30
#: Linhas que não são domínio. Até meio por cento é sujeira tolerável e é
#: descartada; acima disso o formato mudou e a lista inteira é recusada.
LINHAS_INVALIDAS_TOLERADAS = 0.005

#: Provedores que nenhuma versão da lista bloqueia. São os que um médico,
#: uma secretária ou uma clínica realmente usam, e `bol.com.br` está aqui
#: porque a lista o trazia em 2026-11. Comparados pelo domínio inteiro e
#: pelos sufixos: `alguem@mail.uol.com.br` também passa.
SEMPRE_LIBERADOS = frozenset({
    'gmail.com', 'googlemail.com',
    'outlook.com', 'outlook.com.br', 'hotmail.com', 'hotmail.com.br', 'live.com', 'live.com.br', 'msn.com',
    'yahoo.com', 'yahoo.com.br', 'ymail.com', 'rocketmail.com',
    'icloud.com', 'me.com', 'mac.com',
    'uol.com.br', 'bol.com.br', 'terra.com.br', 'ig.com.br', 'globo.com', 'globomail.com', 'r7.com',
    'oi.com.br', 'zipmail.com.br',
    'protonmail.com', 'proton.me', 'pm.me',
    'aol.com', 'gmx.com', 'gmx.net', 'zoho.com', 'yandex.com', 'fastmail.com',
})

#: Se a lista baixada trouxer qualquer um destes, ela está corrompida — e é
#: recusada inteira, em vez de valer com a exceção em código remendando.
SENTINELAS = frozenset({'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'icloud.com', 'com.br', 'com'})

#: O que a pessoa lê. Diz o que aconteceu sem acusar ninguém (quem usa um
#: domínio bloqueado por engano está lendo isto também) e diz o que fazer.
MENSAGEM_RECUSA = (
    'Este provedor de e-mail não é aceito para cadastro: ele é um serviço de e-mail '
    'temporário ou descartável, e não é considerado confiável. Use outro e-mail válido — '
    'o do seu consultório, da sua instituição ou de um provedor como Gmail ou Outlook. '
    'Se o seu domínio foi recusado por engano, escreva para contato@neurodoc.app.br.'
)

_DOMINIO_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$')


class ListaRecusada(Exception):
    """A lista baixada não passou na conferência. A mensagem vai ao console."""


# ------------------------------------------------------------------ pergunta

def dominio_do_email(email):
    """O domínio, minúsculo e em ASCII (o domínio acentuado vira `xn--`)."""
    email = (email or '').strip().lower()
    if '@' not in email:
        return ''
    dominio = email.rsplit('@', 1)[1].strip().rstrip('.')
    try:
        dominio = dominio.encode('idna').decode('ascii')
    except UnicodeError:
        pass
    return dominio


def _sufixos(dominio):
    """`a.b.mailinator.com` → os três com pelo menos um ponto.

    Os serviços descartáveis entregam caixa em subdomínio aleatório; a lista
    traz o domínio de base. Comparar só o domínio inteiro deixaria passar
    `xk2.mailinator.com`.
    """
    partes = dominio.split('.')
    return ['.'.join(partes[i:]) for i in range(len(partes) - 1)]


def _liberados_do_console():
    from .models import ListaDominiosDescartaveis

    # `filter().first()` e não `carregar()`: a pergunta é feita no meio de um
    # cadastro, e perguntar não deve gravar linha nenhuma.
    linha = ListaDominiosDescartaveis.objects.filter(singleton=True).first()
    return linha.dominios_liberados() if linha else set()


def e_descartavel(email):
    """O endereço é de um serviço de e-mail descartável?

    Liberado (em código ou no console) vence a lista, pelo domínio inteiro
    ou por qualquer sufixo. Lista vazia — instalação nova antes da primeira
    sincronização — responde "não": a recusa é uma defesa a mais, e não a
    condição para alguém conseguir se cadastrar.
    """
    from .models import DominioDescartavel

    candidatos = _sufixos(dominio_do_email(email))
    if not candidatos:
        return False
    liberados = SEMPRE_LIBERADOS | _liberados_do_console()
    if any(c in liberados for c in candidatos):
        return False
    return DominioDescartavel.objects.filter(dominio__in=candidatos).exists()


def validar_email_de_cadastro(email):
    """Para os formulários: `ValidationError` com a mensagem da tela."""
    from django.core.exceptions import ValidationError

    if e_descartavel(email):
        raise ValidationError(MENSAGEM_RECUSA, code='email_descartavel')


# ---------------------------------------------------------- atualização

def ler(conteudo, atual=0):
    """Do arquivo baixado ao conjunto de domínios — ou `ListaRecusada`.

    `atual` é quantos domínios a lista em uso tem: é contra ela que se mede
    a queda. Uma linha por domínio; linha vazia e comentário (`#`) são
    ignorados, que é o que a fonte publica hoje e o que um formato vizinho
    publicaria.
    """
    if isinstance(conteudo, bytes):
        try:
            conteudo = conteudo.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ListaRecusada('O arquivo não é texto UTF-8: o formato da fonte mudou.') from exc

    dominios, invalidas, linhas = set(), 0, 0
    for linha in conteudo.splitlines():
        linha = linha.strip().lower().rstrip('.')
        if not linha or linha.startswith('#'):
            continue
        linhas += 1
        if len(linha) <= 253 and _DOMINIO_RE.fullmatch(linha):
            dominios.add(linha)
        else:
            invalidas += 1

    if linhas and invalidas / linhas > LINHAS_INVALIDAS_TOLERADAS:
        raise ListaRecusada(
            f'{invalidas} de {linhas} linhas não são domínios: o formato da fonte mudou. '
            'A lista anterior continua valendo.'
        )
    if len(dominios) < MINIMO_DE_DOMINIOS:
        raise ListaRecusada(
            f'A lista baixada tem {len(dominios)} domínios, abaixo do mínimo de '
            f'{MINIMO_DE_DOMINIOS}: não é a lista esperada. A anterior continua valendo.'
        )
    if atual and len(dominios) < atual * (1 - QUEDA_MAXIMA):
        raise ListaRecusada(
            f'A lista baixada tem {len(dominios)} domínios contra {atual} da atual — uma queda '
            f'maior que {int(QUEDA_MAXIMA * 100)}%. Recusada; a anterior continua valendo.'
        )
    corrompida = sorted(dominios & SENTINELAS)
    if corrompida:
        raise ListaRecusada(
            f'A lista baixada traz {", ".join(corrompida)}, que não é serviço descartável: '
            'está corrompida. A anterior continua valendo.'
        )
    return dominios


def gravar(dominios):
    """Troca a lista do banco pela nova, pela diferença e numa transação só.

    Pela diferença porque de uma semana para outra entram e saem algumas
    centenas de 220 mil: reescrever tudo seria apagar e inserir a tabela
    inteira toda semana. Numa transação porque quem se cadastra no meio da
    troca enxerga a lista anterior inteira até o commit, e a nova inteira
    depois — nunca uma tabela pela metade. A linha de estado é travada
    (`select_for_update`), para o botão "Atualizar agora" e a rodada de
    domingo não se cruzarem.
    """
    from django.db import transaction
    from django.utils import timezone

    from .models import DominioDescartavel, ListaDominiosDescartaveis

    ListaDominiosDescartaveis.carregar()
    with transaction.atomic():
        estado = ListaDominiosDescartaveis.objects.select_for_update().get(singleton=True)
        existentes = set(DominioDescartavel.objects.values_list('dominio', flat=True))
        novos = sorted(dominios - existentes)
        removidos = sorted(existentes - dominios)
        DominioDescartavel.objects.bulk_create(
            [DominioDescartavel(dominio=d) for d in novos], batch_size=5000, ignore_conflicts=True,
        )
        for i in range(0, len(removidos), 5000):
            DominioDescartavel.objects.filter(dominio__in=removidos[i:i + 5000]).delete()
        agora = timezone.now()
        estado.total = len(dominios)
        estado.atualizada_em = agora
        estado.ultima_tentativa_em = agora
        estado.ultimo_erro = ''
        estado.save(update_fields=['total', 'atualizada_em', 'ultima_tentativa_em', 'ultimo_erro', 'updated_at'])
    return {'total': len(dominios), 'entraram': len(novos), 'sairam': len(removidos)}


def baixar():
    """O arquivo da fonte, com teto de tamanho. Só no worker (CLAUDE.md §2)."""
    import httpx

    with httpx.stream(
        'GET', URL, timeout=TIMEOUT_SEGUNDOS, follow_redirects=True,
        headers={'User-Agent': 'NeuroDoc (lista de e-mail descartavel; contato@neurodoc.app.br)'},
    ) as resposta:
        resposta.raise_for_status()
        partes, tamanho = [], 0
        for parte in resposta.iter_bytes():
            tamanho += len(parte)
            if tamanho > TAMANHO_MAXIMO_BYTES:
                raise ListaRecusada(
                    f'O arquivo passou de {TAMANHO_MAXIMO_BYTES // (1024 * 1024)} MB: não é a lista '
                    'esperada. A anterior continua valendo.'
                )
            partes.append(parte)
    return b''.join(partes)


def registrar_falha(motivo):
    """Grava o motivo na linha de estado e avisa quem opera o servidor."""
    from django.utils import timezone

    from .models import ListaDominiosDescartaveis

    estado = ListaDominiosDescartaveis.carregar()
    estado.ultima_tentativa_em = timezone.now()
    estado.ultimo_erro = motivo[:2000]
    estado.save(update_fields=['ultima_tentativa_em', 'ultimo_erro', 'updated_at'])
    return avisar_falha(estado)


def avisar_falha(estado):
    """E-mail a todo superadministrador ativo. Só configuração, nenhum dado pessoal.

    A cada falha, e não "na passagem para a falha" como a vigilância da IA:
    a rodada é semanal, então são no máximo quatro e-mails num mês ruim, e
    cada um diz de quando é a lista que continua valendo.
    """
    from django.conf import settings
    from django.core.mail import send_mail
    from django.utils import timezone

    from accounts.models import User

    destinos = list(
        User.objects.filter(is_superuser=True, is_active=True)
        .exclude(email='').values_list('email', flat=True)
    )
    if not destinos:
        return 0
    if estado.atualizada_em:
        vigente = (
            f'A lista em uso continua sendo a de '
            f'{timezone.localtime(estado.atualizada_em).strftime("%d/%m/%Y")}, com {estado.total} domínios: '
            'o cadastro segue recusando o que ela recusava.'
        )
    else:
        vigente = (
            'Nenhuma lista foi carregada ainda: enquanto isso, o cadastro NÃO recusa e-mail '
            'descartável nenhum.'
        )
    corpo = (
        'A atualização semanal da lista de domínios de e-mail descartável falhou.\n\n'
        f'Fonte: {URL}\n'
        f'Motivo: {estado.ultimo_erro}\n\n'
        f'{vigente}\n\n'
        'Se a fonte mudou de endereço ou de formato, é preciso ajustar '
        '`catalogs/descartaveis.py`. Para conferir ou tentar de novo: '
        f'{settings.PUBLIC_BASE_URL.rstrip("/")}/instalacao/operacao/'
    )
    try:
        send_mail(
            '[NeuroDoc] A lista de e-mail descartável não foi atualizada', corpo,
            settings.DEFAULT_FROM_EMAIL, destinos, fail_silently=False,
        )
    except Exception:                                   # noqa: BLE001
        logger.exception('descartaveis: falha ao enviar o aviso')
        return 0
    return len(destinos)


def sincronizar(conteudo=None):
    """Baixa (ou recebe), confere e grava. Nunca levanta: devolve o desfecho.

    Qualquer falha — rede, HTTP, formato, conferência, banco — mantém a lista
    anterior e vira aviso. É a regra do pedido: "se não conseguir ou o
    repositório mudar, avisa por e-mail".
    """
    from .models import ListaDominiosDescartaveis

    try:
        if conteudo is None:
            conteudo = baixar()
        atual = ListaDominiosDescartaveis.carregar().total
        resultado = gravar(ler(conteudo, atual=atual))
    except ListaRecusada as exc:
        avisados = registrar_falha(str(exc))
        logger.warning('descartaveis: recusada: %s', exc)
        return {'ok': False, 'erro': str(exc), 'avisados': avisados}
    except Exception as exc:                            # noqa: BLE001
        motivo = f'Não foi possível baixar ou gravar a lista ({type(exc).__name__}: {exc}).'
        avisados = registrar_falha(motivo)
        logger.warning('descartaveis: %s', motivo)
        return {'ok': False, 'erro': motivo, 'avisados': avisados}
    logger.info('descartaveis: %(total)s domínios (+%(entraram)s, -%(sairam)s)', resultado)
    return {'ok': True, **resultado}
