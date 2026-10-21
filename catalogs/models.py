import re

from django.db import models

from base.models import TimestampedModel


class CatalogSystem(models.TextChoices):
    CID10 = 'CID10', 'CID-10'
    TUSS = 'TUSS', 'TUSS'
    CMED = 'CMED', 'CMED/Anvisa (medicamentos)'
    PORTARIA_344 = 'P344', 'Portaria 344/98 (substâncias controladas)'


class CatalogReleaseStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    ACTIVE = 'active', 'Ativa'
    SUPERSEDED = 'superseded', 'Substituída'


class CatalogRelease(TimestampedModel):
    system = models.CharField(max_length=10, choices=CatalogSystem.choices)
    version = models.CharField(max_length=40)
    source_url = models.URLField(max_length=2048, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    license_note = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=40, choices=CatalogReleaseStatus.choices, default=CatalogReleaseStatus.DRAFT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['system', 'version'], name='catalogs_catalogrelease_system_version_uniq'),
        ]

    def __str__(self):
        return f'{self.system} {self.version} ({self.status})'


class DiagnosisCode(TimestampedModel):
    release = models.ForeignKey(CatalogRelease, on_delete=models.PROTECT, related_name='diagnosis_codes')
    code = models.CharField(max_length=20)
    description = models.TextField(max_length=4000)
    parent_code = models.CharField(max_length=20, blank=True)
    #: Código e descrição sem acento e em maiúsculas, para a busca da tela.
    #: Existe como coluna porque este banco não tem a extensão `unaccent` e
    #: ninguém digita acento procurando "esclerose multipla" com pressa. São
    #: 14 mil linhas: a varredura sequencial custa menos que a dependência.
    search_text = models.TextField(blank=True, default='')
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['release', 'code'], name='catalogs_diagnosiscode_release_code_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.description[:60]}'


class ProcedureCode(TimestampedModel):
    release = models.ForeignKey(CatalogRelease, on_delete=models.PROTECT, related_name='procedure_codes')
    code = models.CharField(max_length=20)
    description = models.TextField(max_length=4000)
    parent_code = models.CharField(max_length=20, blank=True)
    #: Código e descrição sem acento e em maiúsculas, para a busca da tela.
    #: Existe como coluna porque este banco não tem a extensão `unaccent` e
    #: ninguém digita acento procurando "esclerose multipla" com pressa. São
    #: 14 mil linhas: a varredura sequencial custa menos que a dependência.
    search_text = models.TextField(blank=True, default='')
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['release', 'code'], name='catalogs_procedurecode_release_code_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.description[:60]}'


class PostalRangeScope(models.TextChoices):
    CITY = 'city', 'Total do município'
    URBAN = 'urban', 'Exclusiva da sede urbana'


class PostalCodeRange(TimestampedModel):
    """Faixa de CEP por município, dos Correios.

    Referência global — não pertence a nenhum tenant, como CID-10 e TUSS.
    Carregada de `catalogs/data/postal_ranges.csv` pelo comando
    `import_postal_codes`, de modo que a resolução de CEP para município/UF
    funcione sem nenhuma requisição externa.

    O conjunto de dados é por **faixa municipal**: ele resolve município,
    UF e código IBGE, e nunca logradouro ou bairro. `by_street` registra se
    o município é codificado por logradouro nos Correios — quando é falso,
    não existe CEP de rua nenhum ali e a tela pode dizer isso em vez de
    parecer que faltou preencher.

    `cep_start`/`cep_end` são textos de 8 dígitos com zero à esquerda, então
    a comparação lexicográfica coincide com a numérica e a busca por faixa
    é um simples BETWEEN sobre o índice.
    """

    cep_start = models.CharField(max_length=8)
    cep_end = models.CharField(max_length=8)
    uf = models.CharField(max_length=2)
    city = models.CharField(max_length=120)
    city_ascii = models.CharField(max_length=120)
    region = models.CharField(max_length=20, blank=True)
    ibge_code = models.CharField(max_length=7, blank=True)
    by_street = models.BooleanField(default=False)
    scope = models.CharField(max_length=10, choices=PostalRangeScope.choices, default=PostalRangeScope.CITY)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['cep_start', 'cep_end', 'scope', 'ibge_code'],
                name='catalogs_cep_range_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['cep_start', 'cep_end'], name='catalogs_cep_range_idx'),
        ]

    def __str__(self):
        return f'{self.cep_start}-{self.cep_end} {self.city}/{self.uf}'


class MedicationTarja(models.TextChoices):
    """A tarja da embalagem, como a lista da CMED a escreve.

    Serve para **avisar** quem prescreve, nunca para decidir por ele. A
    coluna TARJA é atributo da lista de **preços** da CMED, não a regra da
    Portaria SVS/MS 344/98: ela acompanha o que a Anvisa registrou para
    aquela apresentação e pode divergir do enquadramento que vale para o
    receituário. Um sistema que trocasse o formato da receita sozinho a
    partir dela estaria transformando dado comercial em decisão clínica.

    `NAO_INFORMADA` é o `- (*)` da planilha, que aparece em 4.670 das
    26.242 linhas. É ausência de informação, e não "sem tarja" — tratar os
    dois como a mesma coisa faria o sistema afirmar que um medicamento é
    isento quando ele só não foi classificado.
    """

    PRETA = 'preta', 'Tarja preta'
    VERMELHA_RESTRITA = 'vermelha_restrita', 'Tarja vermelha sob restrição'
    VERMELHA = 'vermelha', 'Tarja vermelha'
    SEM_TARJA = 'sem_tarja', 'Sem tarja'
    NAO_INFORMADA = 'nao_informada', 'Tarja não informada'


#: Tarjas que costumam exigir Receituário de Controle Especial. É a base do
#: aviso na tela — e a palavra "costumam" está no texto exibido de
#: propósito, porque quem decide é quem assina.
TARJAS_QUE_SUGEREM_CONTROLE_ESPECIAL = frozenset({
    MedicationTarja.PRETA, MedicationTarja.VERMELHA_RESTRITA,
})


class MedicationProduct(TimestampedModel):
    """Uma apresentação de medicamento da lista de preços da CMED/Anvisa.

    Catálogo público e global, como CID-10 e TUSS: não é dado de inquilino,
    e por isso herda `TimestampedModel` e não `TenantModel`.

    A linha da CMED é por **apresentação**, não por medicamento: o mesmo
    princípio ativo aparece em dezenas de linhas, uma por concentração,
    forma e embalagem. É exatamente o que se quer num autocomplete de
    receita, onde "500 mg comprimido revestido caixa com 20" é a informação
    que falta na hora de escrever.

    Os preços da planilha (52 das 74 colunas) **não** são importados. Eles
    envelhecem a cada publicação, ninguém prescreve por preço, e guardá-los
    transformaria um catálogo clínico numa tabela de valores desatualizada
    que alguém acabaria exibindo ao paciente.
    """

    release = models.ForeignKey(CatalogRelease, on_delete=models.PROTECT, related_name='medications')
    #: Código GGREM: o identificador da apresentação na CMED. Único na
    #: release, e é por ele que uma reimportação reconhece a mesma linha.
    ggrem = models.CharField(max_length=32)
    #: `TextField`, e não `CharField`: a substância de uma vacina
    #: pneumocócica lista todos os sorotipos e chega a 1.419 caracteres na
    #: lista de 09/2026. Qualquer teto que eu escolhesse aqui seria um
    #: `value too long` numa publicação futura — e o importador falha no
    #: meio, com a release pela metade.
    substance = models.TextField()
    product = models.CharField(max_length=300)
    presentation = models.CharField(max_length=500)
    laboratory = models.CharField(max_length=300, blank=True)
    therapeutic_class = models.CharField(max_length=300, blank=True)
    product_type = models.CharField(max_length=60, blank=True)
    tarja = models.CharField(
        max_length=30, choices=MedicationTarja.choices, default=MedicationTarja.NAO_INFORMADA,
    )
    registration = models.CharField(max_length=32, blank=True)
    ean = models.CharField(max_length=20, blank=True)
    #: Substância, produto e apresentação sem acento e em maiúsculas, para
    #: comparar com o que se digita. Mesma razão e mesma função do CID-10
    #: (`normalize_for_search`): este banco não tem `unaccent`, e ninguém
    #: digita acento procurando "dipirona" com o paciente na frente.
    search_text = models.TextField(blank=True, default='')
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['release', 'ggrem'], name='catalogs_medication_release_ggrem_uniq'),
        ]
        indexes = [
            models.Index(fields=['release', 'substance'], name='catalogs_med_substance_idx'),
        ]

    @property
    def sugere_controle_especial(self):
        return self.tarja in TARJAS_QUE_SUGEREM_CONTROLE_ESPECIAL

    def rotulo(self):
        """Nome e concentração, sem a descrição comercial da embalagem.

        A apresentação da CMED termina em blister, material e quantidade
        (``CT BL AL PLAS ... X 60``). Isso identifica uma linha da tabela de
        preços, mas não ajuda a escolher o medicamento e fazia uma opção
        simples ocupar várias linhas. A apresentação integral continua no
        campo próprio; o autocomplete mostra só a decisão clínica.
        """
        partes = [self.product or self.substance, self.dosagem_resumida()]
        return ' '.join(p for p in partes if p)

    def dosagem_resumida(self):
        """Extrai a concentração inicial da apresentação da CMED.

        A planilha não oferece uma coluna separada para a dose. Ela abre a
        apresentação pela concentração e depois informa a forma farmacêutica
        (comprimido, solução, cápsula...). Cortar nessa fronteira preserva
        combinações e concentrações como ``100 mg/ml`` sem levar embalagem
        e quantidade para a tela.
        """
        apresentacao = ' '.join((self.presentation or '').replace('\u00a0', ' ').split())
        if not apresentacao:
            return ''
        formas = (
            'COM', 'CAP', 'SOL', 'SUS', 'EMU', 'GEL', 'CREM', 'POM', 'PO', 'PÓ',
            'GRAN', 'ADES', 'XPE', 'ELX', 'LOC', 'PAS', 'LIQ', 'SUP', 'AER',
            'SPR', 'INJ', 'COL', 'OVU', 'SAB',
        )
        inicio_forma = re.compile(r'\s+(?=(?:' + '|'.join(formas) + r')\b)', re.IGNORECASE)
        dosagem = inicio_forma.split(apresentacao, maxsplit=1)[0].strip()
        if not re.search(r'\d', dosagem):
            return ''
        if not re.search(r'(?i)(?:mcg|mg|ml|ui|g|u)\b', dosagem):
            return ''
        dosagem = re.sub(
            r'(?i)(?<=\d)(MCG|MG|ML|UI|G|U)\b',
            lambda achado: f' {achado.group(1).lower()}', dosagem,
        )
        dosagem = re.sub(
            r'(?i)\b(MCG|MG|ML|UI|G|U)\b',
            lambda achado: achado.group(1).lower(), dosagem,
        )
        dosagem = re.sub(r'\s*/\s*', '/', dosagem)
        dosagem = re.sub(r'\s*\+\s*', ' + ', dosagem)
        return dosagem

    def __str__(self):
        return f'{self.product} ({self.substance[:40]})'


class Municipality(TimestampedModel):
    """Municipios brasileiros do IBGE, para a naturalidade do paciente.

    Referencia global, como CID-10 e TUSS: nao pertence a inquilino
    nenhum. Carregada por `import_municipios`, que roda **no worker** --
    sao 5.571 linhas vindas da API do IBGE, e trabalho externo e do
    worker (§2).

    Existe por um motivo pratico: a naturalidade digitada a mao vira
    "Sao Paulo", "SAO PAULO", "S. Paulo" e "São Paulo" na mesma clinica,
    e nenhuma busca por local de nascimento funciona depois. O catalogo
    da uma lista para escolher.

    **O campo do paciente continua aceitando texto livre**, e isso e
    decisao e nao esquecimento: paciente nascido fora do Brasil, ou em
    municipio que mudou de nome, tem de caber. O catalogo sugere; nao
    impede.

    `name_ascii` existe pela mesma razao que em `PostalCodeRange`: quem
    digita "sao paulo" sem acento tem de achar "São Paulo", e comparar
    sem acento no banco exigiria `unaccent` instalado.
    """

    ibge_code = models.CharField(max_length=7, unique=True)
    name = models.CharField(max_length=120)
    name_ascii = models.CharField(max_length=120)
    uf = models.CharField(max_length=2)

    class Meta:
        indexes = [
            models.Index(fields=['name_ascii'], name='catalogs_municipio_nome_idx'),
            models.Index(fields=['uf'], name='catalogs_municipio_uf_idx'),
        ]
        ordering = ['name', 'uf']

    def __str__(self):
        return f'{self.name}/{self.uf}'

    @property
    def label(self):
        return f'{self.name}/{self.uf}'


class ControlledList(TimestampedModel):
    """Uma lista do Anexo I da Portaria SVS/MS 344/1998 ("C1", "B1"...).

    Ver `catalogs/portaria344.py`: a lista decide o receituário, e o
    `receituario` é o que a norma fixa para ela, não a leitura do texto.
    O `adendo` guarda as exceções por dose, forma e associação **como
    texto**, para o médico ler — o sistema não as aplica sozinho.
    """

    release = models.ForeignKey(CatalogRelease, on_delete=models.PROTECT, related_name='controlled_lists')
    code = models.CharField('lista', max_length=4)
    title = models.CharField('título', max_length=300, blank=True)
    receituario = models.CharField('receituário', max_length=40)
    receituario_texto = models.CharField('receituário (texto do anexo)', max_length=300, blank=True)
    adendo = models.TextField('adendo', blank=True)
    position = models.PositiveSmallIntegerField('ordem', default=0)

    class Meta:
        verbose_name = 'lista de substâncias controladas'
        verbose_name_plural = 'listas de substâncias controladas'
        constraints = [
            models.UniqueConstraint(fields=['release', 'code'], name='catalogs_controlledlist_release_code_uniq'),
        ]

    def __str__(self):
        return f'Lista {self.code}'


class ControlledSubstance(TimestampedModel):
    """Uma substância de uma lista da Portaria 344, na redação do anexo.

    `search_text` é o nome e os sinônimos sem acento e em maiúsculas — a
    mesma forma de `catalogs.importers.normalize_for_search` —, porque a
    classificação compara com a substância da CMED ("CLORIDRATO DE
    SERTRALINA") e o banco não tem `unaccent`.
    """

    release = models.ForeignKey(CatalogRelease, on_delete=models.PROTECT, related_name='controlled_substances')
    controlled_list = models.ForeignKey(ControlledList, on_delete=models.PROTECT, related_name='substances')
    number = models.PositiveSmallIntegerField('número na lista')
    name = models.CharField('substância', max_length=500)
    synonyms = models.TextField('sinônimos', blank=True)
    search_text = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'substância controlada'
        verbose_name_plural = 'substâncias controladas'
        constraints = [
            models.UniqueConstraint(
                fields=['controlled_list', 'number'], name='catalogs_controlledsubstance_list_number_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.controlled_list.code})'
