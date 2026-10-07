"""O padrao da instalacao atende quem nao tem o seu -- IA e SMS.

Dois defeitos encontrados em 06/10/2026, com a **mesma assinatura**: a
instalacao passou a ter duas clinicas, e tudo que so e exercitado por
quem depende do padrao da instalacao estava quebrado. A primeira clinica
tem chave propria de IA e de SMS; nunca tocou nesses caminhos.

1. **A IA estava morta havia quarenta dias.** `AI_MODEL` no `.env`
   apontava para `nvidia/llama-3.3-nemotron-super-49b-v1.5`, que a NVIDIA
   aposentou em 2026-08-26 e que responde `410 Gone`. Nao havia tela
   mostrando o padrao da instalacao nem verificacao conferindo-o contra o
   catalogo do provedor, e trocar o modelo exigia editar arquivo, regerar
   runtime e republicar. O medico lia "A tarefa nao foi concluida. Tente
   novamente." -- conselho que nunca ia funcionar.

2. **O SMS nunca saiu.** A confirmacao de horario era enviada de dentro
   da requisicao, e o processo `app` **nao recebe o secret do SMSDEV**
   (§2: chave de egresso e do worker). Quem tem chave propria funciona,
   porque essa fica cifrada no banco; quem depende da instalacao recebia
   `SmsChannelDisabled`. E a entrega ficava registrada como **"sem
   contato cadastrado"**, mandando a clinica conferir o telefone do
   paciente, que estava certo.

O roteiro nao consegue provar que um provedor real responde -- isso
depende de rede e de credencial. O que ele prova e tudo que esta do lado
de ca: de onde vem o padrao, que a tela existe, que a verificacao acusa
modelo fora da lista, que a recusa do provedor nao vira "tente
novamente", que nenhuma entrega sai da requisicao, e que o canal
indisponivel nao se disfarca de paciente sem telefone.
"""
import re
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.urls import reverse
from django.utils import timezone

from base.models import InstallationSettings
from communications.models import DeliveryStatus

failures = []
raiz = Path(dj_settings.BASE_DIR)


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


print('=== 1. o padrao da instalacao mora no banco, e o .env so semeia ===')
config = InstallationSettings.carregar()
original = (config.ai_provider, config.ai_model, config.ai_base_url,
            config.ai_available_models, config.ai_checked_at,
            config.ai_check_ok, config.ai_check_detail)
try:
    config.ai_provider = 'openrouter'
    config.ai_model = 'modelo/escolhido-no-console'
    config.ai_base_url = ''
    config.save()
    provedor, modelo, _ = InstallationSettings.carregar().ia_da_instalacao()
    confere(provedor == 'openrouter' and modelo == 'modelo/escolhido-no-console',
            'o que o console gravou vence o .env', f'{provedor}/{modelo}')

    config.ai_provider = ''
    config.ai_model = ''
    config.save()
    provedor, modelo, _ = InstallationSettings.carregar().ia_da_instalacao()
    confere(provedor == dj_settings.AI_PROVIDER and modelo == dj_settings.AI_MODEL,
            'campo vazio cai no .env -- instalacao antiga nao fica sem provedor',
            f'{provedor}/{modelo}')

    print('=== 2. a verificacao acusa modelo que o provedor aposentou ===')
    # O estado exato da producao em 06/10/2026.
    config.ai_provider = 'nvidia'
    config.ai_model = 'nvidia/llama-3.3-nemotron-super-49b-v1.5'
    config.ai_available_models = ['nvidia/llama-3.1-nemotron-70b-instruct']
    config.ai_checked_at = timezone.now()
    config.save()
    confere(config.ia_modelo_fora_da_lista,
            'modelo ausente da lista do provedor e acusado')

    config.ai_model = 'nvidia/llama-3.1-nemotron-70b-instruct'
    config.save()
    confere(not config.ia_modelo_fora_da_lista, 'modelo presente na lista nao e acusado')

    # Nunca verificado nao pode parecer acusacao: a tela nao pode afirmar
    # o que nao conferiu.
    config.ai_checked_at = None
    config.ai_model = 'qualquer/coisa'
    config.save()
    confere(not config.ia_modelo_fora_da_lista,
            'sem verificacao, a tela nao acusa nada')
finally:
    (config.ai_provider, config.ai_model, config.ai_base_url,
     config.ai_available_models, config.ai_checked_at,
     config.ai_check_ok, config.ai_check_detail) = original
    config.save()

print('=== 3. a chave nao vem do provedor errado ao trocar de provedor ===')
# `settings.AI_API_KEY` e resolvida uma vez, na carga, a partir de
# `AI_PROVIDER`. Com o provedor escolhido no console, ler dali passaria a
# mandar a chave do provedor antigo -- que e o ciclo de deploy que o
# console existe para dispensar.
from ai import providers as _prov

fonte = Path(raiz, 'ai', 'providers', '__init__.py').read_text(encoding='utf-8')
corpo = fonte.split('def _installation_model(')[1].split('\ndef ')[0]
confere('installation_api_key(provider)' in corpo,
        'a chave da instalacao e lida pelo provedor em vigor')
confere('InstallationSettings' in corpo,
        'o provedor em vigor vem do console, nao de settings.AI_PROVIDER')
confere(hasattr(_prov, 'installation_api_key'),
        'installation_api_key existe e e importavel')

print('=== 4. a recusa do provedor nao vira "tente novamente" ===')
from ai.services import _falha_do_provedor


class _Resposta:
    def __init__(self, status):
        self.status_code = status


class _ErroDoProvedor(Exception):
    def __init__(self, status):
        super().__init__(f'Error code: {status}')
        self.response = _Resposta(status)


class _JobFalso:
    id = 'job-de-roteiro'


# 410 Gone: exatamente o que a NVIDIA respondeu por quarenta dias.
detalhe, diag = _falha_do_provedor(_ErroDoProvedor(410), _JobFalso())
print('   410 ->', detalhe)
confere(diag['configuracao'] is True, '410 e classificado como configuracao')
confere('Repetir não resolve' in detalhe,
        'e a mensagem diz que repetir nao resolve', detalhe)
confere(re.search(r'[A-Za-z]{4,} (?:failed|error)', detalhe) is None,
        'a mensagem esta em portugues', detalhe)

detalhe, diag = _falha_do_provedor(_ErroDoProvedor(503), _JobFalso())
print('   503 ->', detalhe)
confere(diag['configuracao'] is False, '503 e instabilidade, nao configuracao')
confere('Tente novamente' in detalhe, 'e ai sim manda tentar de novo', detalhe)

for passageiro in (408, 429):
    _, diag = _falha_do_provedor(_ErroDoProvedor(passageiro), _JobFalso())
    confere(diag['configuracao'] is False,
            f'{passageiro} e passageiro apesar de 4xx')

# O diagnostico nao pode carregar credencial.
_, diag = _falha_do_provedor(_ErroDoProvedor(401), _JobFalso())
texto = repr(diag)
confere(not re.search(r'(?i)(api[_-]?key|bearer|sk-|nvapi)', texto),
        'o diagnostico nao carrega chave', texto[:160])

print('=== 5. a tela do console existe e oferece o catalogo ===')
from ai.providers.catalog import PROVIDER_CHOICES

tela = Path(raiz, 'templates', 'ops', 'superadmin', 'operations.html').read_text(encoding='utf-8')
confere('operations-installation-ai' in tela, 'a tela posta para a rota do provedor')
confere('name="provedor"' in tela and 'name="modelo"' in tela,
        'com campo de provedor e de modelo')
confere('value="verificar"' in tela, 'e com o botao de verificar')
confere('ia_fora_da_lista' in tela, 'e o aviso de modelo aposentado')
# A chave nao pode ser editavel aqui: o processo `app` nao a tem.
confere('name="api_key"' not in tela and 'name="chave"' not in tela,
        'a chave NAO e editavel no console')
confere(reverse('superadmin:operations-installation-ai').endswith('/operacao/provedor-de-ia/'),
        'a rota resolve', reverse('superadmin:operations-installation-ai'))
confere(len(PROVIDER_CHOICES) >= 10, 'o catalogo inteiro e oferecido',
        str(len(PROVIDER_CHOICES)))

print('=== 6. a verificacao roda no worker, nao na tela ===')
import ai.tasks as _ai_tasks

confere(hasattr(_ai_tasks, 'verificar_provedor_da_instalacao'),
        'a tarefa de verificacao existe')
fonte_console = Path(raiz, 'ops', 'superadmin.py').read_text(encoding='utf-8')
bloco = fonte_console.split('class InstallationAIView')[1].split('\nclass ')[0]
confere('verificar_provedor_da_instalacao.delay()' in bloco,
        'o console ENFILEIRA a verificacao')
confere('list_models(' not in bloco and 'probe_model(' not in bloco,
        'e nao fala com o provedor de dentro da requisicao')

print('=== 7. nenhuma entrega sai de dentro da requisicao ===')
# A regra do §2, cobrada por varredura e nao por lista: o processo `app`
# nao tem as chaves de egresso, entao quem envia e o worker. Foi a falta
# desta varredura que deixou a confirmacao de horario para tras depois de
# a entrega de documento ja ter sido corrigida.
PROIBIDOS = ('send_sms(', 'send_appointment_confirmation(', 'deliver_document(')
PERMITIDOS = {
    'communications/tasks.py': 'e o worker',
    'communications/services.py': 'e a implementacao, chamada pelo worker',
    'communications/handlers.py': 'consumidor de evento, despachado no worker',
    'communications/reconciliation.py': 'tarefa periodica',
    'communications/admin_views.py': 'consulta de saldo, que nao envia mensagem',
    'communications/smsdev.py': 'o proprio cliente',
}
suspeitos = []
for arquivo in sorted(raiz.rglob('*.py')):
    rel = arquivo.relative_to(raiz).as_posix()
    if rel.startswith(('.venv/', 'checks/')) or rel in PERMITIDOS:
        continue
    if not rel.endswith('views.py'):
        continue
    texto = arquivo.read_text(encoding='utf-8', errors='ignore')
    for proibido in PROIBIDOS:
        if proibido in texto:
            suspeitos.append(f'{rel} chama {proibido}')
print('  views que enviam direto:', suspeitos or 'nenhuma')
confere(not suspeitos, 'nenhuma view envia mensagem de dentro da requisicao',
        '; '.join(suspeitos))

vista = Path(raiz, 'scheduling', 'views.py').read_text(encoding='utf-8')
bloco = vista.split('class SendConfirmationView')[1].split('\nclass ')[0]
confere('send_confirmation_task.delay(' in bloco,
        'a confirmacao de horario e enfileirada')
confere('confirmation_contacts(' in bloco,
        'e a falta de contato continua sendo avisada na hora -- e o unico '
        'desfecho que a pessoa na tela resolve agora')

import communications.tasks as _com_tasks

confere(hasattr(_com_tasks, 'send_confirmation_task'), 'a tarefa existe')

print('=== 8. canal indisponivel nao se disfarca de paciente sem telefone ===')
confere(hasattr(DeliveryStatus, 'CHANNEL_UNAVAILABLE'), 'o estado existe')
confere(DeliveryStatus.CHANNEL_UNAVAILABLE.label == 'Canal indisponível',
        'com rotulo que diz o que houve',
        DeliveryStatus.CHANNEL_UNAVAILABLE.label)

servicos = Path(raiz, 'communications', 'services.py').read_text(encoding='utf-8')
bloco = servicos.split('def _send(')[1].split('\ndef ')[0]
for gatilho in ('tenant_inactive', 'channel_disabled'):
    trecho = bloco.split(gatilho)[0][-400:]
    confere('CHANNEL_UNAVAILABLE' in trecho and 'NO_CONTACT' not in trecho.split('CHANNEL_UNAVAILABLE')[-1],
            f'{gatilho} grava CHANNEL_UNAVAILABLE, nao NO_CONTACT')

from base.templatetags.nd import nd_tone

confere(nd_tone('channel_unavailable') == 'danger',
        'e aparece em vermelho -- nao ha o que a clinica cadastrar',
        nd_tone('channel_unavailable'))
confere(nd_tone('no_contact') == 'warning',
        'enquanto sem contato continua amarelo: esse a clinica resolve')

print('=== 9. a chave de egresso continua fora do processo web ===')
# A correcao nao pode ter sido "dar a chave ao `app`": o desenho do §2
# depende de o processo que atende o navegador nao ter credencial de
# saida. Se um dia isso mudar, que mude de propriedade e com justificativa
# -- nao de carona numa correcao de SMS.
stack = Path(raiz, 'docker-stack.yml').read_text(encoding='utf-8')
bloco_app = stack.split('\n  app:')[1].split('\n  celery_worker:')[0]
vazados = [s for s in ('SMSDEV_API_KEY', 'OPENROUTER_API_KEY', 'NVIDIA_API_KEY',
                       'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'SMTP_PASSWORD')
           if s in bloco_app]
confere(not vazados, 'o servico `app` nao recebe secret de egresso', ', '.join(vazados))

bloco_worker = stack.split('\n  celery_worker:')[1].split('\n  celery_beat:')[0]
faltando = [s for s in ('NEURODOC_SMSDEV_API_KEY', 'NEURODOC_NVIDIA_API_KEY',
                        'NEURODOC_OPENROUTER_API_KEY')
            if s not in bloco_worker]
confere(not faltando, 'e o worker recebe os que precisa', ', '.join(faltando))

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - o padrao da instalacao e trocavel, verificavel, e as entregas saem pelo worker.')
