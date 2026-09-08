"""Quem pode o quê — a matriz do PRD seção 4 escrita em código.

A matriz existia só em prosa, e o resultado era previsível: papel nenhum
barrava nada fora de mensageria e colaboradores. Uma secretária alcançava
o prontuário, o exame neurológico e a configuração de agenda de qualquer
médico; um gestor também.

O que se declara aqui é **capacidade**, não papel. A tela pergunta "posso
ler prontuário?" em vez de "sou médico?" — porque a resposta a "sou médico"
não é a mesma em toda tela (o dono é `owner` e pode não ser médico; o
médico é médico e não configura a agenda do colega), e porque uma matriz
espalhada como `if 'doctor' in roles` por vinte views é uma matriz que
diverge do PRD na primeira mudança.

Onde o PRD escreve `—`, aqui não há capacidade. Onde escreve "A se
delegado", a capacidade é concedida: delegação não está modelada, e negar
por padrão tiraria da secretária o trabalho que ela de fato faz (marcar,
cadastrar, cobrar). Está anotado em `_ADMINISTRATIVE` para quando o modelo
de delegação existir.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.views import View

from .models import Role


class Capability:
    """Nomes das capacidades. Constantes, não papéis.

    Cada uma corresponde a uma linha da matriz do PRD seção 4.
    """

    #: Ler nota clínica, exame, hipótese, anexo clínico, resumo assistencial.
    #: PRD: `—` para secretaria e gestor, sem exceção.
    READ_CLINICAL = 'read_clinical'

    #: Criar, editar e finalizar atendimento.
    WRITE_CLINICAL = 'write_clinical'

    #: Emitir e assinar documento médico com o próprio certificado.
    ISSUE_DOCUMENT = 'issue_document'

    #: Chat e resumo clínico de IA — segue o prontuário, porque lê o
    #: prontuário. O resumo administrativo é outra coisa e não passa aqui.
    CLINICAL_AI = 'clinical_ai'

    #: Configurar a organização e seus colaboradores: convidar, conceder
    #: papel, revogar vínculo, identidade da clínica.
    MANAGE_ORGANIZATION = 'manage_organization'

    #: Credenciais de provedor — SMS, SMTP, IA. Separada da anterior porque
    #: o gestor administra a operação da clínica sem mexer em quem tem
    #: acesso a ela.
    MANAGE_INTEGRATIONS = 'manage_integrations'

    #: Cadastro e dados demográficos do paciente, contatos, convênio.
    PATIENT_ADMIN = 'patient_admin'

    #: Marcar, remarcar, cancelar, check-in.
    SCHEDULE = 'schedule'

    #: Configurar a grade de disponibilidade. Ter a capacidade não basta:
    #: o médico só configura a **própria** agenda, e isso é verificado por
    #: objeto em `can_configure_agenda_of`.
    CONFIGURE_AVAILABILITY = 'configure_availability'

    #: Financeiro e CRM.
    FINANCE = 'finance'

    #: Indicadores agregados da clínica. A secretaria fica de fora: o que
    #: ela precisa do dia está no balcão, e agregado gerencial não é o
    #: escopo dela.
    MANAGERIAL_DASHBOARD = 'managerial_dashboard'


#: Capacidades administrativas por papel.
#:
#: `SECRETARY` recebe `CONFIGURE_AVAILABILITY` e `FINANCE` porque o PRD as
#: marca "A se delegado" e delegação ainda não é um campo do vínculo.
#: Quando for, estas duas saem daqui e passam a depender da concessão.
_ADMINISTRATIVE = {
    Role.OWNER: frozenset({
        Capability.MANAGE_ORGANIZATION, Capability.MANAGE_INTEGRATIONS,
        Capability.PATIENT_ADMIN, Capability.SCHEDULE,
        Capability.CONFIGURE_AVAILABILITY, Capability.FINANCE,
        Capability.MANAGERIAL_DASHBOARD,
    }),
    Role.MANAGER: frozenset({
        Capability.MANAGE_INTEGRATIONS,
        Capability.PATIENT_ADMIN, Capability.SCHEDULE,
        Capability.CONFIGURE_AVAILABILITY, Capability.FINANCE,
        Capability.MANAGERIAL_DASHBOARD,
    }),
    Role.SECRETARY: frozenset({
        Capability.PATIENT_ADMIN, Capability.SCHEDULE,
        Capability.CONFIGURE_AVAILABILITY, Capability.FINANCE,
    }),
    Role.DOCTOR: frozenset({
        Capability.PATIENT_ADMIN, Capability.SCHEDULE,
        Capability.CONFIGURE_AVAILABILITY, Capability.FINANCE,
        Capability.MANAGERIAL_DASHBOARD,
    }),
}

#: O que só o papel médico abre. Ler é o papel; escrever e assinar exigem
#: também a habilitação profissional verificada — é a diferença entre
#: "consta como médico no vínculo" e "pode assinar uma receita".
_CLINICAL_READ = frozenset({Capability.READ_CLINICAL, Capability.CLINICAL_AI})
_CLINICAL_WRITE = frozenset({Capability.WRITE_CLINICAL, Capability.ISSUE_DOCUMENT})


def capabilities_for(roles, *, clinically_enabled):
    """As capacidades de um vínculo.

    `roles` acumulam: quem é `owner` **e** `doctor` soma as duas colunas —
    é o que o PRD quer dizer com "Só se também médico". Quem é só `owner`
    administra a clínica e não lê prontuário.

    `clinically_enabled` é `Membership.can_practice_clinically()`: papel
    `doctor` mais `PhysicianProfile` verificado. Sem ele o médico lê o que
    é dele, mas não finaliza atendimento nem assina documento — e essa é a
    diferença que impede alguém de se autoconceder capacidade médica só
    marcando um papel.
    """
    roles = set(roles or [])
    granted = set()
    for role in roles:
        granted |= _ADMINISTRATIVE.get(role, frozenset())
    if Role.DOCTOR in roles:
        granted |= _CLINICAL_READ
        if clinically_enabled:
            granted |= _CLINICAL_WRITE
    return frozenset(granted)


class CapabilityRequiredView(LoginRequiredMixin, View):
    """Base das telas de `/app/`: exige tenant resolvido e uma capacidade.

    Cada app mantinha a própria cópia de `TenantScopedView`, e todas as
    cópias faziam a mesma coisa — verificar que existe `access_context` e
    nada mais. Uma base só é o que permite a verificação de capacidade
    entrar em todas de uma vez, e é o que faz uma tela nova nascer
    protegida: `required_capability = None` é uma decisão explícita, não um
    esquecimento.

    A recusa é 404, e não 403, pelo mesmo motivo já adotado em mensageria:
    quem não tem a capacidade não precisa saber que a tela existe. O
    complemento disso é esconder o link — um 404 na cara de quem clicou um
    botão visível é um defeito de navegação, não uma proteção.
    """

    #: Capacidade exigida. `None` quer dizer "qualquer vínculo ativo serve"
    #: — válido para notificações, troca de organização e telas do próprio
    #: usuário, e deliberado em cada caso.
    required_capability = None

    def dispatch(self, request, *args, **kwargs):
        context = request.access_context
        if context is None:
            raise Http404
        if self.required_capability and not context.can(self.required_capability):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def can_configure_agenda_of(context, physician_membership_id):
    """Se este vínculo pode mexer na grade daquele médico.

    A capacidade sozinha não responde: o PRD dá ao médico "própria agenda",
    e um médico que reconfigura a grade do colega apaga horário publicado
    de quem não está olhando. Quem administra a clínica — dono, gestor,
    secretaria — mexe na de qualquer um; o médico, só na dele.
    """
    if context is None or not context.can(Capability.CONFIGURE_AVAILABILITY):
        return False
    administrative = {Role.OWNER, Role.MANAGER, Role.SECRETARY}
    if administrative & set(context.permissions):
        return True
    return str(context.membership_id) == str(physician_membership_id)
