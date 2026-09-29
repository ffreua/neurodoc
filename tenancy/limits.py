"""Quanto a clínica já usa do plano, e o que acontece quando enche.

Um lugar só decide isto. Os limites são lidos em seis pontos do produto —
dois que criam paciente, quatro que concedem papel médico — e a pergunta
"esta clínica ainda cabe?" respondida de seis jeitos diferentes é como
cinco deles concordam e o sexto deixa passar.

## O que conta

**Pacientes ativos**, não todos os já cadastrados: arquivar libera vaga.
É coerente com o resto do produto, onde arquivar já tira o paciente da
carteira ativa e dos indicadores, e não pune quem mantém o cadastro limpo.

**Vínculos ativos com papel médico**, não convites emitidos nem vínculos
suspensos. Suspender serve a férias e afastamento: cobrar a vaga de quem
está afastado obrigaria a clínica a revogar o vínculo — que apaga a
trilha de quem fez o quê — só para caber no plano.

## Rebaixar congela, não apaga

Uma clínica com 700 pacientes que vai para um plano de 500 mantém os 700
acessíveis, com o prontuário intacto; o que o sistema recusa é o 701º.
Apagar ou esconder prontuário por questão comercial é o que não se faz em
sistema de saúde, e a Lei 13.787/2018 fixa vinte anos de guarda, que não
conhece plano de assinatura. Por isso `assert_can_add_*` pergunta sobre o
**próximo** registro, e nunca sobre os que já existem.
"""

from dataclasses import dataclass

from .plans import max_doctors, max_patients, plan_label

#: A partir de quanto da cota a tela avisa. O bloqueio não pode ser a
#: primeira notícia: quem descobre o limite com o paciente no balcão não
#: tem o que fazer naquele momento.
WARNING_RATIO = 0.8


class PlanLimitReached(Exception):
    """O limite do plano foi atingido.

    Carrega os números em vez de só uma frase pronta porque quem mostra na
    tela precisa deles separados — e porque uma mensagem escrita em cada
    chamador divergiria da dos outros no primeiro ajuste de texto.
    """

    def __init__(self, resource, usage, limit, plan_label_text):
        self.resource = resource
        self.usage = usage
        self.limit = limit
        self.plan_label = plan_label_text
        super().__init__(self.message())

    def message(self):
        nome = 'pacientes' if self.resource == 'patients' else 'médicos'
        return (
            f'O plano {self.plan_label} permite até {self.limit} {nome}, e a clínica '
            f'já tem {self.usage}. Para ampliar, fale com contato@neurodoc.app.br. '
            'Nada do que já está cadastrado foi alterado.'
        )


@dataclass(frozen=True)
class LimitStatus:
    """Uso de um recurso contra o limite, pronto para a tela."""

    resource: str
    usage: int
    limit: int | None
    plan_label: str

    @property
    def unlimited(self):
        return self.limit is None

    @property
    def ratio(self):
        """Fração usada, de 0 a 1. Ilimitado é sempre 0 — nunca se enche."""
        if self.unlimited or self.limit == 0:
            return 0.0
        return min(self.usage / self.limit, 1.0)

    @property
    def percent(self):
        return int(round(self.ratio * 100))

    @property
    def blocked(self):
        """Sem vaga para o próximo."""
        return not self.unlimited and self.usage >= self.limit

    @property
    def warning(self):
        """Perto do fim, mas ainda cabe. Bloqueado não é aviso: é bloqueio."""
        return not self.unlimited and not self.blocked and self.ratio >= WARNING_RATIO

    @property
    def remaining(self):
        if self.unlimited:
            return None
        return max(self.limit - self.usage, 0)


def resolve_tenant(tenant_or_id):
    """Aceita o objeto `Tenant` ou só o id, e devolve o objeto.

    As views de `/app/` carregam `tenant_id` no `AccessContext` e não a
    organização; os serviços que rodam fora de requisição costumam ter o
    objeto. Sem isto, cada um dos seis pontos de verificação faria a sua
    própria busca — e o que se repete em seis lugares diverge em um.
    """
    from .models import Tenant

    if isinstance(tenant_or_id, Tenant):
        return tenant_or_id
    return Tenant.objects.get(id=tenant_or_id)


def _resolve(override, from_plan):
    """Override vence o plano; nulo cai no plano.

    Zero é um override legítimo — uma clínica suspensa comercialmente que
    não deve cadastrar mais ninguém —, e por isso o teste é contra `None`
    e não pela verdade do valor. `if override:` trataria 0 como ausente e
    devolveria o limite do plano, que é o oposto do que se pediu.
    """
    return from_plan if override is None else override


def granted_limits(plan, patient_override=None, doctor_override=None):
    """Os limites que esta combinação concede, como (pacientes, médicos).

    Serve a quem ainda não tem organização: o convite, que promete um
    plano antes de a clínica existir, e a tela que mostra o que ele
    promete. A mesma resolução de `patient_limit`/`doctor_limit`, para o
    que o convite anuncia e o que a organização recebe não divergirem.
    """
    return (
        _resolve(patient_override, max_patients(plan)),
        _resolve(doctor_override, max_doctors(plan)),
    )


def describe_limit(value):
    """"ilimitado" ou o número, para a tela não repetir esse `if`."""
    return 'ilimitado' if value is None else str(value)


def patient_limit(tenant):
    tenant = resolve_tenant(tenant)
    return _resolve(tenant.patient_limit_override, max_patients(tenant.plan))


def doctor_limit(tenant):
    tenant = resolve_tenant(tenant)
    return _resolve(tenant.doctor_limit_override, max_doctors(tenant.plan))


def patient_usage(tenant):
    from patients.models import Patient, PatientStatus, RegistrationStage

    tenant = resolve_tenant(tenant)
    return Patient.objects.filter(
        tenant_id=tenant.id, status=PatientStatus.ACTIVE,
        registration_stage=RegistrationStage.COMPLETE,
    ).count()


def doctor_usage(tenant):
    from .models import Membership, MembershipStatus, Role

    tenant = resolve_tenant(tenant)
    return Membership.objects.filter(
        tenant_id=tenant.id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).count()


def patient_status(tenant):
    tenant = resolve_tenant(tenant)
    return LimitStatus('patients', patient_usage(tenant), patient_limit(tenant), plan_label(tenant.plan))


def doctor_status(tenant):
    tenant = resolve_tenant(tenant)
    return LimitStatus('doctors', doctor_usage(tenant), doctor_limit(tenant), plan_label(tenant.plan))


def assert_can_add_patient(tenant):
    """Levanta `PlanLimitReached` se não há vaga para mais um paciente."""
    status = patient_status(tenant)
    if status.blocked:
        raise PlanLimitReached('patients', status.usage, status.limit, status.plan_label)


def assert_can_add_doctor(tenant, extra=1):
    """Levanta `PlanLimitReached` se não há vaga para mais `extra` médicos.

    `extra` existe para o convite de colaborador: ele é conferido na
    emissão, quando o médico ainda não entrou, e de novo no aceite. Sem a
    conferência na emissão, o convidado descobriria o problema depois de
    clicar no link — e quem pode resolvê-lo é o dono da clínica, não ele.
    """
    status = doctor_status(tenant)
    if status.unlimited:
        return
    if status.usage + extra > status.limit:
        raise PlanLimitReached('doctors', status.usage, status.limit, status.plan_label)
