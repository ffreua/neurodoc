"""O SMTP próprio conecta no IP conferido (auditoria de 2026-11-11).

O servidor de e-mail da clínica é conferido pelo DNS (`_exigir_host_publico`
recusa endereço interno), mas o `smtplib` perguntava ao DNS de novo ao
conectar. Quem controla o domínio respondia um IP público à primeira
pergunta e um interno à segunda (*DNS rebinding*).

O que se tenta quebrar, com o DNS e a rede simulados (nada sai da máquina):

1. **o rebinding**: a primeira resposta é pública, a segunda é o Redis da
   instalação — a conexão tem de ir ao IP público, e o DNS ser perguntado
   uma vez só;
2. **o certificado**: no SSL direto (porta 465), a conexão vai ao IP e o
   nome que o TLS confere continua sendo o do servidor, e não o IP;
3. **a recusa de sempre**: host que já resolve para endereço interno é
   recusado antes de qualquer conexão;
4. **o IPv4 primeiro** quando o servidor tem os dois.
"""
import socket
from types import SimpleNamespace

from communications.email import ServidorNaoPublico, _connection_for

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


class Parar(Exception):
    """Interrompe a conexão simulada depois de anotar para onde ela ia."""


PUBLICO, INTERNO = '93.184.215.14', '10.0.1.7'


def remetente(**extra):
    base = dict(uses_own_server=True, host='smtp.clinica-roteiro.example', port=587,
                user='u', use_tls=True, use_ssl=False, password=lambda: 'p')
    base.update(extra)
    return SimpleNamespace(**base)


getaddrinfo_original = socket.getaddrinfo
create_connection_original = socket.create_connection
anotado = {'perguntas': 0, 'destinos': []}


def dns_que_troca(host, port, *args, **kwargs):
    """Primeira pergunta: IP público. Daí em diante: o interno."""
    anotado['perguntas'] += 1
    ip = PUBLICO if anotado['perguntas'] == 1 else INTERNO
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]


def conexao_anotada(endereco, *args, **kwargs):
    anotado['destinos'].append(endereco[0])
    raise Parar()


try:
    socket.getaddrinfo = dns_que_troca
    socket.create_connection = conexao_anotada

    print('=== 1. o rebinding ===')
    conexao = _connection_for(remetente())
    conferir('o backend e o que fixa o IP', type(conexao).__name__, 'ServidorConferidoBackend')
    conferir('o IP fixado e o da conferencia', conexao.ip_conferido, PUBLICO)
    try:
        conexao.open()
    except Parar:
        pass
    conferir('a conexao foi ao IP publico', anotado['destinos'], [PUBLICO])
    conferir('o DNS foi perguntado uma vez so', anotado['perguntas'], 1)

    print('=== 2. o certificado (SSL direto, porta 465) ===')
    anotado.update(perguntas=0, destinos=[])
    socket.create_connection = lambda endereco, *a, **k: (anotado['destinos'].append(endereco[0]) or object())
    conexao = _connection_for(remetente(port=465, use_tls=False, use_ssl=True))
    conferir('a classe e a de SSL', conexao.connection_class.__mro__[1].__name__, 'SMTP_SSL')
    nomes = []

    def embrulhar(sock, server_hostname=None, **kwargs):
        nomes.append(server_hostname)
        raise Parar()

    conexao.ssl_context.wrap_socket = embrulhar
    try:
        conexao.open()
    except Parar:
        pass
    conferir('o SSL tambem vai ao IP publico', anotado['destinos'], [PUBLICO])
    conferir('o TLS confere o certificado pelo nome do servidor', nomes,
             ['smtp.clinica-roteiro.example'])
    socket.create_connection = conexao_anotada

    print('=== 3. a recusa de sempre ===')
    socket.getaddrinfo = lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (INTERNO, port))]
    anotado.update(destinos=[])
    try:
        _connection_for(remetente())
        recusado = False
    except ServidorNaoPublico:
        recusado = True
    conferir('host que resolve para endereco interno e recusado', recusado, True)
    conferir('  sem nenhuma conexao', anotado['destinos'], [])

    print('=== 4. o IPv4 primeiro ===')
    socket.getaddrinfo = lambda host, port, *a, **k: [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:4860:4860::8888', port, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLICO, port)),
    ]
    conferir('com IPv4 e IPv6, o IPv4', _connection_for(remetente()).ip_conferido, PUBLICO)
finally:
    socket.getaddrinfo = getaddrinfo_original
    socket.create_connection = create_connection_original

print()
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: o SMTP proprio conecta no IP que passou na conferencia, e o TLS confere o nome.')
