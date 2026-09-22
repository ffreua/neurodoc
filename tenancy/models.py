import re

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from base.models import TenantModel, TimestampedModel
from base.validators import is_valid_cnpj

from .plans import PLANS, PlanCode


SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
RESERVED_SLUGS = {'app', 'admin', 'api', 'static', 'health', 'technical-docs', 'www'}


class Role(models.TextChoices):
    OWNER = 'owner', 'Responsável'
    DOCTOR = 'doctor', 'Médico'
    SECRETARY = 'secretary', 'Secretaria'
    MANAGER = 'manager', 'Gestor'


class TenantStatus(models.TextChoices):
    """Em que pé está a relação comercial com a organização.

    Três estados, porque os dois motivos de desligar uma clínica são
    diferentes e pedem consequências diferentes.

    `SUSPENDED` é a falta de pagamento: a clínica **congela**. Todo mundo
    continua entrando, lendo prontuário, imprimindo e exportando; nada é
    criado nem alterado. É o estado que se desfaz sozinho quando a fatura é
    paga, e é o único compatível com a guarda do prontuário — cortar o
    acesso do médico ao registro dos próprios pacientes por causa de um
    boleto atrasado transformaria uma questão comercial num problema de
    assistência.

    `CLOSED` é a rescisão: ninguém entra mais. O dado **continua no banco**
    — o prontuário tem guarda de vinte anos e não é do sistema decidir
    apagá-lo —, mas a porta fecha, e a tela diz a quem recorrer para pedir
    a exportação.

    Nenhum dos dois apaga nada, nunca. Reativar é trocar o estado de volta.
    """

    ACTIVE = 'active', 'Ativa'
    SUSPENDED = 'suspended', 'Suspensa (somente leitura)'
    CLOSED = 'closed', 'Encerrada'


#: Os estados em que a organização não aceita escrita.
INACTIVE_STATUSES = frozenset({TenantStatus.SUSPENDED, TenantStatus.CLOSED})


class Tenant(TimestampedModel):
    legal_name = models.CharField(max_length=255)
    trade_name = models.CharField(max_length=255, blank=True)
    cnpj = models.CharField(max_length=14, unique=True)
    slug = models.SlugField(max_length=63, unique=True)
    status = models.CharField(max_length=40, choices=TenantStatus.choices, default=TenantStatus.ACTIVE)

    # ------------------------------------------------------------- plano
    #
    # O catálogo vive em `tenancy/plans.py`, em código: um plano é o
    # registro do que foi vendido a alguém, e numa tabela baixar um limite
    # alteraria em silêncio o direito de quem já contratou.
    #
    # O que varia por cliente são os dois *override* abaixo, e não o plano.
    # Nulo significa "usa o plano"; preenchido, vale o valor. É assim que a
    # clínica que negociou 1.200 pacientes continua no Básico em vez de
    # virar um quinto plano — e é assim que a clínica-sede fica irrestrita,
    # como `custom` sem override, e não como uma exceção codificada por
    # e-mail que ninguém vê na tela nem na trilha.
    plan = models.CharField(
        max_length=40, choices=PlanCode.choices, default=PlanCode.FREE,
    )
    patient_limit_override = models.PositiveIntegerField(null=True, blank=True)
    doctor_limit_override = models.PositiveIntegerField(null=True, blank=True)
    #: Por que esta clínica tem o plano e os limites que tem — contrato,
    #: cortesia, piloto. É o que responde à pergunta um ano depois, quando
    #: quem combinou já não lembra e o e-mail se perdeu.
    plan_note = models.CharField(max_length=255, blank=True)

    # ------------------------------------------------- estado comercial
    #
    # Mesma razão do `plan_note`: um estado sem motivo escrito é
    # indistinguível de um erro seis meses depois, e a pergunta que se faz
    # então — "por que esta clínica está suspensa?" — não tem outra fonte.
    #: Por que a organização está no estado em que está. Exigido ao mudar.
    status_note = models.CharField(max_length=255, blank=True)
    #: Quando o estado mudou pela última vez. A trilha guarda o evento
    #: completo; isto existe para a tela poder dizer "suspensa desde"
    #: sem varrer a auditoria a cada linha da listagem.
    status_changed_at = models.DateTimeField(null=True, blank=True)

    timezone = models.CharField(max_length=64, default='America/Sao_Paulo')
    settings = models.JSONField(default=dict, blank=True)

    @property
    def is_active(self):
        return self.status == TenantStatus.ACTIVE

    @property
    def is_read_only(self):
        """Congelada: lê tudo, não escreve nada."""
        return self.status == TenantStatus.SUSPENDED

    @property
    def is_closed(self):
        return self.status == TenantStatus.CLOSED

    def clean(self):
        if not SLUG_RE.fullmatch(self.slug or ''):
            raise ValidationError({'slug': 'Invalid slug format'})
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({'slug': 'Reserved slug'})
        if not is_valid_cnpj(self.cnpj or ''):
            raise ValidationError({'cnpj': 'Invalid CNPJ'})
        if self.plan not in PLANS:
            raise ValidationError({'plan': f'Plano desconhecido: {self.plan}'})

    def __str__(self):
        return self.legal_name


class TenantDomain(TimestampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='domains')
    hostname = models.CharField(max_length=255)
    verified_at = models.DateTimeField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('hostname'), name='tenancy_tenantdomain_hostname_lower_uniq'),
        ]

    def clean(self):
        self.hostname = (self.hostname or '').lower().strip()

    def __str__(self):
        return self.hostname


#: Ha quantos dias, no maximo, pode ter sido a ultima consulta para o
#: paciente ainda pedir pelo portal.
#:
#: Cento e oitenta, e nao "seis meses": a Resolucao CFM n 2.314/2022, art.
#: 6, 2, diz "intervalos nao superiores a 180 dias". Seis meses de
#: calendario dao 181 a 184 dias -- mais permissivo do que o texto que a
#: tela cita, e a diferenca cai justamente sobre quem consultou na
#: fronteira. O numero e o da norma para que a citacao e o comportamento
#: digam a mesma coisa.
PORTAL_RECENT_VISIT_DAYS = 180


class MembershipStatus(models.TextChoices):
    # Os rótulos são o que a tela da equipe mostra a quem administra a
    # clínica. Os valores gravados continuam em inglês, como no resto do
    # esquema — mudar valor de coluna para traduzir rótulo quebraria todo
    # filtro escrito contra eles.
    INVITED = 'invited', 'Convidado'
    ACTIVE = 'active', 'Ativo'
    SUSPENDED = 'suspended', 'Suspenso'
    REVOKED = 'revoked', 'Revogado'


class Membership(TenantModel):
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='memberships')
    roles = ArrayField(models.CharField(max_length=40, choices=Role.choices), default=list, blank=True)
    status = models.CharField(max_length=40, choices=MembershipStatus.choices, default=MembershipStatus.INVITED)
    invited_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    #: A escolha **deste medico** para os pacientes que ele atende. Nulo
    #: herda a da clinica.
    #:
    #: Mora no vinculo, e nao em `PhysicianProfile`, porque
    #: `PhysicianProfile` e do usuario e atravessa clinicas: o CRM e o
    #: mesmo em toda parte, e a decisao de barrar nao precisa ser. Aqui a
    #: configuracao nasce escopada por inquilino, como todo `TenantModel`.
    #:
    #: Tres estados, e por isso `null=True`: sim, nao, e "siga a clinica"
    #: -- este ultimo e o que permite o responsavel mudar o padrao e a
    #: mudanca valer para quem nao se manifestou.
    patient_portal_requires_recent_visit = models.BooleanField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'user'], name='tenancy_membership_tenant_user_uniq'),
        ]

    def has_role(self, role):
        return role in (self.roles or [])

    def is_active(self):
        return self.status == MembershipStatus.ACTIVE

    def can_practice_clinically(self):
        """A granted 'doctor' role is not automatic clinical enablement.

        A verified PhysicianProfile is a separate, explicit gate — owners
        cannot self-serve medical capability just by assigning the role.
        """
        if not self.has_role(Role.DOCTOR):
            return False
        from accounts.models import PhysicianProfile
        profile = PhysicianProfile.objects.filter(user_id=self.user_id).first()
        return bool(profile and profile.verification_status == profile.VerificationStatus.VERIFIED)

    def __str__(self):
        return f'{self.user_id}@{self.tenant_id}'


class ClinicProfile(TenantModel):
    """Identidade da clínica: o que aparece no papel timbrado e na tela.

    Separado de `Tenant` porque as duas coisas respondem a perguntas
    diferentes. `Tenant` é quem a organização é perante o sistema — razão
    social, CNPJ, slug, plano, estado da assinatura —, e mexer nisso é ato
    de cadastro. Isto aqui é como a clínica se apresenta ao paciente:
    endereço que sai na receita, telefone que ele liga, logotipo no
    cabeçalho. Muda quando a clínica muda de sala, e não deveria obrigar a
    tocar na linha que identifica a pessoa jurídica.

    O logotipo é guardado como arquivo em `/data/media`, não como coluna
    binária: é o mesmo caminho dos anexos, fica fora do dump do banco e é
    lido direto do disco na hora de montar o PDF.
    """

    #: Caminho absoluto do arquivo. Guardado, e não derivado do id, porque a
    #: extensão depende do formato enviado e o PDF precisa do arquivo real.
    logo_path = models.CharField(max_length=500, blank=True)
    logo_mime = models.CharField(max_length=100, blank=True)
    logo_bytes = models.PositiveIntegerField(default=0)
    logo_updated_at = models.DateTimeField(null=True, blank=True)

    #: Contato que sai no cabeçalho do documento. O endereço do médico
    #: (`accounts.PhysicianProfile`) continua existindo e é outro: numa
    #: clínica com vários médicos, o consultório é um e os CRMs são vários.
    address_line = models.CharField(max_length=255, blank=True)
    address_district = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=2, blank=True)
    postal_code = models.CharField(max_length=9, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    website = models.URLField(max_length=255, blank=True)

    #: Portal público de solicitações do paciente.
    #:
    #: Desligado por padrão, e por clínica. Ligar publica um endereço que
    #: qualquer pessoa alcança e que aceita CPF e data de nascimento — não
    #: é algo que deva existir para uma clínica que não pediu.
    patient_portal_enabled = models.BooleanField(default=False)
    #: Aviso que a clínica quer exibir no portal: prazo de atendimento,
    #: o que o portal não substitui, orientações da primeira consulta.
    #: Fica com a clínica porque o prazo é dela.
    patient_portal_notice = models.TextField(blank=True)
    #: Barrar quem nao consulta ha mais de `PORTAL_RECENT_VISIT_DAYS`.
    #:
    #: Ligado por padrao: e o que a Resolucao CFM n 2.314/2022 parametriza
    #: e o que o art. 37 do Codigo de Etica Medica sustenta. Desligar e
    #: liberalidade de quem responde pelo ato -- o medico segue podendo
    #: prescrever, so nao pelo portal automaticamente.
    patient_portal_requires_recent_visit = models.BooleanField(default=True)

    #: Encarregado pelo tratamento de dados pessoais (LGPD art. 41).
    #:
    #: A clínica é a **controladora** do prontuário — é ela que decide
    #: atender, o que registrar e por quanto tempo —, e o §1º do art. 41
    #: manda que a identidade e o contato do encarregado sejam divulgados
    #: publicamente. Divulgados de verdade: um paciente que queira exercer
    #: um direito precisa achar para quem escrever sem pedir a ninguém.
    #:
    #: Ficam aqui, e não numa configuração da instalação, porque o
    #: encarregado é de cada clínica. Quem mantém o servidor é operador, e
    #: tem o seu próprio — são duas figuras distintas, e juntá-las num
    #: campo só faria o paciente escrever para quem não pode responder.
    #:
    #: Vazio enquanto a clínica não designar, e a tela do portal diz
    #: exatamente isso em vez de inventar um endereço: prometer um canal
    #: que não existe é pior do que admitir que ele falta.
    dpo_name = models.CharField(max_length=255, blank=True)
    dpo_email = models.EmailField(max_length=254, blank=True)
    dpo_phone = models.CharField(max_length=20, blank=True)

    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant'], name='tenancy_clinicprofile_tenant_uniq'),
        ]

    @property
    def has_logo(self):
        return bool(self.logo_path)

    def address_summary(self):
        """Endereço em uma linha, para o cabeçalho do documento.

        Devolve string vazia quando não há endereço, em vez de uma linha de
        vírgulas soltas: um cabeçalho com ", /" impresso é pior do que um
        cabeçalho sem endereço.
        """
        street = ' — '.join(p for p in [self.address_line, self.address_district] if p)
        place = self.city
        if self.city and self.state:
            place = f'{self.city}/{self.state}'
        return ' — '.join(p for p in [street, place, self.postal_code] if p)

    def __str__(self):
        return f'Identidade de {self.tenant_id}'


class InvitationPurpose(models.TextChoices):
    PLATFORM = 'platform', 'Plataforma'
    COLLABORATOR = 'collaborator', 'Colaborador'


class Invitation(TimestampedModel):
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=40, choices=InvitationPurpose.choices)
    target_tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name='invitations',
    )
    email_binding = models.EmailField(max_length=254, blank=True)
    role_grants = ArrayField(
        models.CharField(max_length=40, choices=Role.choices), default=list, blank=True,
    )
    # ---------------------------------------------------- o que foi vendido
    #
    # O convite de plataforma carrega o plano contratado. Antes, todo
    # convite criava a clínica em `free`, com o plano escrito na linha de
    # `accept_platform_invitation` — quem vendesse o Completo teria de
    # corrigir o plano à mão depois, e ninguém saberia dizer se o cliente
    # está no plano certo sem perguntar a quem vendeu.
    #
    # Vale só para `purpose='platform'`: convite de colaborador entra numa
    # clínica que já tem plano, e mudá-lo pela porta do convite seria uma
    # forma silenciosa de alterar contrato.
    plan = models.CharField(
        max_length=40, choices=PlanCode.choices, default=PlanCode.FREE,
    )
    patient_limit_override = models.PositiveIntegerField(null=True, blank=True)
    doctor_limit_override = models.PositiveIntegerField(null=True, blank=True)
    #: Por que este convite tem o plano que tem. Copiado para o
    #: `plan_note` da organização no aceite, que é onde a pergunta é feita
    #: depois — o convite some da vista assim que é consumido.
    plan_note = models.CharField(max_length=255, blank=True)

    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(purpose='platform') | ~models.Q(target_tenant=None),
                name='tenancy_invitation_collaborator_requires_target_tenant',
            ),
        ]

    def is_usable(self, now):
        return self.consumed_at is None and self.revoked_at is None and self.expires_at > now

    def __str__(self):
        return f'{self.purpose} invitation ({self.id})'


class ClinicMessageKind(models.TextChoices):
    """Por que a clínica está falando com quem mantém o sistema.

    Duas portas, e a diferença não é de formulário: um pedido de ajuda tem
    alguém esperando resposta hoje, e uma sugestão entra numa lista que se
    lê com calma. Misturá-las numa caixa só faz o urgente esperar a vez
    atrás de uma ideia de melhoria — e faz a ideia ser lida com a pressa
    de quem está atendendo um chamado.
    """

    SUPPORT = 'support', 'Fale com a NeuroDoc'
    SUGGESTION = 'suggestion', 'Sugestão de melhoria'


class ClinicMessageStatus(models.TextChoices):
    NEW = 'new', 'Nova'
    READ = 'read', 'Lida'
    ANSWERED = 'answered', 'Respondida'
    ARCHIVED = 'archived', 'Arquivada'


class ClinicMessage(TenantModel):
    """Mensagem de uma clínica para quem mantém a instalação.

    O caminho inverso do `Lead`: aquele é a pré-história de um inquilino,
    este é um inquilino que já existe pedindo alguma coisa. Ficam no mesmo
    app e são lidos no mesmo console, por quem opera o servidor.

    `TenantModel` porque a mensagem **é** de uma clínica: quem a escreveu
    escreveu de dentro de uma, e a resposta volta para ela. O console do
    superadministrador atravessa organizações para ler, como já faz com a
    trilha de auditoria; as telas de `/app/` continuam escopadas.

    **Nunca conteúdo clínico.** A tela diz isso a quem escreve, e é por
    isso que ela não oferece anexar arquivo nem escolher paciente: um
    campo de anexo aqui viraria exame de paciente no console de quem opera
    o servidor, que é exatamente a linha que o produto inteiro não
    atravessa. O que se manda daqui é texto sobre o sistema.
    """

    kind = models.CharField(max_length=20, choices=ClinicMessageKind.choices)
    #: Quem escreveu, pelo vínculo e não pelo usuário: a mesma pessoa pode
    #: ter vínculo em duas clínicas, e o que importa aqui é de qual delas
    #: ela falou.
    author = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='+',
    )
    subject = models.CharField(max_length=140)
    body = models.TextField(max_length=4000)
    status = models.CharField(
        max_length=20, choices=ClinicMessageStatus.choices, default=ClinicMessageStatus.NEW,
    )
    #: Anotação de quem opera o servidor, nunca visível para a clínica.
    #: Existe para o console responder "o que foi feito com isto?" sem
    #: exigir um segundo sistema.
    handling_note = models.CharField(max_length=500, blank=True)
    handled_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    notify_error = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['-created_at'], name='tenancy_clinicmsg_recent_idx'),
            models.Index(fields=['status'], name='tenancy_clinicmsg_status_idx'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()}: {self.subject}'


class ContractAcceptance(TenantModel):
    """O aceite do contrato de adesao, com prova de o que foi aceito.

    Nasce junto com a clinica, na mesma transacao de
    `accept_platform_invitation`: uma organizacao sem aceite registrado
    seria uma clinica usando o sistema sem contrato, e descobrir isso
    depois nao tem conserto -- ninguem volta no tempo para perguntar.

    **Por que guardar o hash do texto.** A versao sozinha nao prova nada:
    se alguem editar `tenancy/contract.py` sem trocar `VERSAO`, todos os
    aceites passados passam a apontar para um texto que ninguem leu.
    Com o SHA-256 do texto gravado no aceite, a divergencia aparece --
    e aparece na tela do console, que e onde alguem olha.

    `TenantModel` porque o aceite **e** da clinica, e um dia ela vai
    querer reler o que assinou. O console do superadministrador atravessa
    organizacoes para ler, como ja faz com as mensagens e com a trilha.
    """

    #: Versao aceita (`tenancy.contract.VERSAO`). Texto novo e versao
    #: nova: nunca se edita uma versao ja aceita -- a clausula 17.6 diz
    #: isso com todas as letras.
    version = models.CharField(max_length=20)
    #: SHA-256 de `contract.texto_simples()` no momento do aceite.
    text_sha256 = models.CharField(max_length=64)
    #: O contrato inteiro, como foi aceito.
    #:
    #: Exigencia da clausula 2.3: "uma copia do conteudo contratual
    #: efetivamente aceito permanecera vinculada ao respectivo registro de
    #: contratacao". So o hash nao cumpre -- ele prova que um texto e
    #: aquele texto, mas nao devolve o texto. E `tenancy/contract.py`
    #: guarda apenas a **versao corrente**: quem aceitou a 1.0 nao tem
    #: onde ler a 1.0 depois de a 2.0 entrar no ar.
    #:
    #: Vinte e cinco mil caracteres por aceite, uma vez por clinica. E
    #: barato para o que compra: a prova documental fica no banco, e nao
    #: numa versao do codigo que alguem teria de recuperar do historico.
    text = models.TextField(blank=True)
    #: O plano contratado, copiado do convite. Fica aqui, e nao so no
    #: `Tenant`, porque o plano da clinica muda e o do contrato assinado
    #: nao: o que se cobrou no primeiro ano e o que esta escrito aqui.
    plan = models.CharField(max_length=40, choices=PlanCode.choices, default=PlanCode.FREE)
    #: O que o plano custava no dia (clausula 2.2, "h": plano **e
    #: condicoes comerciais**). Em centavos, como todo preco do sistema.
    #: Nulo quando nao ha preco de tabela -- o Personalizado, combinado
    #: caso a caso. Zero e o Gratuito, que e um preco e nao uma ausencia.
    price_annual_cents = models.PositiveIntegerField(null=True, blank=True)

    #: A conta que aceitou, enquanto ela existir.
    #:
    #: `SET_NULL`, e nao `PROTECT`. A tentacao e proteger -- e prova de
    #: aceite, e prova nao se apaga. Mas o que prova o aceite sao os dois
    #: campos abaixo, copiados no instante; a chave estrangeira e
    #: conveniencia para abrir a conta a partir do contrato. Com `PROTECT`,
    #: uma conta encerrada ficaria presa para sempre por causa dela, e o
    #: unico jeito de encerrar a conta seria apagar o aceite -- que e
    #: exatamente o que nao pode acontecer.
    accepted_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    #: Nome e e-mail copiados no aceite. Sao **eles** que provam quem
    #: aceitou: a conta pode trocar de e-mail, ser desativada ou sumir, e
    #: quem aceitou naquele dia continua sendo quem esta escrito aqui.
    accepted_name = models.CharField(max_length=255, blank=True)
    accepted_email = models.EmailField(max_length=254)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    #: Declaracao de poderes para contratar (clausula 2.2, "i").
    #:
    #: Campo proprio, e nao embutido na caixa de aceite. Sao duas
    #: declaracoes diferentes -- "li e aceito" e "tenho poderes para
    #: assinar por esta clinica" --, e a segunda e a que se discute quando
    #: alguem alega que quem clicou nao podia ter clicado. Juntas numa
    #: caixa so, nao haveria como mostrar que a pergunta foi feita.
    representation_declared = models.BooleanField(default=False)

    #: Ate quando cabe arrependimento (clausula 9), e quando vence o
    #: periodo contratado (clausula 2). Gravados, e nao calculados na
    #: leitura, porque sao termo de contrato: mudar o prazo de sete dias
    #: amanha nao pode reescrever o prazo de quem assinou ontem.
    withdrawal_deadline = models.DateTimeField()
    expires_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    #: Copia enviada ao contratante. Mesmo padrao do lead e da mensagem:
    #: o aceite e gravado antes de o e-mail sair, e a falha do e-mail fica
    #: registrada em vez de derrubar a criacao da clinica.
    emailed_at = models.DateTimeField(null=True, blank=True)
    email_error = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            # Uma clinica aceita cada versao uma vez. Aceitar a mesma
            # versao duas vezes nao acrescenta nada e faria a tela do
            # console perguntar qual das duas vale.
            models.UniqueConstraint(
                fields=['tenant', 'version'],
                name='tenancy_contract_tenant_version_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['-created_at'], name='tenancy_contrato_recent_idx'),
        ]

    def __str__(self):
        return f'Contrato {self.version} — {self.accepted_email}'


class LeadStatus(models.TextChoices):
    NEW = 'new', 'Novo'
    CONTACTED = 'contacted', 'Contatado'
    CONVERTED = 'converted', 'Convertido'
    DISCARDED = 'discarded', 'Descartado'


class Lead(TimestampedModel):
    """Pedido de contato vindo da pagina publica de vendas.

    Fica em `tenancy` porque um lead e a pre-historia de um inquilino: ele
    vira `Invitation` e depois `Tenant`, e quem o le e quem opera a
    instalacao, no mesmo console. O app `crm` foi removido do produto em
    08/09/2026 (PRD 25.9), e nao se ressuscita um funil inteiro para
    guardar sete campos.

    Herda de `TimestampedModel` e nao de `TenantModel` de proposito: no
    momento em que o pedido chega, a organizacao ainda nao existe -- e
    justamente o que a pessoa esta pedindo.

    Os servicos (limite por IP, aviso por e-mail) ficam em
    `tenancy/leads.py`, como `patients` separa `models.py` de `photo.py`.
    """

    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=32, blank=True)
    clinic_name = models.CharField(max_length=255, blank=True)
    #: Codigo do plano de interesse. `CharField` livre e nao `choices`: o
    #: lead e um retrato do que a pessoa clicou naquele dia, e um plano
    #: aposentado nao pode invalidar um pedido antigo.
    plan = models.CharField(max_length=40, blank=True)
    message = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW)
    #: IP de origem, como no resto do sistema -- serve a investigar abuso,
    #: nao a identificar a pessoa.
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    #: Versao do aviso de privacidade aceita no envio. Demonstrar
    #: consentimento exige saber **a que** se consentiu, e o texto muda.
    privacy_notice_version = models.CharField(max_length=20, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    notify_error = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=['-created_at'], name='tenancy_lead_recent_idx')]

    def __str__(self):
        return f'{self.name} <{self.email}>'
