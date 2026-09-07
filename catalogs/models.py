from django.db import models

from base.models import TimestampedModel


class CatalogSystem(models.TextChoices):
    CID10 = 'CID10', 'CID-10'
    TUSS = 'TUSS', 'TUSS'


class CatalogReleaseStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    ACTIVE = 'active', 'Active'
    SUPERSEDED = 'superseded', 'Superseded'


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
