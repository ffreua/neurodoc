"""Quando a última consulta é antiga demais para um pedido pelo portal.

O portal recebe pedido de receita, relatório médico e exame — os três são
ato médico. O art. 37 do Código de Ética Médica (Resolução CFM nº
2.217/2018) veda ao médico "prescrever tratamento ou outros procedimentos
sem exame direto do paciente, salvo em casos de urgência ou emergência e
impossibilidade comprovada de realizá-lo". Um portal que aceita pedido de
quem não é visto há anos empurra o médico para essa vedação — e a decisão
de recusar acaba caindo sobre ele, um a um, depois de o paciente já ter
criado expectativa.

**O CFM não fixa um número de meses.** Quem fixa é quem atende. Este
módulo só aplica o intervalo que a clínica ou o médico escolheram, e a
tela diz as duas coisas separadamente: a norma que existe, e o prazo que
é da clínica.

**Bloqueia na identificação, e confere de novo no envio.** Na
identificação porque é onde a pessoa ainda não investiu tempo — descobrir
a recusa depois de descrever cinco medicamentos é pior do que descobrir
antes. No envio porque entre uma coisa e outra cabe o médico apertar a
janela, e a sessão aberta antes não pode valer como autorização depois.
"""

from tenancy.models import PORTAL_REQUEST_WINDOW_DEFAULT


def _somar_meses(momento, meses):
    """A mesma data, `meses` adiante. Sem biblioteca e sem 30 dias.

    Trinta dias vezes seis dá 180, e seis meses civis dão entre 181 e 184
    — a diferença é de dias, e cai justamente sobre quem consultou na
    fronteira. Meses de calendário é o que a clínica quis dizer quando
    escolheu "6 meses", e é o que o paciente entende ao ler a tela.

    Dia que não existe no mês de destino cai no último dia dele: 31 de
    janeiro mais um mês é 28 de fevereiro, e não 3 de março.
    """
    import calendar

    total = momento.month - 1 + meses
    ano = momento.year + total // 12
    mes = total % 12 + 1
    dia = min(momento.day, calendar.monthrange(ano, mes)[1])
    return momento.replace(year=ano, month=mes, day=dia)


def ultima_consulta(patient):
    """O atendimento mais recente do paciente, e quem o conduziu.

    Conta **qualquer** atendimento, e não só o finalizado. Um atendimento
    em rascunho significa que o médico abriu a ficha durante a visita: a
    consulta aconteceu, e o que falta é a nota ser fechada. Exigir o
    finalizado bloquearia o paciente visto na semana passada porque o
    médico ainda não terminou de escrever — recusar quem acabou de ser
    atendido é o erro caro aqui, e deixar passar um pedido a mais não é:
    o portal produz **pedido**, que o médico revisa antes de emitir.
    """
    from clinical.models import Encounter

    return (
        Encounter.objects
        .filter(tenant_id=patient.tenant_id, patient=patient)
        .select_related('physician_membership')
        .order_by('-occurred_at')
        .first()
    )


def janela_em_meses(clinic, encontro):
    """Quantos meses valem para este paciente.

    A do médico que o atendeu vence a da clínica: foi ele quem viu o caso,
    e é dele a responsabilidade do art. 37. Nulo no vínculo significa
    "siga a clínica" — é o que permite o responsável mudar o padrão e a
    mudança valer para quem não se manifestou.
    """
    do_medico = getattr(
        getattr(encontro, 'physician_membership', None), 'patient_portal_max_months', None,
    )
    if do_medico:
        return int(do_medico)
    da_clinica = getattr(clinic, 'patient_portal_max_months', None)
    return int(da_clinica or PORTAL_REQUEST_WINDOW_DEFAULT)


class Bloqueio:
    """Por que este paciente não pode pedir agora, em linguagem de tela.

    Classe, e não dicionário, para que a ausência de bloqueio seja `None` e
    não um dicionário com uma chave `bloqueado: False` que algum template
    vai esquecer de olhar.
    """

    def __init__(self, meses, ultima=None, medico=''):
        self.meses = meses
        #: `None` quando não há consulta nenhuma registrada. São dois casos
        #: diferentes na tela: "faz tempo demais" e "ainda não te vimos".
        self.ultima = ultima
        self.medico = medico

    @property
    def nunca_consultou(self):
        return self.ultima is None


def bloqueio(clinic, patient, agora=None):
    """`None` se o paciente pode pedir; um `Bloqueio` se não pode."""
    from django.utils import timezone

    agora = agora or timezone.now()
    encontro = ultima_consulta(patient)
    meses = janela_em_meses(clinic, encontro)

    if encontro is None:
        return Bloqueio(meses)

    limite = _somar_meses(timezone.localtime(encontro.occurred_at), meses)
    if timezone.localtime(agora) <= limite:
        return None

    profissional = getattr(encontro.physician_membership, 'user', None)
    nome = ''
    if profissional is not None:
        perfil = getattr(profissional, 'physician_profile', None)
        nome = getattr(perfil, 'professional_name', '') or profissional.get_full_name()
    return Bloqueio(meses, ultima=timezone.localtime(encontro.occurred_at), medico=nome)
