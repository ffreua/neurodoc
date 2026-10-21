"""Transição do SNCR: a RCE eletrônica sem numeração deixa de valer em 31/10/2026.

**Regra transitória, com data para sair.** Ela existe até a integração
com o SNCR (Sistema Nacional de Controle de Receituários, Anvisa) entrar
em produção — trabalho em `docs/sncr/`. Quando a receita eletrônica
passar a sair com a numeração do SNCR, este módulo é retirado junto com
os três pontos que o consultam (a assinatura em `issuance`, o aviso na
tela do documento e o aviso no formulário).

**O que a norma diz.** Perguntas e Respostas da RDC 1.000/2025 (Anvisa,
2ª edição), perguntas 30 e 50: de 30/09 a 30/10/2026, a Receita de
Controle Especial (RCE) e a Receita Sujeita à Retenção (RET) **emitidas
eletronicamente** podem sair sem numeração do SNCR; **a partir de
31/10/2026, precisam dela**. A RCE **impressa e assinada à mão** continua
válida, inclusive no leiaute da clínica, desde que traga "Receita de
Controle Especial" e os campos obrigatórios (pergunta 7).

**O que o NeuroDoc faz até a integração.** A RCE é um formato que o
médico escolhe (`special_control`), então dá para barrar com certeza: a
partir de 31/10, ela não é mais **assinada digitalmente**; sai pelo
"Emitir para assinar e carimbar". A RET não é: o NeuroDoc não classifica
o medicamento (antimicrobiano, agonista de GLP-1), e por isso a receita
simples **não** é barrada — ela recebe só o aviso, e a decisão fica com o
médico. Barrar toda receita simples digital para alcançar a RET pararia
o consultório inteiro por causa de uma minoria de receitas.

**Por que a data é do dia de Brasília** (`timezone.localdate`): a
emissão é um ato do dia civil da clínica; o relógio do processo está em
UTC e, das 21h à meia-noite de 30/10, já responderia 31.
"""

from datetime import date

from django.utils import timezone

#: Primeiro dia em que a RCE/RET eletrônica exige a numeração do SNCR.
DATA_EXIGENCIA = date(2026, 10, 31)

MOTIVO_AUDITORIA = 'rce_eletronica_sem_numeracao_sncr'

RECUSA_ASSINATURA = (
    'A partir de 31/10/2026, a Receita de Controle Especial emitida eletronicamente '
    'precisa da numeração do SNCR (Anvisa), e a integração do NeuroDoc com o SNCR '
    'ainda está em implantação. Use “Emitir para assinar e carimbar”: a receita '
    'impressa e assinada à mão continua válida.'
)


def _formato(document):
    from .models import MedicalDocumentKind

    if document.kind != MedicalDocumentKind.PRESCRIPTION:
        return None
    return (document.content_snapshot or {}).get('prescription_format') or ''


def _em_vigor(hoje=None):
    return (hoje or timezone.localdate()) >= DATA_EXIGENCIA


def assinatura_digital_bloqueada(document, hoje=None):
    """A RCE não pode mais ser assinada digitalmente sem número do SNCR."""
    from .pdf.prescription import SPECIAL_CONTROL

    return _formato(document) == SPECIAL_CONTROL and _em_vigor(hoje)


def aviso(document=None, hoje=None, formato=None):
    """O aviso que a tela mostra, ou `None` quando não há o que avisar.

    Devolve um dicionário com `nivel` (`danger` quando a assinatura digital
    já está barrada, `warning` antes disso e para a receita simples),
    `titulo` e `texto`. `formato` permite pedir o aviso sem documento — é o
    caso do formulário de criação, onde o formato ainda não foi escolhido.
    """
    from .pdf.prescription import SIMPLE, SPECIAL_CONTROL

    if document is not None:
        formato = _formato(document)
    if formato is None:
        return None
    vigente = _em_vigor(hoje)
    if formato == SPECIAL_CONTROL:
        if vigente:
            return {
                'nivel': 'danger',
                'titulo': 'Receita de Controle Especial: emissão só em papel',
                'texto': (
                    'Desde 31/10/2026, a RCE emitida eletronicamente precisa da numeração '
                    'do SNCR (Anvisa, RDC 1.000/2025). Enquanto a integração do NeuroDoc com '
                    'o SNCR é concluída, a assinatura digital desta receita está suspensa: '
                    'emita para assinar e carimbar. A receita impressa, assinada à mão, '
                    'continua válida.'
                ),
            }
        return {
            'nivel': 'warning',
            'titulo': 'Receita de Controle Especial: mudança em 31/10/2026',
            'texto': (
                'A partir de 31/10/2026, a RCE emitida eletronicamente precisará da '
                'numeração do SNCR (Anvisa, RDC 1.000/2025). Até a integração do NeuroDoc '
                'com o SNCR ser concluída, a partir dessa data a RCE sairá só para assinar '
                'e carimbar.'
            ),
        }
    if formato in (SIMPLE, ''):
        quando = 'Desde' if vigente else 'A partir de'
        return {
            'nivel': 'warning',
            'titulo': 'Antimicrobiano ou agonista de GLP-1?',
            'texto': (
                f'{quando} 31/10/2026, a receita sujeita à retenção (antimicrobianos, '
                'agonistas de GLP-1) emitida eletronicamente precisa da numeração do SNCR '
                '(Anvisa). Se esta receita contém um desses medicamentos, emita para '
                'assinar e carimbar até a integração do NeuroDoc com o SNCR ser concluída.'
            ),
        }
    return None
