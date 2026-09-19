"""Acesso do paciente ao documento pelo link que ele recebeu.

Duas coisas juntas abrem o documento: o **link**, que é aleatório e vai só
para o contato cadastrado, e uma **resposta que o paciente sabe** — os
quatro últimos dígitos do CPF dele.

Antes o segundo fator era um código de uso único enviado por SMS ou e-mail.
Funciona, e é mais forte, mas cobra caro do paciente: ele recebe uma
mensagem com o link, pede um código, espera uma segunda mensagem, copia o
código e só então vê a receita. Numa clínica isso vira ligação para a
recepção — e, quando o SMS do código não chega, vira uma receita que o
paciente não conseguiu abrir.

O que se perde e o que se ganha:

- **Perde-se** a rotatividade. Os quatro dígitos são fixos, e quem convive
  com o paciente costuma sabê-los. Não são segredo forte.
- **Ganha-se** que a proteção real continua sendo o link: 32 bytes
  aleatórios, entregues apenas a um contato autorizado e verificado, com
  prazo. Sem o link, os quatro dígitos não servem para nada; e são 10.000
  combinações contra um limite de tentativas que trava o token.

Quem não tem CPF cadastrado — criança, na maioria das vezes — responde a
data de nascimento. Sem isso, o documento de um menor seria entregue e
impossível de abrir.
"""

import hashlib
import secrets

from django.db.models import F
from django.utils import timezone

from .models import DocumentAccessToken

TOKEN_VALIDITY_DAYS = 30

#: Tentativas por token. Cinco cobre o paciente que erra a data ou digita o
#: CPF errado; 10.000 combinações contra cinco tentativas não se adivinha.
#: O token trava — não é janela de tempo — porque quem tenta adivinhar tem
#: tempo de sobra e o paciente legítimo não precisa de mais que cinco.
MAX_ATTEMPTS = 5

CHALLENGE_CPF = 'cpf'
CHALLENGE_BIRTH_DATE = 'birth_date'


class AccessDenied(Exception):
    """Resposta errada. A mensagem é a mesma para todos os motivos."""


class AccessLocked(Exception):
    """Tentativas esgotadas para este link."""


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_access_token(document, contact):
    """O link nunca é guardado — só o resumo dele.

    Um vazamento de leitura do banco não devolve links utilizáveis, do
    mesmo jeito que não devolve senhas.
    """
    raw_token = secrets.token_urlsafe(32)
    token = DocumentAccessToken.objects.create(
        tenant=document.tenant, document=document, contact=contact,
        token_hash=_hash_token(raw_token),
        expires_at=timezone.now() + timezone.timedelta(days=TOKEN_VALIDITY_DAYS),
    )
    return token, raw_token


def resolve_token(raw_token):
    token = (
        DocumentAccessToken.objects
        .select_related('document__patient', 'document__physician__user', 'document__tenant', 'contact')
        .filter(token_hash=_hash_token(raw_token or ''))
        .first()
    )
    if token is None or token.revoked_at is not None or token.expires_at < timezone.now():
        return None
    return token


def challenge_kind(token):
    """O que perguntar a quem abriu o link.

    CPF quando o paciente tem um cadastrado; data de nascimento quando não
    tem. A escolha é do dado, não da tela: perguntar CPF a quem não tem
    seria uma pergunta sem resposta possível.
    """
    return CHALLENGE_CPF if (token.document.patient.cpf or '').strip() else CHALLENGE_BIRTH_DATE


def expected_answer(token):
    patient = token.document.patient
    if challenge_kind(token) == CHALLENGE_CPF:
        return ''.join(c for c in patient.cpf if c.isdigit())[-4:]
    if patient.birth_date is None:
        return ''
    return patient.birth_date.strftime('%d%m%Y')


def _normalize(answer, kind):
    digits = ''.join(c for c in (answer or '') if c.isdigit())
    if kind == CHALLENGE_CPF:
        # Aceita o CPF inteiro: o paciente costuma digitar tudo, e recusar
        # por isso seria recusar a resposta certa.
        return digits[-4:] if len(digits) >= 4 else digits
    return digits


def attempts_left(token):
    return max(0, MAX_ATTEMPTS - token.otp_attempts)


def verify_identity(token, answer):
    """Confere a resposta e conta a tentativa.

    A tentativa é gravada **antes** de responder, e não depois: gravar
    depois faria uma requisição interrompida no meio não contar, e quem
    tenta adivinhar interrompe de propósito.

    O incremento é um `UPDATE ... SET otp_attempts = otp_attempts + 1`
    condicionado ao limite, e não ler-somar-gravar em Python. Lido em
    Python, duas tentativas simultâneas leem o mesmo número, somam um
    sobre o mesmo número e gravam o mesmo número: duas tentativas contadas
    como uma. Quem quer adivinhar quatro dígitos manda as requisições em
    paralelo de propósito, e era assim que cinco tentativas viravam muitas
    mais. Como o próprio banco decide, a linha não atualizada **é** a
    resposta de que o limite estourou.
    """
    kind = challenge_kind(token)
    expected = expected_answer(token)
    given = _normalize(answer, kind)

    contada = type(token).objects.filter(
        pk=token.pk, otp_attempts__lt=MAX_ATTEMPTS,
    ).update(otp_attempts=F('otp_attempts') + 1)
    if not contada:
        raise AccessLocked(
            'Este link foi bloqueado por tentativas demais. Peça o reenvio à clínica.'
        )
    token.refresh_from_db(fields=['otp_attempts'])

    # `compare_digest` para o tempo de resposta não revelar quantos dígitos
    # bateram. É barato, e o hábito vale mais do que a economia.
    if not expected or not secrets.compare_digest(given, expected):
        if token.otp_attempts >= MAX_ATTEMPTS:
            raise AccessLocked(
                'Este link foi bloqueado por tentativas demais. Peça o reenvio à clínica.'
            )
        raise AccessDenied('Os dados não conferem.')

    token.otp_attempts = 0
    token.last_access_at = timezone.now()
    token.save(update_fields=['otp_attempts', 'last_access_at'])
    return True


def revoke_token(token):
    token.revoked_at = timezone.now()
    token.save(update_fields=['revoked_at'])
    return token


def revoke_previous_tokens(document):
    """Invalida os links anteriores deste documento.

    Chamado a cada reenvio. Manter vivos os links antigos multiplicaria as
    portas de entrada do mesmo documento sem nenhum ganho — e tiraria do
    reenvio a única função que ele tem quando o link vazou: fechar a
    porta antiga.
    """
    return DocumentAccessToken.objects.filter(
        document=document, revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
