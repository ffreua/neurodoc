"""Cifragem de segredo curto guardado no banco.

Chave de API e senha de SMTP configuradas pela clínica precisam ficar no
banco — é o gestor que as informa pela tela, não um segredo de infraestrutura
posto no deploy. Guardar em texto claro significaria que um dump do banco
entrega a chave de SMS e a senha do e-mail da clínica.

Usa o mesmo desenho de envelope do PFX (`documents.credentials`): uma chave
de dados aleatória por segredo cifra o valor, e só essa chave — nunca o
valor — é embrulhada pela chave-mestra. É o que permite rotacionar a mestra
reembrulhando as chaves de dados, sem tocar nos valores.

`SECRETS_MASTER_KEY` é a mestra. Enquanto ela não for definida, cai em
`PFX_MASTER_KEY`, para a instalação existente continuar funcionando —
`master_key_is_shared()` diz quando isso está acontecendo, e a tela avisa.
Chaves separadas por finalidade são o certo: comprometer a chave de SMS não
deveria dar acesso ao certificado de assinatura.
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class SecretUnavailable(Exception):
    """Sem chave-mestra, ou o texto cifrado não abre com a chave atual."""


def master_key():
    key = getattr(settings, 'SECRETS_MASTER_KEY', '') or getattr(settings, 'PFX_MASTER_KEY', '')
    if not key:
        raise SecretUnavailable(
            'Nenhuma chave-mestra configurada (SECRETS_MASTER_KEY). '
            'Sem ela não é possível guardar segredo cifrado.'
        )
    return key.encode() if isinstance(key, str) else key


def master_key_is_shared():
    """Se a chave de segredos é a mesma do PFX — para a tela poder avisar."""
    own = getattr(settings, 'SECRETS_MASTER_KEY', '')
    return not own and bool(getattr(settings, 'PFX_MASTER_KEY', ''))


def master_key_available():
    try:
        master_key()
    except SecretUnavailable:
        return False
    return True


def encrypt_secret(value):
    """Cifra `value` e devolve o par `(texto_cifrado, metadados)`.

    Os metadados guardam a chave de dados embrulhada. Ficam juntos porque
    sem eles o texto cifrado é irrecuperável, e separá-los em duas colunas
    que podem se desencontrar não protege de nada.
    """
    if not value:
        return '', {}
    data_key = Fernet.generate_key()
    ciphertext = Fernet(data_key).encrypt(value.encode())
    wrapped = Fernet(master_key()).encrypt(data_key)
    return ciphertext.decode(), {'wrapped_key': wrapped.decode()}


def decrypt_secret(ciphertext, metadata):
    """Devolve o valor em claro, ou levanta `SecretUnavailable`.

    Levanta em vez de devolver string vazia de propósito: um segredo que
    não abre é uma falha de configuração, e tratá-lo como "vazio" faria o
    sistema tentar enviar SMS com chave em branco e reportar erro do
    provedor em vez do erro real.
    """
    if not ciphertext:
        return ''
    wrapped = (metadata or {}).get('wrapped_key')
    if not wrapped:
        raise SecretUnavailable('Segredo gravado sem a chave de dados embrulhada.')
    try:
        data_key = Fernet(master_key()).decrypt(wrapped.encode())
        return Fernet(data_key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise SecretUnavailable(
            'O segredo não abre com a chave-mestra atual. '
            'Ele foi cifrado com outra chave — informe-o de novo.'
        ) from exc


#: Quantos marcadores a máscara usa, independentemente do tamanho do
#: segredo. Ver `mask_secret`.
MASK_WIDTH = 8


def mask_secret(value, keep=4):
    """Como o segredo aparece na tela: só os últimos caracteres.

    Nunca devolve o valor inteiro. A tela precisa mostrar que **existe** uma
    chave configurada e permitir conferir que é a certa; mostrar a chave
    completa numa tela de navegador não serve a nenhum desses dois fins.

    A máscara tem largura fixa, e não o tamanho do segredo. Por dois
    motivos, um de correção e outro de sigilo:

    - As colunas que guardam a dica têm 40 caracteres. Uma máscara do
      tamanho do valor cabia para uma chave de SMS, e estourava a coluna
      para uma chave de IA, que passa de setenta caracteres — o gestor
      colava a chave e recebia `DataError` do banco em vez da tela.
    - O comprimento de um segredo é informação sobre ele. Uma fileira de
      pontos que cresce com a chave diz de que provedor ela é e quanta
      entropia tem, sem nenhum ganho para quem só quer conferir se gravou a
      chave certa.
    """
    if not value:
        return ''
    if len(value) <= keep:
        return '•' * len(value)
    return '•' * MASK_WIDTH + value[-keep:]
