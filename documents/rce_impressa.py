"""A RCE impressa não é assinada digitalmente desde 31/10/2026.

**A regra é da norma, não da falta de integração.** Perguntas e Respostas
da RDC 1.000/2025 (Anvisa, 2ª edição), perguntas 30 e 50: a Receita de
Controle Especial (RCE) **emitida eletronicamente** precisa da numeração do
SNCR. A RCE do leiaute da clínica (`special_control`) não tem número do
SNCR; assinada digitalmente, ela seria uma RCE eletrônica sem numeração.
Impressa e assinada à mão, continua válida (pergunta 7).

**De onde veio.** Esta trava nasceu na 1.21.1 como regra transitória
(`documents/sncr_transicao.py`), com avisos na tela enquanto a integração
com o SNCR não existia. Em 2026-10-29 o primeiro bloco real foi pedido em
produção e a primeira RCE eletrônica numerada foi assinada e conferida no
portal da Anvisa (`docs/sncr/ESTADO_EXECUCAO.md`): os avisos saíram, e a
trava ficou, porque o caminho digital da RCE agora é a eletrônica do SNCR
(`sncr/receita.py`).

**A prorrogação de 29/10/2026.** A Diretoria Colegiada aprovou estender
até 03/03/2027 a transição da RCE e da RET eletrônicas sem numeração. A
trava foi mantida por decisão do proprietário: com a eletrônica numerada
funcionando, não há motivo para emitir RCE digital sem número, e a
alteração ainda não estava publicada no DOU.

**Por que a data é do dia de Brasília** (`timezone.localdate`): a emissão
é ato do dia civil da clínica; o relógio do processo está em UTC e, das 21h
à meia-noite de 30/10, já responderia 31.
"""

from datetime import date

from django.utils import timezone

#: Primeiro dia em que a RCE eletrônica exige a numeração do SNCR.
DATA_EXIGENCIA = date(2026, 10, 31)

#: O motivo na trilha. O texto é o de quando a regra nasceu, de propósito:
#: mudar a chave partiria a série de recusas em duas.
MOTIVO_AUDITORIA = 'rce_eletronica_sem_numeracao_sncr'


def _integracao_ligada():
    from sncr.models import Configuracao

    return Configuracao.carregar().ativo


def recusa():
    """A mensagem da recusa, com o caminho que existe nesta instalação."""
    texto = ('A Receita de Controle Especial impressa não é assinada digitalmente: a RCE emitida '
             'eletronicamente precisa da numeração do SNCR (Anvisa, RDC 1.000/2025). ')
    if _integracao_ligada():
        return texto + ('Use “Emitir para assinar e carimbar”, ou crie a receita no formato “Controle '
                        'especial — eletrônica com numeração do SNCR”.')
    return texto + 'Use “Emitir para assinar e carimbar”: a receita impressa e assinada à mão é válida.'


def _em_vigor(hoje=None):
    return (hoje or timezone.localdate()) >= DATA_EXIGENCIA


def assinatura_digital_bloqueada(document, hoje=None):
    """A RCE do leiaute da clínica não pode ser assinada digitalmente."""
    from .models import MedicalDocumentKind
    from .pdf.prescription import SPECIAL_CONTROL

    if document.kind != MedicalDocumentKind.PRESCRIPTION:
        return False
    formato = (document.content_snapshot or {}).get('prescription_format') or ''
    return formato == SPECIAL_CONTROL and _em_vigor(hoje)
