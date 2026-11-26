"""A IA propria da clinica: liga e desliga, e apagar de verdade (2026-11-26).

O relato: "apaguei a chave e os dados e salvei, mas continua aparecendo". E
continuava, por desenho: o campo da chave em branco **mantem** a chave
guardada (reabrir a tela para trocar o modelo nao pode zera-la), e nao
havia nenhum jeito de apaga-la. Alem disso o navegador preenchia o
"Endereco da API" com o e-mail de login.

O que se cobra:

- a tela tem o liga/desliga (`role="switch"`, `data-nd-revela`), e os
  campos ficam escondidos com ele desligado e a mostra com ele ligado;
- o endereco sai sem preenchimento automatico e a chave com `new-password`;
- desligar e salvar guarda a chave (para religar sem colar de novo), e a
  clinica passa a usar a IA da instalacao;
- "Remover chave e configuracao" apaga a linha inteira -- chave cifrada,
  provedor, modelo --, entra na trilha sem a chave, e so por POST;
- quem nao configura integracoes nao remove, e a remocao de uma clinica
  nao toca a configuracao de outra.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.forms.models import model_to_dict
from django.test import Client

from ai.models import AIProviderSettings
from ai.providers import usa_padrao_da_instalacao
from audit.models import AuditEvent
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')
clinica_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo(tenant, papel):
    return Membership.objects.filter(
        tenant=tenant, roles__contains=[papel], status=MembershipStatus.ACTIVE,
    ).select_related('user').first()


def logado(m, tenant):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


dono = vinculo(clinica, Role.OWNER)
secretaria = vinculo(clinica, Role.SECRETARY)
cli = logado(dono, clinica)

# A demonstracao pode ter configuracao propria: guardada aqui e devolvida no fim.
guardadas = {
    t.id: [model_to_dict(r) | {'id': r.id} for r in AIProviderSettings.objects.filter(tenant=t)]
    for t in (clinica, clinica_b)
}


def configurar(tenant, ligada=True):
    AIProviderSettings.objects.filter(tenant=tenant).delete()
    return AIProviderSettings.objects.create(
        tenant=tenant, provider='openrouter', enabled=ligada, model='deepseek/deepseek-v4-flash',
        api_key_ciphertext='cifra-do-roteiro', api_key_metadata={}, api_key_hint='********a1e2',
    )


try:
    print('=== 1. o liga/desliga e os campos ===')
    configurar(clinica, ligada=False)
    tela = cli.get('/app/org/ia/')
    if tela.status_code == 404:
        tela = cli.get('/app/org/integracoes/ia/')
    corpo = tela.content.decode()
    confere(tela.status_code == 200, f'a tela abre para o responsavel ({tela.status_code})')
    confere('role="switch"' in corpo and 'data-nd-revela="ai-campos"' in corpo, 'tem o liga/desliga')
    confere('<div id="ai-campos" hidden>' in corpo, 'desligada, os campos ficam escondidos')
    confere('autocomplete="off"' in corpo.split('id="id_base_url"')[0][-400:]
            + corpo.split('id="id_base_url"')[1][:200], 'o endereco sem preenchimento automatico')
    confere('new-password' in corpo, 'a chave com new-password')
    confere('Remover chave e configuração' in corpo, 'o botao de remover aparece com chave guardada')
    AIProviderSettings.objects.filter(tenant=clinica).update(enabled=True)
    corpo = cli.get(tela.request['PATH_INFO']).content.decode()
    confere('<div id="ai-campos" >' in corpo or '<div id="ai-campos">' in corpo,
            'ligada, os campos aparecem')

    print('=== 2. desligar guarda a chave ===')
    url_tela = tela.request['PATH_INFO']
    salvar = url_tela.rstrip('/') + '/salvar/'
    r = cli.post(salvar, {'provider': 'openrouter', 'base_url': '', 'model': 'deepseek/deepseek-v4-flash',
                          'api_key': ''})
    linha = AIProviderSettings.objects.get(tenant=clinica)
    confere(r.status_code == 302 and not linha.enabled, 'salvar desligado desliga')
    confere(linha.has_api_key, 'e a chave continua guardada')
    confere(usa_padrao_da_instalacao(clinica.id), 'desligada, a clinica usa a IA da instalacao')

    print('=== 3. remover apaga de verdade ===')
    configurar(clinica_b)
    remover = url_tela.rstrip('/') + '/remover/'
    confere(cli.get(remover).status_code in (404, 405), 'GET nao remove')
    confere(AIProviderSettings.objects.filter(tenant=clinica).exists(), 'e a linha continua')
    if secretaria:
        r = logado(secretaria, clinica).post(remover)
        confere(r.status_code in (403, 404), 'a secretaria nao remove')
        confere(AIProviderSettings.objects.filter(tenant=clinica, api_key_ciphertext__gt='').exists(),
                'a chave segue la')
    trilha_antes = AuditEvent.objects.filter(action='ai.provider_settings_removed').count()
    r = cli.post(remover)
    confere(r.status_code == 302, 'o responsavel remove')
    confere(not AIProviderSettings.objects.filter(tenant=clinica).exclude(api_key_ciphertext='').exists(),
            'a chave cifrada saiu do banco')
    confere(not AIProviderSettings.objects.filter(tenant=clinica).exclude(model='').exists(),
            'e o modelo tambem')
    confere(AIProviderSettings.objects.filter(tenant=clinica_b, api_key_ciphertext='cifra-do-roteiro').exists(),
            'a configuracao da clinica B ficou intacta')
    evento = AuditEvent.objects.filter(action='ai.provider_settings_removed').order_by('-created_at').first()
    confere(AuditEvent.objects.filter(action='ai.provider_settings_removed').count() == trilha_antes + 1,
            'a remocao entrou na trilha')
    confere(evento is not None and 'cifra' not in str(evento.integrity_metadata), 'sem a chave na trilha')
    corpo = cli.get(url_tela).content.decode()
    confere('Chave guardada' not in corpo and 'Remover chave e configuração' not in corpo,
            'a tela nao mostra mais chave guardada nem o botao')
    confere(usa_padrao_da_instalacao(clinica.id), 'e a clinica usa a IA da instalacao')
finally:
    for tenant_id, linhas in guardadas.items():
        AIProviderSettings.objects.filter(tenant_id=tenant_id).delete()
        for dados in linhas:
            dados = dict(dados)
            dados['tenant_id'] = dados.pop('tenant')
            dados['updated_by_id'] = dados.pop('updated_by', None)
            AIProviderSettings.objects.create(**dados)
    print('  limpeza: configuracoes de IA da demonstracao devolvidas')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: a IA propria liga e desliga, guarda a chave ao desligar e apaga de verdade ao remover.')
