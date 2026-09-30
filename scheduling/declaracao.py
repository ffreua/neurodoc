"""Declaração de comparecimento: o papel que o paciente leva ao trabalho.

O paciente falta meio dia de serviço para consultar, e o empregador quer
prova. Até aqui isso saía escrito à mão num papel timbrado, ou não saía.

**Por que a secretária pode emitir, e isso não é lapso de autorização.**
Declaração de comparecimento e atestado médico são documentos diferentes,
e a diferença é quem pode assiná-los:

- o **atestado** afirma incapacidade para o trabalho. É juízo clínico, é
  ato médico, e quem o assina responde por ele no CRM;
- a **declaração de comparecimento** afirma um fato administrativo — esta
  pessoa esteve aqui, das 14h às 16h30. Quem registrou a chegada e a saída
  foi a recepção, e é a recepção que sabe.

Por isso a capacidade exigida é `SCHEDULE`, a mesma da agenda, e o
documento **nunca** diz que o paciente está incapacitado, nem por quanto
tempo. O texto foi escrito para não dar margem: afirma presença e horário,
e nada mais.

**O documento não carrega diagnóstico, CID nem motivo da consulta.** Ele
vai para a mão do empregador. Informação de saúde é dado pessoal sensível
(LGPD art. 5º, II), e uma declaração de comparecimento que dissesse "para
avaliação de epilepsia" entregaria ao patrão exatamente o que a lei protege
— com o próprio paciente carregando o papel, sem saber que carregava. O que
a clínica é já aparece pelo timbre, e isso é inevitável; o resto não é.

**O arquivo não fica guardado, mas a emissão fica registrada.** O papel se
imprime e acabou — não há PDF armazenado, e foi isso que se pediu. Mas o
*ato* entra na trilha de auditoria com os horários declarados, porque
"a clínica me deu um papel dizendo que saí às 18h" é conversa que existe, e
quando ela acontece alguém precisa saber o que foi emitido. Registrar o
ato custa uma linha; não registrar custa a palavra de alguém contra a de
outro.
"""
from datetime import datetime

from django.utils import timezone

from audit.services import record_audit_event

#: Formato dos campos de hora da tela. Vem do `<input type="time">`.
FORMATO_HORA = '%H:%M'


def _hora(texto, padrao):
    """Lê `HH:MM` da tela; qualquer outra coisa cai no padrão.

    Hora malformada não pode virar erro 500 nem, pior, sair impressa como
    `None` num papel que vai para o empregador.
    """
    try:
        return datetime.strptime((texto or '').strip(), FORMATO_HORA).time()
    except ValueError:
        return padrao


def horarios(appointment, entrada_texto='', saida_texto=''):
    """Os horários que vão no papel, em hora local.

    O padrão é o do agendamento — é o que a secretária confirma nove vezes
    em dez. Quando o paciente chegou adiantado ou o atendimento passou da
    hora, ela corrige, e o que vale é o que ela digitou: quem viu a pessoa
    entrar e sair foi ela, não a grade.
    """
    inicio = timezone.localtime(appointment.starts_at)
    fim = timezone.localtime(appointment.ends_at)
    entrada = _hora(entrada_texto, inicio.time())
    saida = _hora(saida_texto, fim.time())
    return {
        'data': inicio.date(),
        'entrada': entrada,
        'saida': saida,
        # Saída anterior à entrada é erro de digitação, e o papel não pode
        # sair dizendo "das 16h às 14h". A tela avisa em vez de imprimir.
        'invertido': saida < entrada,
        'duracao': _duracao(entrada, saida),
    }


def _duracao(entrada, saida):
    """Quanto tempo o paciente ficou, em texto legível.

    Sai no documento porque é o número que o departamento pessoal usa, e
    obrigá-lo a subtrair dois horários é convidar a conta errada.
    """
    if saida < entrada:
        return ''
    minutos = (
        (saida.hour * 60 + saida.minute) - (entrada.hour * 60 + entrada.minute)
    )
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f'{horas}h{resto:02d}'
    if horas:
        return f'{horas}h'
    return f'{resto} minutos'


def registrar_emissao(context, appointment, dados, actor_membership, acompanhante=''):
    """Põe a emissão na trilha. O papel não fica; o ato fica.

    Sem conteúdo clínico no metadado — o mesmo motivo pelo qual ele não
    está no papel.
    """
    record_audit_event(
        actor_membership.user_id, context.tenant_id,
        'scheduling.attendance_statement_issued',
        object_type='appointment', object_id=appointment.id, outcome='success',
        integrity_metadata={
            'data': dados['data'].isoformat(),
            'entrada': dados['entrada'].strftime(FORMATO_HORA),
            'saida': dados['saida'].strftime(FORMATO_HORA),
            'acompanhante': bool(acompanhante),
        },
    )
