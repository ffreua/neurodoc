"""Tudo que o usuario le esta em portugues.

O produto e para consultorio brasileiro, e o CLAUDE.md diz isso na
primeira linha das convencoes. Mesmo assim, uma mensagem em ingles
atravessou ate producao e foi o proprio medico quem a encontrou: ao errar
a senha algumas vezes, o login respondia **"Too many attempts. Try again
later."**

**Por que escapa com tanta facilidade.** Mensagem de erro e o texto que
ninguem le enquanto escreve a tela -- ela so aparece no caminho que deu
errado, e o caminho que deu errado e justamente o que nao se exercita ao
desenvolver. Dezenove mensagens estavam assim, espalhadas por nove
arquivos, e a maioria em `clean()` de modelo: validacao que so dispara com
dado invalido.

**O que este roteiro cobra, e o que ele deixa passar de proposito:**

- **cobra** o texto que chega a tela: `messages.*`, `ValidationError`,
  `label=`, `help_text=`, e as excecoes das classes que as views mostram
  com `str(exc)`;
- **deixa passar** mensagem de log, de `CommandError` de comando
  administrativo, e de excecao que so quem opera o servidor le. Ingles ali
  nao atrapalha ninguem, e exigir portugues criaria ruido que faria o
  roteiro ser ignorado.

A deteccao e por lista de palavras inglesas, nao por adivinhacao: duas ou
mais numa frase sem acento portugues. Uma so seria coincidencia --
"email", "error" e "status" vivem no portugues tecnico.
"""
import ast
import re
from pathlib import Path

from django.conf import settings as dj_settings

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:56} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


print('\n1. O produto esta configurado em portugues')
conferir('LANGUAGE_CODE', dj_settings.LANGUAGE_CODE, 'pt-br')
conferir('USE_I18N ligado (traduz o que vem do Django)', dj_settings.USE_I18N, True)

print('\n2. Nenhuma mensagem de interface em ingles')

#: Chamadas cujo texto vai para a tela.
ALVOS_CHAMADA = {
    'error', 'success', 'warning', 'info', 'add_message',
    'ValidationError', 'PermissionDenied', 'SuspiciousOperation',
}
#: Argumentos nomeados que viram rotulo de campo.
ALVOS_KWARG = {'label', 'help_text', 'verbose_name', 'placeholder', 'empty_label'}

#: Excecoes que as views mostram ao usuario com `str(exc)`. A lista e
#: fechada de proposito: excecao que so o servidor le pode ficar em
#: ingles, e misturar as duas faria o roteiro acusar o que nao importa.
EXCECOES_NA_TELA = {
    'SchedulingError', 'SlotUnavailable', 'IllegalTransition',
    'FinalizationError', 'UploadRejected', 'QuotaExceeded',
    'InvalidPfxPassword', 'CredentialNotUsable', 'InvalidDuration',
    'SigningSessionKeyMissing', 'RecentMfaRequired', 'NoUsableContact',
    'PlanLimitReached', 'ChatError', 'SmsChannelDisabled',
    # Acrescentadas pela secao 5, que as encontrou sozinha. Tres delas
    # estavam em ingles e chegavam a tela: a recusa do rascunho ja
    # revisado, a autorizacao da IA e o limite de respostas do chat.
    'AlreadyReviewed', 'ArtifactStale', 'RelatorioNaoAprovado',
    'RascunhoJaVirouDocumento', 'MissingPhysicianProfile',
    'AIAuthorizationDenied', 'ConcurrencyLimitExceeded',
    'ProviderProbeFailed', 'CampaignBlocked',
}

#: Arquivos que falam com quem opera o servidor, nao com quem usa o
#: produto. O console de instalacao fala portugues porque o
#: superadministrador tambem e brasileiro, mas os comandos e o deploy sao
#: ferramenta de operacao.
FORA = {'.venv', 'migrations', 'node_modules', '.git', 'site', 'checks',
        'docs', 'ops', 'management'}

INGLES = re.compile(
    r'\b(the|this|that|these|those|and|are|was|were|been|'
    r'you|your|our|its|their|must|cannot|should|would|will|'
    r'please|try|again|later|too|many|invalid|required|missing|'
    r'already|exists|does|failed|unknown|expired|disabled|enabled|'
    r'allowed|denied|provide|enter|select|choose|upload|'
    r'with|without|from|into|only|another|belong|precede|positive|'
    # Acrescentadas depois de "Artifact already rejected" chegar a
    # producao: a frase tinha uma unica palavra da lista, e o detector
    # exige duas. Palavra sem homonimo no portugues tecnico, so.
    r'rejected|accepted|changed|since|before|regenerate|reviewing|'
    r'draft|review|source|generation)\b',
    re.IGNORECASE,
)
ACENTO = re.compile(r'[áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ]')


def parece_ingles(texto):
    if len(texto.strip()) < 8 or ACENTO.search(texto):
        return False
    return len(INGLES.findall(texto)) >= 2


def textos_da_chamada(no):
    """Os literais de um `Call` que podem virar texto de tela."""
    nome = (no.func.attr if isinstance(no.func, ast.Attribute)
            else getattr(no.func, 'id', ''))
    saida = []
    if nome in ALVOS_CHAMADA or nome in EXCECOES_NA_TELA:
        for a in no.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                saida.append((a.lineno, a.value))
            elif isinstance(a, ast.JoinedStr):
                partes = ''.join(
                    v.value for v in a.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
                saida.append((a.lineno, partes))
            elif isinstance(a, ast.Dict):
                for v in a.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        saida.append((v.lineno, v.value))
    for kw in no.keywords:
        if kw.arg in ALVOS_KWARG and isinstance(kw.value, ast.Constant) \
                and isinstance(kw.value.value, str):
            saida.append((kw.value.lineno, kw.value.value))
    return saida


raiz = Path(dj_settings.BASE_DIR)
encontradas = []
for arquivo in sorted(raiz.rglob('*.py')):
    if any(parte in FORA for parte in arquivo.parts):
        continue
    try:
        arvore = ast.parse(arquivo.read_text(encoding='utf-8'))
    except SyntaxError:
        continue
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call):
            for linha, texto in textos_da_chamada(no):
                if parece_ingles(texto):
                    encontradas.append(
                        f'{arquivo.relative_to(raiz)}:{linha}  {texto[:70]!r}'
                    )

for item in sorted(set(encontradas)):
    print(f'      {item}')
conferir('mensagens de interface em ingles', len(set(encontradas)), 0)

print('\n3. Nem nos templates')
visiveis = []
for arquivo in sorted((raiz / 'templates').rglob('*.html')):
    bruto = arquivo.read_text(encoding='utf-8')
    # Tira o que nao e texto visivel.
    texto = re.sub(r'(?s)\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', ' ', bruto)
    texto = re.sub(r'(?s)\{#.*?#\}', ' ', texto)
    texto = re.sub(r'(?s)<script.*?</script>', ' ', texto)
    texto = re.sub(r'(?s)<style.*?</style>', ' ', texto)
    texto = re.sub(r'(?s)<!--.*?-->', ' ', texto)
    texto = re.sub(r'\{[%{].*?[%}]\}', ' ', texto)
    texto = re.sub(r'<[^>]+>', ' ', texto)
    for numero, linha in enumerate(texto.split('\n'), 1):
        limpa = ' '.join(linha.split())
        if parece_ingles(limpa):
            visiveis.append(f'{arquivo.relative_to(raiz)}:{numero}  {limpa[:70]!r}')

for item in visiveis:
    print(f'      {item}')
conferir('texto visivel em ingles nos templates', len(visiveis), 0)

print('\n4. A mensagem que o medico encontrou, especificamente')
# O caso que originou este roteiro. Fica nomeado para que, se alguem
# reescrever o bloqueio de login, a assercao continue cobrando o idioma.
origem = Path(dj_settings.BASE_DIR, 'accounts', 'forms.py').read_text(encoding='utf-8')
conferir('o bloqueio por tentativas fala portugues',
         'Muitas tentativas' in origem, True)
conferir('e nao fala ingles', 'Too many attempts' in origem, False)

print('\n5. Nenhuma excecao nova escapa da lista')
# A lista `EXCECOES_NA_TELA` e escrita a mao, e foi por isso que
# "Artifact already rejected" chegou ao medico: a excecao que a produzia
# nao estava nela, entao o roteiro nunca olhou para o texto dela.
#
# Esta secao inverte o onus. Em vez de confiar que alguem lembrou de
# acrescentar o nome, ela **procura** no codigo quem mostra `str(exc)` ao
# usuario e cobra que esses nomes estejam na lista. Lista desatualizada
# passa a ser falha de roteiro, e nao um silencio.


def _mostra_excecao(handler):
    """O corpo deste `except` devolve `str(exc)` ao usuario?"""
    if not handler.name:
        return False
    for no in ast.walk(handler):
        if not isinstance(no, ast.Call):
            continue
        nome = (no.func.attr if isinstance(no.func, ast.Attribute)
                else getattr(no.func, 'id', ''))
        # `str(exc)` dentro de uma resposta, de um `messages.*` ou de um
        # `render`: o que chega a tela de um jeito ou de outro.
        if nome == 'str' and len(no.args) == 1 \
                and isinstance(no.args[0], ast.Name) and no.args[0].id == handler.name:
            return True
    return False


def _nomes_do_handler(handler):
    alvo = handler.type
    if isinstance(alvo, ast.Name):
        return [alvo.id]
    if isinstance(alvo, ast.Tuple):
        return [e.id for e in alvo.elts if isinstance(e, ast.Name)]
    return []


#: Excecoes de biblioteca, cujo texto nao escrevemos. Ficam de fora porque
#: exigir portugues delas seria exigir que o Django mudasse de idioma.
DE_BIBLIOTECA = {'Exception', 'ValueError', 'TypeError', 'KeyError', 'OSError',
                 'ValidationError', 'PermissionDenied', 'SuspiciousOperation',
                 'IntegrityError', 'Http404'}

fora_da_lista = []
for arquivo in sorted(raiz.rglob('*views*.py')):
    if any(parte in FORA for parte in arquivo.parts):
        continue
    try:
        arvore = ast.parse(arquivo.read_text(encoding='utf-8'))
    except SyntaxError:
        continue
    for no in ast.walk(arvore):
        if not isinstance(no, ast.ExceptHandler) or not _mostra_excecao(no):
            continue
        for nome in _nomes_do_handler(no):
            if nome in EXCECOES_NA_TELA or nome in DE_BIBLIOTECA:
                continue
            fora_da_lista.append(
                f'{arquivo.relative_to(raiz)}:{no.lineno}  {nome}'
            )

for item in sorted(set(fora_da_lista)):
    print(f'      {item}')
conferir('excecoes mostradas ao usuario e nao conferidas',
         len(set(fora_da_lista)), 0)

# E a que originou esta secao, nomeada: se alguem reescrever a revisao de
# rascunho, a assercao continua cobrando o idioma.
revisao = Path(dj_settings.BASE_DIR, 'ai', 'review.py').read_text(encoding='utf-8')
conferir('a recusa do rascunho ja revisado fala portugues',
         'já foi revisado' in revisao, True)
conferir('e nao fala ingles', 'Artifact already' in revisao, False)

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o que o usuario le esta em portugues, nas telas e nas mensagens')
print('    de erro -- inclusive nos caminhos que so aparecem quando algo falha.')
