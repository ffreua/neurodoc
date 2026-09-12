"""O provedor padrao da instalacao alcanca o catalogo inteiro?

A pergunta nasceu de um defeito real: `AI_PROVIDER=nvidia` no `.env`
levantava "Unknown AI provider", ainda que a NVIDIA estivesse no catalogo
e funcionasse quando uma clinica a escolhia pela tela. O padrao da
instalacao usava um mapa de tres provedores; o caminho por clinica usava o
catalogo de dez.

Nada aqui chama provedor de verdade. O que se verifica e a montagem do
cliente: provedor, modelo, endereco e chave.
"""
from django.conf import settings
from django.test import override_settings

from ai.providers import (
    ProviderUnavailable, active_provider_label, get_chat_model, installation_secret_name,
)
from ai.providers.catalog import ANTHROPIC_NATIVE, PROVIDERS, provider_kind

failures = []

print('=== 1. todo provedor do catalogo serve de padrao da instalacao ===')
for nome in sorted(PROVIDERS):
    esperado_url = PROVIDERS[nome].get('base_url', '')
    with override_settings(AI_ENABLED=True, AI_PROVIDER=nome,
                           AI_MODEL='modelo-de-teste', AI_API_KEY='chave-de-teste'):
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

print('=== 2. a NVIDIA e o padrao desta instalacao ===')
print(f'  AI_PROVIDER={settings.AI_PROVIDER}  AI_MODEL={settings.AI_MODEL}')
print(f'  rotulo na tela: {active_provider_label()}')
if settings.AI_PROVIDER != 'nvidia':
    failures.append(f'AI_PROVIDER={settings.AI_PROVIDER}, esperado nvidia')

print('=== 3. o erro diz qual secret falta ===')
with override_settings(AI_ENABLED=True, AI_PROVIDER='nvidia', AI_API_KEY=''):
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
with override_settings(AI_ENABLED=True, AI_PROVIDER='inexistente', AI_API_KEY='x'):
    try:
        get_chat_model()
        failures.append('provedor inexistente montou um cliente')
    except ProviderUnavailable as exc:
        lista = 'nvidia' in str(exc) and 'openrouter' in str(exc)
        print(f'  recusado, e lista os conhecidos={lista}')
        if not lista:
            failures.append('a recusa de provedor desconhecido nao lista os conhecidos')

print('=== 5. AI_ENABLED=False desliga, mesmo com chave ===')
with override_settings(AI_ENABLED=False, AI_PROVIDER='nvidia', AI_API_KEY='chave'):
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

with override_settings(AI_ENABLED=True, AI_PROVIDER='nvidia',
                       AI_MODEL='modelo-da-instalacao', AI_API_KEY='chave-da-instalacao'):
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

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o padrao da instalacao alcanca o catalogo, e nao atropela a clinica.')
