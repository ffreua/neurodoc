"""Limite de tentativas de login.

**Três contadores, e não um** (auditoria de 2026-11-11). Até aqui a conta
era só por par e-mail + IP: quem tivesse muitos IPs ganhava cinco
tentativas por IP contra a mesma conta, e um IP só testava e-mails sem
limite nenhum. Agora contam juntos:

- o **par** e-mail + IP — o caso comum, a pessoa que errou a senha;
- a **conta**, de qualquer IP — a senha de alguém sendo tentada de muitos
  lugares;
- o **IP**, contra qualquer conta — um endereço varrendo e-mails.

O teto da conta é mais alto que o do par de propósito: ele deixa o dono da
conta preso enquanto o ataque durar, e a janela de quinze minutos é o que
limita esse custo. O do IP é mais alto ainda porque a recepção de uma
clínica, atrás de um roteador só, é um IP com várias pessoas.

**Contagem atômica.** Ler o número e gravar o seguinte deixava pedidos
simultâneos lerem o mesmo valor e passarem todos; `incr` do Redis não.

**Sem espera.** O atraso progressivo era um `time.sleep` de até dois
segundos dentro da requisição, e cada processo do `app` atende uma
requisição por vez (CLAUDE.md §8): trocando de e-mail a cada cinco
tentativas, um IP só prendia os processos sem nunca cair no bloqueio. A
recusa imediata custa ao atacante o mesmo e não custa nada ao servidor.
"""
from django.core.cache import cache

MAX_ATTEMPTS = 5
MAX_POR_CONTA = 20
MAX_POR_IP = 50
WINDOW_SECONDS = 900


def _par(email, ip):
    return f'login-throttle:{(email or "").strip().lower()}:{ip or ""}'


def _conta(email):
    return f'login-throttle-conta:{(email or "").strip().lower()}'


def _ip(ip):
    return f'login-throttle-ip:{ip or ""}'


def _limites(email, ip):
    return ((_par(email, ip), MAX_ATTEMPTS), (_conta(email), MAX_POR_CONTA), (_ip(ip), MAX_POR_IP))


def is_throttled(email, ip):
    return any(cache.get(chave, 0) >= teto for chave, teto in _limites(email, ip))


def _somar(chave):
    # `add` só cria se não existe (com o prazo); `incr` soma sem ler antes.
    cache.add(chave, 0, WINDOW_SECONDS)
    try:
        return cache.incr(chave)
    except ValueError:
        # Venceu entre o `add` e o `incr`: começa de novo.
        cache.set(chave, 1, WINDOW_SECONDS)
        return 1


def register_failure(email, ip):
    contagens = [_somar(chave) for chave, _teto in _limites(email, ip)]
    return contagens[0]


def clear_failures(email, ip):
    # Só o par: o acerto da senha prova quem está neste navegador, e não
    # zera o que outros IPs tentaram contra a conta.
    cache.delete(_par(email, ip))
