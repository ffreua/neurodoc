import uuid

from django.db import models


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    row_version = models.BigIntegerField(default=1)

    class Meta:
        abstract = True


class TenantModel(TimestampedModel):
    tenant = models.ForeignKey('tenancy.Tenant', on_delete=models.PROTECT)

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'id'],
                name='%(app_label)s_%(class)s_tenant_id_uniq',
            ),
        ]


class InstallationSettings(TimestampedModel):
    """As chaves da instalacao que se viram **sem deploy**.

    Nasceu de uma pergunta do proprietario durante a auditoria pre-deploy:
    por que autorizar apagamento de arquivo ou liberar um endereco de API
    exige editar `.env`, regerar o runtime e republicar? A resposta honesta
    e que nao exige -- e que o caminho por `.env` tem um defeito de
    seguranca proprio: **desligar demora**. Uma trava que so se solta com um
    ciclo de deploy nao serve de freio de emergencia, e freio de emergencia
    e exatamente o que essas duas chaves precisam ser.

    Por que uma linha so, e nao um par chave/valor generico: sao duas
    decisoes nomeadas, cada uma com significado proprio e com trilha
    propria. Uma tabela de `chave = texto` aceitaria `documents_gc_dry_run
    = 'talvez'` e so quebraria na madrugada de domingo.

    **O `.env` semeia, o banco decide.** As variaveis
    `AI_BASE_URL_ALLOWLIST` e `DOCUMENTS_GC_DRY_RUN` valem para criar esta
    linha na primeira vez; depois disso quem manda e o console. Mexer no
    `.env` de uma instalacao que ja rodou nao muda nada -- e a tela do
    console diz isso com todas as letras, porque uma regra dessas descoberta
    por tentativa custa uma madrugada.
    """

    #: Garante uma linha so: o `unique=True` num campo de valor fixo e o
    #: jeito de o banco recusar a segunda, em vez de a aplicacao lembrar.
    singleton = models.BooleanField(default=True, unique=True, editable=False)

    #: Um host por linha. Vazio = so os provedores do catalogo.
    ai_base_url_allowlist = models.TextField(blank=True)

    #: `True` conta e registra sem apagar. Ver `documents/tasks.py`.
    documents_gc_dry_run = models.BooleanField(default=True)

    # ----------------------------------------------------------------
    # Provedor de IA da instalacao
    # ----------------------------------------------------------------
    #
    # O padrao de **toda clinica que nao configurou o seu** -- isto e, de
    # toda clinica recem-criada. Morava so no `.env`, e foi assim que o
    # sistema ficou sem IA por quarenta dias sem ninguem notar: em
    # 2026-08-26 a NVIDIA aposentou
    # `nvidia/llama-3.3-nemotron-super-49b-v1.5`, passou a responder
    # `410 Gone`, e a unica forma de apontar para outro modelo era editar
    # arquivo, regerar o runtime e republicar. A clinica afetada foi
    # justamente a que nao tem chave propria.
    #
    # `ai/providers/catalog.py` ja dizia o que iria acontecer: "digitar
    # identificador de modelo e a forma mais comum de a IA falhar em
    # producao -- o nome esta certo hoje, o provedor o aposenta, e o erro
    # so aparece quando alguem pede um resumo no meio de um atendimento".
    # A tela **da clinica** foi construida para evitar isso, com lista
    # vinda do provedor; o padrao da instalacao ficou de fora, digitado a
    # mao num `.env` que ninguem reconfere.
    ai_provider = models.CharField(max_length=40, blank=True)
    ai_model = models.CharField(max_length=100, blank=True)

    #: Endereco da API, para provedor proprio. Vazio = o do catalogo.
    ai_base_url = models.CharField(max_length=300, blank=True)

    #: O que o provedor respondeu na ultima verificacao: a lista de
    #: modelos, quando, e se o modelo escolhido ainda esta entre eles.
    #: Guardado porque a verificacao roda **no worker** (e dele a chave e
    #: a saida para a internet, §2) e a tela do console nao pode
    #: perguntar ao provedor por conta propria.
    ai_available_models = models.JSONField(default=list, blank=True)
    ai_checked_at = models.DateTimeField(null=True, blank=True)
    ai_check_ok = models.BooleanField(null=True, blank=True)
    ai_check_detail = models.CharField(max_length=300, blank=True)

    # ----------------------------------------------------------------
    # Provedor de IA reserva da instalacao
    # ----------------------------------------------------------------
    #
    # Assume **sozinho** quando a chamada ao provedor principal falha --
    # tempo esgotado, provedor fora do ar, limite de uso, modelo aposentado,
    # chave recusada. E a primeira excecao deliberada a regra RT-04 ("nunca
    # trocar de provedor em silencio"), e as tres travas que a tornam
    # aceitavel sao estas:
    #
    # - **so vale para quem usa o padrao da instalacao.** A clinica que
    #   configurou a propria IA escolheu para onde o prontuario vai, e
    #   nunca recua -- nem para a NVIDIA, nem para a reserva;
    # - **nao e silenciosa**: cada uso conta aqui (`ai_reserva_usos`,
    #   `ai_reserva_usada_em`), entra na trilha como `ai.reserva_usada` e o
    #   artefato grava qual provedor respondeu de fato;
    # - **nasce desligada** (`ai_reserva_ativa`), e ligar e ato explicito
    #   no console, com a reserva configurada e a chave gravada.
    #
    # Por que existe: em 2026 a NVIDIA aposentou o modelo padrao e a IA de
    # quem dependia dele ficou quarenta dias parada. A verificacao no
    # console mostrou o defeito quando alguem olhou; a reserva faz o
    # sistema continuar atendendo enquanto ninguem olha.
    #
    # A **chave** da reserva mora aqui, cifrada (`base.crypto`), e nao em
    # secret do servidor como a do principal -- o pedido do proprietario
    # foi justamente configura-la sem editar arquivo no servidor. A
    # protecao e a mesma da chave de IA de cada clinica (que ja mora no
    # banco assim): a tela grava, nunca mostra, e quem decifra e o worker
    # na hora da chamada.
    ai_reserva_ativa = models.BooleanField(default=False)
    ai_reserva_provider = models.CharField(max_length=40, blank=True)
    ai_reserva_model = models.CharField(max_length=100, blank=True)
    ai_reserva_base_url = models.CharField(max_length=300, blank=True)
    ai_reserva_chave_cifrada = models.TextField(blank=True)
    ai_reserva_chave_meta = models.JSONField(default=dict, blank=True)
    #: Os ultimos caracteres, para a tela mostrar **que** ha chave e qual.
    ai_reserva_chave_dica = models.CharField(max_length=40, blank=True)
    ai_reserva_modelos = models.JSONField(default=list, blank=True)
    ai_reserva_checked_at = models.DateTimeField(null=True, blank=True)
    ai_reserva_check_ok = models.BooleanField(null=True, blank=True)
    ai_reserva_check_detail = models.CharField(max_length=300, blank=True)
    #: Quantas vezes a reserva atendeu, e a ultima. E o que torna a troca
    #: visivel: reserva usada todo dia quer dizer principal quebrado.
    ai_reserva_usos = models.PositiveIntegerField(default=0)
    ai_reserva_usada_em = models.DateTimeField(null=True, blank=True)

    #: Quando o aviso de "IA principal falhando" foi mandado por e-mail ao
    #: superadministrador. Zera quando a verificacao volta a passar; com
    #: ele, o aviso sai na passagem de "ok" para "falhou" e se repete uma
    #: vez por dia enquanto durar -- e nao a cada hora.
    ai_alerta_enviado_em = models.DateTimeField(null=True, blank=True)

    #: Por que a coleta foi autorizada a apagar. Exigido ao desligar o
    #: ensaio, pela mesma razao do `status_note` da organizacao: "por que
    #: isto esta ligado?" um ano depois nao tem outra fonte.
    documents_gc_note = models.CharField(max_length=255, blank=True)

    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        verbose_name = 'configuração da instalação'
        verbose_name_plural = 'configurações da instalação'

    def __str__(self):
        return 'Configuração da instalação'

    @classmethod
    def carregar(cls):
        """A linha unica, criada a partir do `.env` na primeira vez.

        `get_or_create` e nao `get`: uma instalacao que sobe pela primeira
        vez nao tem a linha, e a tarefa semanal nao pode falhar por isso --
        ela cai no padrao seguro, que e o do `.env`.
        """
        from django.conf import settings

        linha, _ = cls.objects.get_or_create(
            singleton=True,
            defaults={
                'ai_base_url_allowlist': chr(10).join(
                    getattr(settings, 'AI_BASE_URL_ALLOWLIST', []) or []
                ),
                'documents_gc_dry_run': getattr(settings, 'DOCUMENTS_GC_DRY_RUN', True),
                'ai_provider': getattr(settings, 'AI_PROVIDER', ''),
                'ai_model': getattr(settings, 'AI_MODEL', ''),
            },
        )
        return linha

    def ia_da_instalacao(self):
        """`(provedor, modelo, endereco)` em vigor para quem nao tem o seu.

        Cai no `.env` quando o campo esta vazio, e nao o contrario: e a
        regra desta tabela inteira -- **o `.env` semeia, o banco decide**.
        Uma instalacao que subiu antes desta coluna existir continua
        andando com o que o `.env` diz ate alguem abrir o console.
        """
        from django.conf import settings

        return (
            self.ai_provider or getattr(settings, 'AI_PROVIDER', ''),
            self.ai_model or getattr(settings, 'AI_MODEL', ''),
            self.ai_base_url or '',
        )

    @property
    def ia_modelo_fora_da_lista(self):
        """O modelo escolhido nao esta entre os que o provedor ofereceu.

        `False` enquanto nunca se verificou: a tela nao pode acusar o que
        nao conferiu. Esta e a pergunta que ninguem fazia ao padrao da
        instalacao, e cuja resposta -- "esse modelo nao existe mais desde
        agosto" -- custou quarenta dias de IA parada.
        """
        if not self.ai_available_models or not self.ai_checked_at:
            return False
        _, modelo, _ = self.ia_da_instalacao()
        return bool(modelo) and modelo not in self.ai_available_models

    def hosts_de_ia(self):
        """A lista de permissao, normalizada."""
        return {
            linha.strip().lower().rstrip('/')
            for linha in (self.ai_base_url_allowlist or '').splitlines()
            if linha.strip()
        }

    @property
    def reserva_configurada(self):
        """Provedor, modelo e chave da reserva -- os tres, ou nada.

        As tres juntas pela mesma razao do `is_usable` da clinica: faltando
        qualquer uma, a troca aconteceria e falharia no provedor reserva,
        dobrando a espera do medico para chegar ao mesmo erro.
        """
        return bool(
            self.ai_reserva_provider and self.ai_reserva_model
            and self.ai_reserva_chave_cifrada
        )

    @property
    def reserva_pronta(self):
        """Ligada **e** configurada: e so isto que deixa a troca acontecer."""
        return bool(self.ai_reserva_ativa and self.reserva_configurada)

    def reserva_api_key(self):
        """A chave da reserva em claro. So o worker deve chamar isto."""
        from base.crypto import decrypt_secret

        return decrypt_secret(self.ai_reserva_chave_cifrada, self.ai_reserva_chave_meta)
