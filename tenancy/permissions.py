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

    #: Convênios e planos de saúde da clínica. Separada de `FINANCE`
    #: porque são coisas de altura diferente: lançar um recebimento é
    #: operação do dia, e criar um convênio muda o cadastro que todo
    #: paciente novo passa a escolher e a que toda tabela de honorário se
    #: refere. Quem faz a primeira não faz necessariamente a segunda.
    MANAGE_HEALTH_PLANS = 'manage_health_plans'

    #: Tabela de honorários — o valor da consulta e do procedimento.
    #:
    #: Inclui o médico, e essa é a razão de não ser `MANAGE_HEALTH_PLANS`:
    #: quem define quanto custa a própria consulta é quem a realiza. Ter a
    #: capacidade não basta — o médico só mexe na regra que é dele, e isso
    #: é verificado por objeto em `can_set_fee_for`.
    MANAGE_FEES = 'manage_fees'

    #: Indicadores agregados da clínica. A secretaria fica de fora: o que
    #: ela precisa do dia está no balcão, e agregado gerencial não é o
    #: escopo dela.
    MANAGERIAL_DASHBOARD = 'managerial_dashboard'

    #: Faturamento TISS (1.30): ver guias, lotes e arquivos gerados.
    #: Nenhuma das capacidades TISS implica `READ_CLINICAL` — a guia leva o
    #: mínimo de faturamento, e CID ou indicação clínica, quando a guia
    #: pede, vêm preenchidos pelo médico. Ver `docs/tiss/REVISAO_SPRINT1.md`.
    TISS_VIEW = 'tiss_view'

    #: Criar e editar guia em rascunho, lançar os procedimentos realizados.
    TISS_PREPARE = 'tiss_prepare'

    #: Validar e fechar a guia — o fechamento congela o conteúdo — e montar
    #: o lote.
    TISS_CLOSE = 'tiss_close'

    #: Gerar e baixar o XML, registrar protocolo e resultado do envio.
    TISS_EXPORT = 'tiss_export'

    #: Prestador, credenciamento por operadora, versão do padrão e ciclo de
    #: fechamento. É o que muda **todas** as guias seguintes, por isso fica
    #: com quem já administra convênios (`MANAGE_HEALTH_PLANS`).
    TISS_CONFIGURE = 'tiss_configure'


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
        Capability.MANAGE_HEALTH_PLANS, Capability.MANAGE_FEES,
        Capability.MANAGERIAL_DASHBOARD,
    }),
    Role.MANAGER: frozenset({
        Capability.MANAGE_INTEGRATIONS,
        Capability.PATIENT_ADMIN, Capability.SCHEDULE,
        Capability.CONFIGURE_AVAILABILITY, Capability.FINANCE,
        Capability.MANAGE_HEALTH_PLANS, Capability.MANAGE_FEES,
        Capability.MANAGERIAL_DASHBOARD,
    }),
    Role.SECRETARY: frozenset({
        Capability.PATIENT_ADMIN, Capability.SCHEDULE,
        Capability.CONFIGURE_AVAILABILITY, Capability.FINANCE,
    }),
    Role.DOCTOR: frozenset({
        Capability.PATIENT_ADMIN, Capability.SCHEDULE,
        Capability.CONFIGURE_AVAILABILITY, Capability.FINANCE,
        Capability.MANAGE_FEES,
        Capability.MANAGERIAL_DASHBOARD,
    }),
}

#: O faturamento TISS por papel, decidido em 30/10/2026: a secretária
#: prepara, fecha e exporta — é quem fatura no consultório —, mas não
#: configura; o médico faz tudo menos configurar. Só vale quando a clínica
#: contratou e foi liberada (`tiss_contracted`).
_TISS = {
    Role.OWNER: frozenset({
        Capability.TISS_VIEW, Capability.TISS_PREPARE, Capability.TISS_CLOSE,
        Capability.TISS_EXPORT, Capability.TISS_CONFIGURE,
    }),
    Role.MANAGER: frozenset({
        Capability.TISS_VIEW, Capability.TISS_PREPARE, Capability.TISS_CLOSE,
        Capability.TISS_EXPORT, Capability.TISS_CONFIGURE,
    }),
    Role.SECRETARY: frozenset({
        Capability.TISS_VIEW, Capability.TISS_PREPARE, Capability.TISS_CLOSE,
        Capability.TISS_EXPORT,
    }),
    Role.DOCTOR: frozenset({
        Capability.TISS_VIEW, Capability.TISS_PREPARE, Capability.TISS_CLOSE,
        Capability.TISS_EXPORT,
    }),
}

#: O que só o papel médico abre. Ler é o papel; escrever e assinar exigem
#: também a habilitação profissional verificada — é a diferença entre
#: "consta como médico no vínculo" e "pode assinar uma receita".
_CLINICAL_READ = frozenset({Capability.READ_CLINICAL, Capability.CLINICAL_AI})
_CLINICAL_WRITE = frozenset({Capability.WRITE_CLINICAL, Capability.ISSUE_DOCUMENT})


def capabilities_for(roles, *, clinically_enabled, ai_contracted, tiss_contracted=False):
    """As capacidades de um vínculo.

    `roles` acumulam: quem é `owner` **e** `doctor` soma as duas colunas —
    é o que o PRD quer dizer com "Só se também médico". Quem é só `owner`
    administra a clínica e não lê prontuário.

    `clinically_enabled` é `Membership.can_practice_clinically()`: papel
    `doctor` mais `PhysicianProfile` verificado. Sem ele o médico lê o que
    é dele, mas não finaliza atendimento nem assina documento — e essa é a
    diferença que impede alguém de se autoconceder capacidade médica só
    marcando um papel.

    `ai_contracted` é `plans.has_clinical_ai(tenant.plan)`: o plano da
    clínica inclui a IA. É a única entrada aqui que não vem do vínculo, e
    por isso é **veto**, aplicado depois dos papéis — nenhuma combinação
    de papel devolve `CLINICAL_AI` numa clínica que não a contratou.

    Os três argumentos são obrigatórios e nomeados de propósito. Um
    `ai_contracted=True` por padrão manteria todo chamador existente
    compilando e nenhum deles cobrando o plano, que é o defeito que não
    aparece em teste nenhum: a tela abre, a IA responde e a fatura é de
    quem hospeda. Quem acrescenta uma chamada decide.

    Cuidado com o nome: **não é** `settings.AI_ENABLED`. Aquele é o
    interruptor da instalação inteira; este é o contrato de uma clínica.

    `tiss_contracted` é o plano com TISS **e** a clínica liberada
    (`tenancy.context.tiss_contratado`). Ao contrário de `ai_contracted`, tem
    padrão — e o padrão é `False`: o argumento só **concede**, então quem
    não o passa (a IA, os avisos) fica sem as capacidades TISS, que é a
    direção segura. O padrão perigoso que o parágrafo acima recusa é o que
    concede por omissão.
    """
    roles = set(roles or [])
    granted = set()
    for role in roles:
        granted |= _ADMINISTRATIVE.get(role, frozenset())
        if tiss_contracted:
            granted |= _TISS.get(role, frozenset())
    if Role.DOCTOR in roles:
        granted |= _CLINICAL_READ
        if clinically_enabled:
            granted |= _CLINICAL_WRITE
    if not ai_contracted:
        granted.discard(Capability.CLINICAL_AI)
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


def can_set_fee_for(context, physician_membership_id):
    """Se este vínculo pode criar ou encerrar honorário daquele médico.

    Mesma forma de `can_configure_agenda_of`, e pelo mesmo motivo: a
    capacidade responde "mexe em tabela de honorário?", e não "na de
    quem?". Quem administra a clínica — dono e gestor — define o preço de
    qualquer um, inclusive a regra geral que vale para todos
    (`physician_membership_id` nulo). O médico define o dele.

    Um médico que altera o valor da consulta do colega muda o que a clínica
    fatura por um atendimento que não é dele, e o colega descobre no
    fechamento do mês.
    """
    if context is None or not context.can(Capability.MANAGE_FEES):
        return False
    administrative = {Role.OWNER, Role.MANAGER}
    if administrative & set(context.permissions):
        return True
    if physician_membership_id is None:
        # Regra geral, que vale para a clínica inteira: é decisão de quem
        # administra, não de um dos médicos.
        return False
    return str(context.membership_id) == str(physician_membership_id)
