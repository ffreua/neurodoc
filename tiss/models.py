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
