"""O provedor padrao da instalacao alcanca o catalogo inteiro?

A pergunta nasceu de um defeito real: `AI_PROVIDER=nvidia` no `.env`
levantava "Unknown AI provider", ainda que a NVIDIA estivesse no catalogo
e funcionasse quando uma clinica a escolhia pela tela. O padrao da
instalacao usava um mapa de tres provedores; o caminho por clinica usava o
catalogo de dez.

**Desde 06/10/2026 o padrao vem do console, nao do `.env`** -- ver
`base.models.InstallationSettings` e `check_provedor_e_sms.py`. Este
roteiro passou a montar o cenario por ali, que e de onde o servidor le de
verdade: continuar usando `override_settings(AI_PROVIDER=...)` daria um
roteiro verde medindo um caminho que o produto nao percorre mais.

Nada aqui chama provedor de verdade. O que se verifica e a montagem do
cliente: provedor, modelo, endereco e chave.
"""
import contextlib
from unittest.mock import patch

from django.test import override_settings

from ai import providers as ai_providers
from ai.providers import (
    ProviderUnavailable, active_provider_label, get_chat_model, installation_secret_name,
)
from ai.providers.catalog import ANTHROPIC_NATIVE, PROVIDERS, provider_kind
from base.models import InstallationSettings

failures = []

_config = InstallationSettings.carregar()
_original = (_config.ai_provider, _config.ai_model, _config.ai_base_url)


@contextlib.contextmanager
def padrao_da_instalacao(provider, model='modelo-de-teste', base_url='', chave='chave-de-teste'):
    """Poe o console neste estado, e devolve o que estava.

    A chave e trocada por um dublê porque ela mora em secret e **o
    processo que roda este roteiro nao a tem** -- e nem deve ter. O que
    se verifica aqui e a montagem do cliente, nao a credencial.
    """
    config = InstallationSettings.carregar()
    anterior = (config.ai_provider, config.ai_model, config.ai_base_url)
    config.ai_provider, config.ai_model, config.ai_base_url = provider, model, base_url
    config.save(update_fields=['ai_provider', 'ai_model', 'ai_base_url', 'updated_at'])
    try:
        with patch.object(ai_providers, 'installation_api_key', return_value=chave):
            yield config
    finally:
        config.ai_provider, config.ai_model, config.ai_base_url = anterior
        config.save(update_fields=['ai_provider', 'ai_model', 'ai_base_url', 'updated_at'])

print('=== 1. todo provedor do catalogo serve de padrao da instalacao ===')
for nome in sorted(PROVIDERS):
    esperado_url = PROVIDERS[nome].get('base_url', '')
    with override_settings(AI_ENABLED=True), padrao_da_instalacao(nome):
        try:
            modelo = get_chat_model()
        except ProviderUnavailable as exc:
            print(f'  {nome:14} -> RECUSADO: {exc}')
            failures.append(f'{nome} nao pode ser o padrao da instalacao: {exc}')
            continue
        if provider_kind(nome) == ANTHROPIC_NATIVE:
            print(f'  {nome:14} -> ChatAnthropic  modelo={getattr(modelo, "model", "?")}')
            continue
        url = str(getattr(modelo, 'openai_api_base', '') or '')
        ok_url = url.rstrip('/') == esperado_url.rstrip('/')
        print(f'  {nome:14} -> ChatOpenAI  base_url ok={ok_url}  ({url})')
        if not ok_url:
            failures.append(f'{nome}: base_url {url!r}, esperado {esperado_url!r}')

print('=== 2. o padrao em vigor e o do console ===')
# Era `settings.AI_PROVIDER`, e a pergunta mudou junto com a resposta: o
# que importa nao e mais o que o `.env` diz, e sim o que o servidor usa.
# Foi por nao haver quem fizesse esta pergunta que a instalacao passou
# quarenta dias apontando para um modelo aposentado.
_provedor, _modelo, _url = InstallationSettings.carregar().ia_da_instalacao()
print(f'  em vigor: {_provedor} / {_modelo} {_url or "(endereco do catalogo)"}')
print(f'  rotulo na tela: {active_provider_label()}')
if _provedor not in PROVIDERS:
    failures.append(f'o padrao em vigor ({_provedor}) nao esta no catalogo')
if not _modelo:
    failures.append('a instalacao esta sem modelo escolhido')

print('=== 3. o erro diz qual secret falta ===')
with override_settings(AI_ENABLED=True), padrao_da_instalacao('nvidia', chave=''):
    try:
        get_chat_model()
        failures.append('sem chave, get_chat_model devolveu um cliente')
    except ProviderUnavailable as exc:
        nomeia = 'NEURODOC_NVIDIA_API_KEY' in str(exc)
        print(f'  mensagem nomeia o secret={nomeia}')
        print(f'  -> {exc}')
        if not nomeia:
            failures.append('a mensagem de chave ausente nao diz qual secret gravar')
print(f'  installation_secret_name("groq") = {installation_secret_name("groq")}')

print('=== 4. provedor fora do catalogo e recusado, e a lista aparece ===')
with override_settings(AI_ENABLED=True), padrao_da_instalacao('inexistente', chave='x'):
    try:
        get_chat_model()
        failures.append('provedor inexistente montou um cliente')
    except ProviderUnavailable as exc:
        lista = 'nvidia' in str(exc) and 'openrouter' in str(exc)
        print(f'  recusado, e lista os conhecidos={lista}')
        if not lista:
            failures.append('a recusa de provedor desconhecido nao lista os conhecidos')

print('=== 5. AI_ENABLED=False desliga, mesmo com chave ===')
with override_settings(AI_ENABLED=False), padrao_da_instalacao('nvidia', chave='chave'):
    try:
        get_chat_model()
        failures.append('AI_ENABLED=False nao impediu a montagem do cliente')
    except ProviderUnavailable as exc:
        print(f'  -> {exc}')

print('=== 6. a clinica que configurou a sua nao cai no padrao ===')
# A regra que nao pode quebrar: prontuario da clinica que escolheu um
# contrato nao pode ir para o provedor da instalacao.
from ai.models import AIProviderSettings
from tenancy.models import Tenant

tenant_b = Tenant.objects.get(slug='demo-clinica-b')
row = AIProviderSettings.objects.filter(tenant_id=tenant_b.id).first()
if row is None:
    row = AIProviderSettings(tenant_id=tenant_b.id)
from base.crypto import encrypt_secret

row.provider = 'groq'
row.model = 'modelo-da-clinica'
row.enabled = True
row.api_key_ciphertext, row.api_key_metadata = encrypt_secret('chave-da-clinica')
row.save()

with override_settings(AI_ENABLED=True), padrao_da_instalacao(
        'nvidia', model='modelo-da-instalacao', chave='chave-da-instalacao'):
    modelo = get_chat_model(tenant_id=tenant_b.id)
    usado = str(getattr(modelo, 'model_name', '') or getattr(modelo, 'model', ''))
    url = str(getattr(modelo, 'openai_api_base', '') or '')
    print(f'  modelo usado={usado}  base_url={url}')
    print(f'  rotulo na tela: {active_provider_label(tenant_id=tenant_b.id)}')
    if usado != 'modelo-da-clinica':
        failures.append(f'a clinica caiu no modelo da instalacao ({usado})')
    if 'groq' not in url:
        failures.append(f'a clinica caiu no endereco da instalacao ({url})')

AIProviderSettings.objects.filter(tenant_id=tenant_b.id).delete()

print('=== 7. sem escolha no console, o .env ainda responde ===')
# A instalacao que subiu antes desta coluna existir nao pode ficar sem
# provedor nenhum. `ia_da_instalacao()` cai no `.env` com o campo vazio,
# e e isso que faz a migration dispensar retroescrita.
from django.conf import settings as _settings

_c = InstallationSettings.carregar()
_antes = (_c.ai_provider, _c.ai_model)
_c.ai_provider, _c.ai_model = '', ''
_c.save(update_fields=['ai_provider', 'ai_model', 'updated_at'])
_p, _m, _ = InstallationSettings.carregar().ia_da_instalacao()
print(f'  campos vazios -> {_p} / {_m}  (do .env)')
if (_p, _m) != (_settings.AI_PROVIDER, _settings.AI_MODEL):
    failures.append('campo vazio nao caiu no .env')
_c.ai_provider, _c.ai_model = _antes
_c.save(update_fields=['ai_provider', 'ai_model', 'updated_at'])

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o padrao da instalacao alcanca o catalogo, e nao atropela a clinica.')
