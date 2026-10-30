"""Faturamento TISS: a fundação (Sprint 1, versão 1.30).

O desenho, as premissas conferidas e o que ficou para as sprints seguintes
estão em `docs/tiss/REVISAO_SPRINT1.md`. Três regras atravessam o app:

- **Tudo é da clínica.** Todo modelo operacional é `TenantModel`, e toda
  relação interna nasce com chave estrangeira composta `(tenant_id, fk)`
  (`base/db.py::composite_tenant_foreign_key`) — o banco recusa a linha que
  aponta para objeto de outra clínica, mesmo com bug na aplicação.
- **Nada aqui é obrigatório para quem não fatura convênio.** O módulo é um
  a mais: consulta, check-in, receita e cobrança particular não dependem de
  nada deste app.
- **Os campos são semanticamente distintos.** Código do prestador na
  operadora, CNPJ/CPF, registro ANS, carteira, CNES, número da guia e senha
  de autorização são coisas diferentes, guardadas como texto — zero à
  esquerda preservado, sem máscara numérica.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel, TimestampedModel

from . import versoes
from .validators import cnes_valido, cnpj_valido, normalizar_cnpj


class Configuracao(TimestampedModel):
    """A chave do TISS na instalação inteira — uma linha só.

    É o freio de emergência: desligada, nenhuma tela do TISS abre e nenhuma
    tarefa gera arquivo, em clínica nenhuma, sem deploy. As outras duas
    chaves são o plano (`tenancy.plans.has_tiss`) e a liberação por clínica
    (`Tenant.tiss_liberado`). Nasce desligada.
    """

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    ativo = models.BooleanField('faturamento TISS ligado', default=False)

    class Meta:
        verbose_name = 'configuração do TISS'
        verbose_name_plural = 'configuração do TISS'

    @classmethod
    def carregar(cls):
        return cls.objects.get_or_create(singleton=True)[0]


class TipoPessoa(models.TextChoices):
    JURIDICA = 'pj', 'Pessoa jurídica (CNPJ)'
    FISICA = 'pf', 'Pessoa física (CPF)'


class Prestador(TenantModel):
    """Quem fatura: o contratado da operadora. Uma clínica pode ter mais de um.

    O caso comum é a PJ da clínica; o médico que é credenciado como pessoa
    física é outro prestador, com o próprio CPF. Não é o `Tenant`: a
    identidade contratual da clínica no NeuroDoc (razão social e CNPJ do
    contrato de adesão) não muda por causa de um credenciamento.
    """

    nome = models.CharField('nome do contratado', max_length=150)
    tipo_pessoa = models.CharField(max_length=2, choices=TipoPessoa.choices, default=TipoPessoa.JURIDICA)
    cnpj = models.CharField('CNPJ', max_length=14, blank=True)
    cpf = models.CharField('CPF', max_length=11, blank=True)
    #: Sete dígitos. Vazio = "não tem"; a guia leva 9999999, como a ANS manda.
    cnes = models.CharField('CNES', max_length=7, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        verbose_name = 'prestador'
        verbose_name_plural = 'prestadores'

    def __str__(self):
        return self.nome

    def clean(self):
        from base.validators import is_valid_cpf

        self.cnpj = normalizar_cnpj(self.cnpj)
        self.cpf = ''.join(c for c in (self.cpf or '') if c.isdigit())
        self.cnes = (self.cnes or '').strip()
        erros = {}
        if self.tipo_pessoa == TipoPessoa.JURIDICA:
            if not cnpj_valido(self.cnpj):
                erros['cnpj'] = 'CNPJ inválido. Confira os quatorze caracteres.'
            self.cpf = ''
        else:
            if not is_valid_cpf(self.cpf):
                erros['cpf'] = 'CPF inválido. Confira os onze dígitos.'
            self.cnpj = ''
        if self.cnes and not cnes_valido(self.cnes):
            erros['cnes'] = 'O CNES tem sete dígitos. Deixe em branco se o prestador não tiver.'
        if erros:
            raise ValidationError(erros)

    @property
    def documento(self):
        return self.cnpj if self.tipo_pessoa == TipoPessoa.JURIDICA else self.cpf


class IdentificacaoNaOperadora(models.TextChoices):
    """Como o prestador se identifica no XML — o `choice` de `ct_contratadoDados`."""

    CODIGO = 'codigo', 'Código do prestador na operadora'
    CNPJ = 'cnpj', 'CNPJ'
    CPF = 'cpf', 'CPF'


class CicloFechamento(models.TextChoices):
    MENSAL = 'mensal', 'Do dia 1º ao último dia do mês'
    QUINZE = 'dia15', 'Do dia 15 ao dia 14 do mês seguinte'
    MANUAL = 'manual', 'Período escolhido a cada lote'


class CanalEnvio(models.TextChoices):
    XML_PORTAL = 'xml_portal', 'XML enviado pelo portal da operadora'
    MANUAL = 'manual', 'Digitação manual no portal da operadora'


class Credenciamento(TenantModel):
    """Prestador × operadora: o contrato que define como a guia é escrita.

    A versão do padrão mora aqui, e não na operadora, porque é **acordada**
    entre as partes (Componente Organizacional §206) — dois prestadores da
    mesma clínica podem ter versões diferentes com a mesma operadora.

    Para versão **histórica** (3.x), o XML de cobrança só sai com o aceite
    declarado: quem, quando e por quê. Ver `tiss/versoes.py`.
    """

    prestador = models.ForeignKey(Prestador, on_delete=models.PROTECT, related_name='credenciamentos')
    operadora = models.ForeignKey('patients.Insurer', on_delete=models.PROTECT, related_name='+')
    #: `st_texto14` no XSD. Texto: a operadora pode usar zero à esquerda.
    codigo_na_operadora = models.CharField('código do prestador na operadora', max_length=14, blank=True)
    identificacao = models.CharField(
        'identificação no XML', max_length=10,
        choices=IdentificacaoNaOperadora.choices, default=IdentificacaoNaOperadora.CODIGO,
    )
    versao = models.CharField('versão do padrão TISS', max_length=10, default=versoes.VERSAO_ATUAL)
    aceite_versao_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    aceite_versao_em = models.DateTimeField(null=True, blank=True)
    aceite_versao_motivo = models.CharField(max_length=255, blank=True)
    ciclo = models.CharField(max_length=10, choices=CicloFechamento.choices, default=CicloFechamento.MENSAL)
    canal = models.CharField(max_length=12, choices=CanalEnvio.choices, default=CanalEnvio.XML_PORTAL)
    #: Limite de guias por lote se a operadora pedir menos que os 100 da ANS.
    limite_guias_por_lote = models.PositiveSmallIntegerField(null=True, blank=True)
    portal_url = models.URLField('endereço do portal', max_length=500, blank=True)
    instrucoes = models.TextField('instruções de envio', max_length=4000, blank=True)
    vigencia_inicio = models.DateField('início do credenciamento', null=True, blank=True)
    vigencia_fim = models.DateField('fim do credenciamento', null=True, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        verbose_name = 'credenciamento'
        verbose_name_plural = 'credenciamentos'
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'prestador', 'operadora'],
                condition=models.Q(ativo=True),
                name='tiss_credenciamento_ativo_uniq',
            ),
            models.CheckConstraint(
                condition=models.Q(limite_guias_por_lote__isnull=True)
                | models.Q(limite_guias_por_lote__gte=1, limite_guias_por_lote__lte=100),
                name='tiss_credenciamento_limite_lote',
            ),
        ]

    def __str__(self):
        return f'{self.prestador} — {self.operadora}'

    def clean(self):
        from .validators import registro_ans_valido

        erros = {}
        try:
            v = versoes.versao(self.versao)
            self.versao = v.codigo
        except versoes.VersaoDesconhecida:
            erros['versao'] = 'Versão do padrão TISS desconhecida.'
            v = None
        self.codigo_na_operadora = (self.codigo_na_operadora or '').strip()
        if self.identificacao == IdentificacaoNaOperadora.CODIGO and not self.codigo_na_operadora:
            erros['codigo_na_operadora'] = 'Informe o código que a operadora deu ao prestador.'
        if self.prestador_id:
            pessoa = self.prestador.tipo_pessoa
            if self.identificacao == IdentificacaoNaOperadora.CNPJ and pessoa != TipoPessoa.JURIDICA:
                erros['identificacao'] = 'Prestador pessoa física não se identifica por CNPJ.'
            if self.identificacao == IdentificacaoNaOperadora.CPF and pessoa != TipoPessoa.FISICA:
                erros['identificacao'] = 'Prestador pessoa jurídica não se identifica por CPF.'
            if (v and self.identificacao == IdentificacaoNaOperadora.CNPJ
                    and v.codigo != '4.03.00' and any(c.isalpha() for c in self.prestador.cnpj)):
                erros['versao'] = 'CNPJ com letras só é aceito a partir da versão 4.03.00.'
        if self.operadora_id and not registro_ans_valido(self.operadora.ans_registration):
            erros['operadora'] = (
                'A operadora precisa do registro ANS com seis dígitos (cadastro de convênios) '
                'antes de ser credenciada.'
            )
        if self.vigencia_inicio and self.vigencia_fim and self.vigencia_fim < self.vigencia_inicio:
            erros['vigencia_fim'] = 'O fim não pode ser antes do início.'
        if erros:
            raise ValidationError(erros)

    @property
    def versao_obj(self):
        return versoes.versao(self.versao)

    @property
    def aceite_declarado(self):
        return bool(self.aceite_versao_em and self.aceite_versao_motivo)

    @property
    def exporta_para_cobranca(self):
        """XML de cobrança: versão vigente na ANS, ou histórica com aceite declarado."""
        v = self.versao_obj
        return v.vigente_ans or self.aceite_declarado


class Conselho(models.TextChoices):
    """TUSS Tabela 26 (versão 202609), os códigos que vão no XML."""

    CRESS = '01', 'CRESS — Serviço Social'
    COREN = '02', 'COREN — Enfermagem'
    CRF = '03', 'CRF — Farmácia'
    CREFONO = '04', 'CREFONO — Fonoaudiologia'
    CREFITO = '05', 'CREFITO — Fisioterapia e Terapia Ocupacional'
    CRM = '06', 'CRM — Medicina'
    CRN = '07', 'CRN — Nutrição'
    CRO = '08', 'CRO — Odontologia'
    CRP = '09', 'CRP — Psicologia'
    OUTROS = '10', 'Outros conselhos'
    CRBIO = '11', 'CRBio — Biologia'
    CRBM = '12', 'CRBM — Biomedicina'
    CREF = '13', 'CREF — Educação Física'
    CRMV = '14', 'CRMV — Medicina Veterinária'
    CRTR = '15', 'CRTR — Técnicos em Radiologia'


#: UF pela sigla, gravada; o XML leva o código do IBGE (`dm_UF`).
UF_IBGE = {
    'RO': '11', 'AC': '12', 'AM': '13', 'RR': '14', 'PA': '15', 'AP': '16', 'TO': '17',
    'MA': '21', 'PI': '22', 'CE': '23', 'RN': '24', 'PB': '25', 'PE': '26', 'AL': '27',
    'SE': '28', 'BA': '29', 'MG': '31', 'ES': '32', 'RJ': '33', 'SP': '35', 'PR': '41',
    'SC': '42', 'RS': '43', 'MS': '50', 'MT': '51', 'GO': '52', 'DF': '53',
}


class ProfissionalTiss(TenantModel):
    """Quem solicita ou executa, como a guia o identifica.

    Pode ser da clínica (`membership`) ou **externo** — o médico de fora que
    pediu o exame não precisa ter conta no NeuroDoc. Médico da agenda,
    solicitante, executante e prestador faturador são papéis diferentes, e
    a mesma pessoa pode ocupar mais de um.
    """

    nome = models.CharField(max_length=70)
    conselho = models.CharField(max_length=2, choices=Conselho.choices, default=Conselho.CRM)
    numero_conselho = models.CharField('número no conselho', max_length=15)
    uf = models.CharField('UF do conselho', max_length=2, choices=sorted((s, s) for s in UF_IBGE))
    #: CBO de seis dígitos (225112 = médico neurologista). O domínio aceito
    #: muda por versão e é conferido contra o XSD na guia (`dm_CBOS`).
    cbo = models.CharField('CBO', max_length=6)
    cpf = models.CharField('CPF', max_length=11, blank=True)
    membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    ativo = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        verbose_name = 'profissional (TISS)'
        verbose_name_plural = 'profissionais (TISS)'
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'conselho', 'numero_conselho', 'uf'],
                name='tiss_profissional_conselho_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.nome} ({self.get_conselho_display().split(" ")[0]} {self.numero_conselho}/{self.uf})'

    def clean(self):
        import re

        from base.validators import is_valid_cpf

        self.cbo = ''.join(c for c in (self.cbo or '') if c.isdigit())
        self.numero_conselho = (self.numero_conselho or '').strip()
        self.cpf = ''.join(c for c in (self.cpf or '') if c.isdigit())
        erros = {}
        if not re.fullmatch(r'\d{6}', self.cbo):
            erros['cbo'] = 'O CBO tem seis dígitos (ex.: 225112, médico neurologista).'
        if not self.numero_conselho:
            erros['numero_conselho'] = 'Informe o número no conselho.'
        if self.cpf and not is_valid_cpf(self.cpf):
            erros['cpf'] = 'CPF inválido.'
        if erros:
            raise ValidationError(erros)

    @property
    def externo(self):
        return self.membership_id is None

    @property
    def uf_ibge(self):
        return UF_IBGE[self.uf]


# ---------------------------------------------------------------- Sprint 2
#
# A guia, os itens e a numeração. A estrutura segue a união das versões
# (3.04.00 a 4.03.00) que a ANS publica para Consulta e SP/SADT: campo que
# só existe numa versão (nome do beneficiário e CNS na 3.x, regime de
# atendimento na 4.x) é guardado e só sai no XML da versão que o tem
# (Sprint 3). Árvore campo a campo de cada XSD em `docs/tiss/CAMPOS.md`.
#
# **Não há campo de CID**, de propósito: nenhuma versão das duas guias o
# tem (o diagnóstico com tabela e código é da guia de internação). O único
# campo clínico é a indicação clínica da SP/SADT, que só o médico preenche
# (`indicacao_por`), e que fica na guia porque vai à operadora.


class TipoGuia(models.TextChoices):
    CONSULTA = 'consulta', 'Guia de Consulta'
    SP_SADT = 'sp_sadt', 'Guia de SP/SADT'


class EstadoGuia(models.TextChoices):
    RASCUNHO = 'rascunho', 'Em preenchimento'
    FECHADA = 'fechada', 'Fechada'
    CANCELADA = 'cancelada', 'Cancelada'
    #: Fechada e depois corrigida: a revisão (`Guia.revisa`) a substitui. O
    #: conteúdo e o snapshot continuam como foram fechados.
    SUBSTITUIDA = 'substituida', 'Substituída por revisão'


class TipoContratadoSolicitante(models.TextChoices):
    PROPRIO = 'proprio', 'O próprio prestador da guia'
    CODIGO = 'codigo', 'Outro — código na operadora'
    CNPJ = 'cnpj', 'Outro — CNPJ'
    CPF = 'cpf', 'Outro — CPF'


class Sequencia(TenantModel):
    """O próximo número de guia da clínica, reservado sob trava.

    Nunca `MAX(numero) + 1`: duas recepcionistas gerando guia no mesmo
    segundo leriam o mesmo máximo. A linha é travada com `select_for_update`
    e incrementada na mesma transação que cria a guia — se a criação falha,
    o número volta junto.
    """

    nome = models.CharField(max_length=20)
    proximo = models.PositiveBigIntegerField(default=1)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'nome'], name='tiss_sequencia_nome_uniq'),
        ]


class Guia(TenantModel):
    """Uma guia de Consulta ou de SP/SADT.

    Nasce em preenchimento, com o que o NeuroDoc já sabe (cobertura,
    credenciamento, profissional, data). **Fechar congela**: o `snapshot`
    guarda o que foi faturado — carteira, contrato, preços, versão —, e
    mudar o cadastro depois não reescreve guia fechada. Corrigir uma guia
    fechada é cancelar com motivo e abrir outra que a `revisa`.
    """

    tipo = models.CharField(max_length=10, choices=TipoGuia.choices)
    estado = models.CharField(max_length=12, choices=EstadoGuia.choices, default=EstadoGuia.RASCUNHO)
    paciente = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='+')
    cobertura = models.ForeignKey(
        'patients.PatientCoverage', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    credenciamento = models.ForeignKey(
        Credenciamento, on_delete=models.PROTECT, null=True, blank=True, related_name='guias',
    )
    #: `numeroGuiaPrestador`: o número que a clínica dá à guia. Reservado na
    #: criação (`Sequencia`), único na clínica.
    numero_prestador = models.CharField('nº da guia no prestador', max_length=20)
    numero_operadora = models.CharField('nº da guia atribuído pela operadora', max_length=20, blank=True)
    guia_principal = models.CharField('nº da guia principal', max_length=20, blank=True)
    data_emissao = models.DateField('data de emissão')

    # autorização
    data_autorizacao = models.DateField('data da autorização', null=True, blank=True)
    senha = models.CharField('senha', max_length=20, blank=True)
    validade_senha = models.DateField('validade da senha', null=True, blank=True)
    cod_validacao = models.CharField('código de validação (token)', max_length=10, blank=True)
    ausencia_cod_validacao = models.CharField('motivo da ausência do código', max_length=2, blank=True)

    # beneficiário
    carteira = models.CharField('nº da carteira', max_length=20, blank=True)
    validade_carteira = models.DateField('validade da carteira', null=True, blank=True)
    atendimento_rn = models.BooleanField('atendimento a recém-nascido', default=False)

    # solicitante (SP/SADT)
    contratado_solicitante_tipo = models.CharField(
        'contratado solicitante', max_length=10,
        choices=TipoContratadoSolicitante.choices, default=TipoContratadoSolicitante.PROPRIO,
    )
    contratado_solicitante_codigo = models.CharField('código / CNPJ / CPF do solicitante', max_length=14, blank=True)
    contratado_solicitante_nome = models.CharField('nome do contratado solicitante', max_length=70, blank=True)
    solicitante = models.ForeignKey(
        ProfissionalTiss, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name='profissional solicitante',
    )
    data_solicitacao = models.DateField('data da solicitação', null=True, blank=True)
    carater_atendimento = models.CharField('caráter do atendimento', max_length=1, default='1')
    indicacao_clinica = models.CharField('indicação clínica', max_length=500, blank=True)
    indicacao_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    indicacao_em = models.DateTimeField(null=True, blank=True)
    cobertura_especial = models.CharField('indicador de cobertura especial', max_length=2, blank=True)

    # executante e atendimento
    executante = models.ForeignKey(
        ProfissionalTiss, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name='profissional executante',
    )
    tipo_atendimento = models.CharField('tipo de atendimento', max_length=2, blank=True)
    indicacao_acidente = models.CharField('indicação de acidente', max_length=1, default='9')
    tipo_consulta = models.CharField('tipo de consulta', max_length=1, blank=True)
    motivo_encerramento = models.CharField('motivo de encerramento', max_length=2, blank=True)
    regime_atendimento = models.CharField('regime de atendimento', max_length=2, default='01')
    saude_ocupacional = models.CharField('saúde ocupacional', max_length=2, blank=True)
    observacao = models.CharField('observação / justificativa', max_length=500, blank=True)

    # origem administrativa: de que horário/atendimento a guia nasceu. Só a
    # ligação — o conteúdo do prontuário não entra na guia.
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )

    # fechamento, cancelamento, revisão
    versao = models.CharField('versão do padrão no fechamento', max_length=10, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    fechada_em = models.DateTimeField(null=True, blank=True)
    fechada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    cancelada_em = models.DateTimeField(null=True, blank=True)
    cancelada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    motivo_cancelamento = models.CharField(max_length=255, blank=True)
    revisa = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='revisoes',
    )
    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        verbose_name = 'guia TISS'
        verbose_name_plural = 'guias TISS'
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'numero_prestador'], name='tiss_guia_numero_uniq'),
            models.CheckConstraint(
                condition=~models.Q(estado='fechada') | models.Q(fechada_em__isnull=False),
                name='tiss_guia_fechada_tem_data',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'paciente', '-data_emissao'], name='tiss_guia_paciente_idx'),
            models.Index(fields=['tenant', 'estado', 'data_emissao'], name='tiss_guia_estado_idx'),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.numero_prestador}'

    @property
    def editavel(self):
        return self.estado == EstadoGuia.RASCUNHO

    @property
    def versao_efetiva(self):
        """A versão do fechamento; antes dele, a do credenciamento."""
        if self.versao:
            return self.versao
        return self.credenciamento.versao if self.credenciamento_id else versoes.VERSAO_ATUAL


class ItemGuia(TenantModel):
    """Um procedimento **realizado** — confirmado por quem fatura.

    Agendamento, pedido de exame e check-in não provam execução: nenhum item
    nasce sozinho de um pedido. A guia de Consulta tem exatamente um item; a
    SP/SADT, quantos forem realizados.

    O código e a descrição são guardados como texto, com a release TUSS de
    onde vieram: o espelho troca de release, e a guia continua dizendo o que
    foi cobrado. O preço guarda a origem (`preco_origem`); alterá-lo à mão
    exige motivo (`preco_motivo`).
    """

    guia = models.ForeignKey(Guia, on_delete=models.CASCADE, related_name='itens')
    sequencial = models.PositiveSmallIntegerField()
    data_execucao = models.DateField('data da execução')
    hora_inicial = models.TimeField('hora inicial', null=True, blank=True)
    hora_final = models.TimeField('hora final', null=True, blank=True)
    tabela = models.CharField('tabela', max_length=2, default='22')
    codigo = models.CharField('código do procedimento', max_length=10)
    descricao = models.CharField('descrição', max_length=150)
    release_tuss = models.CharField(max_length=40, blank=True)
    quantidade = models.PositiveSmallIntegerField('quantidade', default=1)
    via_acesso = models.CharField('via de acesso', max_length=1, blank=True)
    tecnica = models.CharField('técnica utilizada', max_length=1, blank=True)
    #: `reducaoAcrescimo` (st_decimal3-2): 1,00 é o preço cheio; 0,70 reduz
    #: 30%; 1,30 acresce 30%. Aplicado uma vez, no total.
    fator = models.DecimalField('fator de redução/acréscimo', max_digits=3, decimal_places=2, default=1)
    valor_unitario = models.DecimalField('valor unitário', max_digits=10, decimal_places=2)
    valor_total = models.DecimalField('valor total', max_digits=10, decimal_places=2)
    preco_origem = models.CharField(max_length=255, blank=True)
    preco_motivo = models.CharField('motivo da alteração do preço', max_length=255, blank=True)
    #: A cobrança que este item fatura, quando ela já existe (a consulta
    #: cobrada no check-in). Um recebível, no máximo um item: a guia vincula
    #: a cobrança existente e **nunca** cria outra para o mesmo serviço.
    recebivel = models.ForeignKey(
        'finance.Receivable', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        verbose_name = 'procedimento da guia'
        verbose_name_plural = 'procedimentos da guia'
        ordering = ['sequencial']
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['guia', 'sequencial'], name='tiss_item_sequencial_uniq'),
            models.UniqueConstraint(
                fields=['tenant', 'recebivel'], condition=models.Q(recebivel__isnull=False),
                name='tiss_item_recebivel_uniq',
            ),
            models.CheckConstraint(
                condition=models.Q(quantidade__gte=1, quantidade__lte=999), name='tiss_item_quantidade',
            ),
            models.CheckConstraint(
                condition=models.Q(fator__gt=0), name='tiss_item_fator_positivo',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.descricao[:40]}'
