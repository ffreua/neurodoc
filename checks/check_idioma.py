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
    r'with|without|from|into|only|another|belong|precede|positive)\b',
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

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o que o usuario le esta em portugues, nas telas e nas mensagens')
print('    de erro -- inclusive nos caminhos que so aparecem quando algo falha.')
