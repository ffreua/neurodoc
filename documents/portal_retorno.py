"""Quando a última consulta é antiga demais para um pedido pelo portal.

O portal recebe pedido de receita, relatório médico e exame — os três são
ato médico. Duas normas do CFM sustentam a recusa, e elas se encaixam:

- **Código de Ética Médica** (Resolução CFM nº 2.217/2018), art. 37: é
  vedado ao médico "prescrever tratamento ou outros procedimentos sem
  exame direto do paciente, salvo em casos de urgência ou emergência e
  impossibilidade comprovada de realizá-lo, devendo, nesse caso, fazê-lo
  imediatamente após cessar o impedimento". O parágrafo único remete o
  atendimento a distância à regulamentação do CFM.
- **Resolução CFM nº 2.314/2022**, art. 6º, § 2º — a regulamentação que o
  parágrafo único anuncia: no acompanhamento de doenças crônicas ou que
  requeiram acompanhamento por longo tempo "deve ser realizada consulta
  presencial, com o médico assistente do paciente, em intervalos não
  superiores a 180 dias".

**O prazo é o da norma, e só ele.** Não há prazo configurável: oferecer
nove ou dezoito meses faria a tela citar uma resolução que diz 180 dias
logo acima do prazo que a contraria — e o paciente lê as duas coisas na
mesma folha. O que a clínica e o médico escolhem é **barrar ou não**.

**Barrar é o padrão; não barrar é liberalidade de quem responde pelo
ato.** Desligar não impede ninguém de prescrever: o médico continua
podendo emitir a receita quando entender que deve. O que muda é o portal
deixar de decidir sozinho por ele.

**Confere em três portas** — identificação, abertura do formulário e
envio. Na identificação porque é onde a pessoa ainda não investiu tempo;
no envio porque entre uma coisa e outra cabe o médico mudar a opção, e
uma sessão aberta antes não vale como autorização depois.
"""

from tenancy.models import PORTAL_RECENT_VISIT_DAYS


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


def barra(clinic, encontro):
    """Esta clínica barra consulta antiga, para este paciente?

    A escolha do médico que o atendeu vence a da clínica: foi ele quem viu
    o caso, e é dele a responsabilidade do art. 37. `None` no vínculo
    significa "siga a clínica" — é o que permite o responsável mudar o
    padrão e a mudança valer para quem não se manifestou.
    """
    do_medico = getattr(
        getattr(encontro, 'physician_membership', None),
        'patient_portal_requires_recent_visit', None,
    )
    if do_medico is not None:
        return bool(do_medico)
    da_clinica = getattr(clinic, 'patient_portal_requires_recent_visit', None)
    return True if da_clinica is None else bool(da_clinica)


class Bloqueio:
    """Por que este paciente não pode pedir agora, em linguagem de tela.

    Classe, e não dicionário, para que a ausência de bloqueio seja `None` e
    não um dicionário com uma chave `bloqueado: False` que algum template
    vai esquecer de olhar.
    """

    dias = PORTAL_RECENT_VISIT_DAYS

    def __init__(self, ultima=None, medico=''):
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
    if not barra(clinic, encontro):
        return None
    if encontro is None:
        return Bloqueio()

    idade = (agora - encontro.occurred_at).days
    if idade <= PORTAL_RECENT_VISIT_DAYS:
        return None

    profissional = getattr(encontro.physician_membership, 'user', None)
    nome = ''
    if profissional is not None:
        perfil = getattr(profissional, 'physician_profile', None)
        nome = getattr(perfil, 'professional_name', '') or profissional.get_full_name()
    return Bloqueio(ultima=timezone.localtime(encontro.occurred_at), medico=nome)
