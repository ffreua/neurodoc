"""Cada clinica usa o seu; desligando, volta ao padrao da instalacao.

Sao tres servicos com a mesma promessa -- **IA, SMS e e-mail** -- e a
promessa tem duas metades que falham por motivos diferentes:

- a clinica que configurou o seu fala com o contrato dela, e nunca cai
  no da instalacao sem pedir (senao prontuario sairia por um provedor
  que ninguem escolheu, e credito seria gasto na conta errada);
- a clinica que **desligou** o seu volta ao padrao -- e nao fica sem o
  servico. Desligar e dizer "use o de voces", nao "nao use nenhum".

Este roteiro existe porque as duas metades ja falharam em producao, cada
uma de um jeito, em 06/10/2026: a IA da instalacao apontava para um
modelo aposentado, e o SMS da clinica sem chave propria nunca saia. Os
dois so eram exercitados por quem dependia do padrao -- e a primeira
clinica real tinha tudo proprio.

Cobre tambem o **nome fantasia**, que entrou junto por ser a outra coisa
que o inquilino precisava poder mudar sozinho e nao podia.
"""
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from unittest.mock import patch

from django.test import override_settings

from base.crypto import encrypt_secret
from tenancy.models import Tenant

failures = []
raiz = Path(dj_settings.BASE_DIR)


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-b')

print('=== 1. e-mail: o SMTP da clinica desliga o da instalacao, e volta ===')
from communications.email import resolve_sender
from communications.models import MessagingSettings

row, _ = MessagingSettings.objects.get_or_create(tenant_id=tenant.id)
guardado = {
    f: getattr(row, f) for f in (
        'email_enabled', 'email_from_address', 'email_from_name', 'smtp_host',
        'smtp_port', 'smtp_user', 'smtp_password_ciphertext', 'smtp_password_metadata',
        'sms_enabled', 'sms_api_key_ciphertext', 'sms_api_key_metadata',
    )
}
try:
    # Estado 1: a clinica nao configurou nada -> instalacao.
    row.email_enabled = False
    row.email_from_address = ''
    row.smtp_host = ''
    row.save()
    confere(resolve_sender(tenant_id=tenant.id) is None,
            'sem configuracao da clinica, o remetente e o da instalacao')

    # Estado 2: a clinica quer so o remetente dela, pelo servidor da
    # instalacao. E um estado legitimo e nao uma meia-configuracao: a
    # clinica que nao tem servidor proprio ainda quer que o e-mail saia
    # no nome dela.
    row.email_enabled = True
    row.email_from_address = 'contato@clinicab.example'
    row.email_from_name = 'Clinica B'
    row.smtp_host = ''
    row.save()
    sender = resolve_sender(tenant_id=tenant.id)
    confere(sender is not None, 'com remetente proprio, a clinica assina o e-mail')
    confere(sender is not None and not sender.uses_own_server,
            'e sem servidor proprio continua saindo pelo da instalacao')
    confere(sender is not None and 'contato@clinicab.example' in sender.header,
            'com o endereco dela no cabecalho', getattr(sender, 'header', ''))

    # Estado 3: servidor proprio. Agora o da instalacao nao e usado.
    row.smtp_host = 'smtp.clinicab.example'
    row.smtp_port = 587
    row.smtp_user = 'contato@clinicab.example'
    row.smtp_password_ciphertext, row.smtp_password_metadata = encrypt_secret('senha-do-roteiro')
    row.save()
    sender = resolve_sender(tenant_id=tenant.id)
    confere(sender is not None and sender.uses_own_server,
            'com SMTP proprio, a clinica passa a usar o servidor dela')
    confere(sender is not None and sender.host == 'smtp.clinicab.example',
            'no host que ela informou', getattr(sender, 'host', ''))

    # Estado 4: desliga. **Volta ao da instalacao** -- nao fica sem.
    row.email_enabled = False
    row.save()
    confere(resolve_sender(tenant_id=tenant.id) is None,
            'desligado, volta ao remetente da instalacao -- e nao fica sem e-mail')

    # E o host sozinho, com o canal desligado, nao pode valer: desligar
    # tem de desligar mesmo, sem deixar o servidor da clinica em uso por
    # um campo que ficou preenchido.
    confere(resolve_sender(tenant_id=tenant.id) is None,
            'host preenchido nao reativa o que foi desligado')

    print('=== 2. o remetente do medico vence o da clinica ===')
    from communications.models import DoctorEmailSettings
    from tenancy.models import Membership

    row.email_enabled = True
    row.smtp_host = ''
    row.save()
    medico = Membership.objects.filter(tenant_id=tenant.id).first()
    doc_row, _ = DoctorEmailSettings.objects.get_or_create(
        tenant_id=tenant.id, physician_membership=medico,
        defaults={'from_email': 'medico@clinicab.example'},
    )
    doc_row.enabled = True
    doc_row.from_email = 'medico@clinicab.example'
    doc_row.save()
    sender = resolve_sender(physician_membership=medico, tenant_id=tenant.id)
    confere(sender is not None and 'medico@clinicab.example' in sender.header,
            'o medico que configurou o seu assina no nome dele',
            getattr(sender, 'header', ''))
    doc_row.enabled = False
    doc_row.save()
    # Releitura do vinculo, e nao reaproveitamento do objeto: Django
    # guarda o relacionamento `email_settings` em cache na instancia, e a
    # primeira chamada acima ja o carregou com `enabled=True`. Sem isto o
    # roteiro mede o cache do proprio roteiro -- em producao cada
    # requisicao carrega o vinculo do zero.
    medico = Membership.objects.get(pk=medico.pk)
    sender = resolve_sender(physician_membership=medico, tenant_id=tenant.id)
    confere(sender is not None and 'contato@clinicab.example' in sender.header,
            'desligando o do medico, volta ao da clinica',
            getattr(sender, 'header', ''))

    print('=== 3. SMS: a chave da clinica desliga a da instalacao, e volta ===')
    from communications.smsdev import SmsChannelDisabled, resolve_api_key

    with patch.object(dj_settings, 'SMSDEV_API_KEY', 'chave-da-instalacao'):
        row.sms_enabled = False
        row.sms_api_key_ciphertext = ''
        row.sms_api_key_metadata = {}
        row.save()
        confere(resolve_api_key(tenant.id) == 'chave-da-instalacao',
                'sem chave propria, usa a da instalacao')

        row.sms_enabled = True
        row.sms_api_key_ciphertext, row.sms_api_key_metadata = encrypt_secret('chave-da-clinica')
        row.save()
        confere(resolve_api_key(tenant.id) == 'chave-da-clinica',
                'com chave propria, usa a dela -- o credito sai da conta certa')

        # Desligar o canal com chave gravada e uma recusa explicita, e
        # nao um retorno ao padrao: a clinica que desliga o SMS esta
        # dizendo "nao mande SMS", nao "mande pela conta de voces".
        row.sms_enabled = False
        row.save()
        try:
            resolve_api_key(tenant.id)
            confere(False, 'desligar o canal de SMS da clinica recusa o envio')
        except SmsChannelDisabled:
            confere(True, 'desligar o canal de SMS da clinica recusa o envio')

        # Sem chave gravada, voltar ao padrao e o certo -- e e o estado
        # da segunda clinica real.
        row.sms_api_key_ciphertext = ''
        row.sms_api_key_metadata = {}
        row.save()
        confere(resolve_api_key(tenant.id) == 'chave-da-instalacao',
                'apagando a chave, volta a da instalacao')

    print('=== 4. SMS segue cortado por plano, mesmo com chave propria ===')
    from tenancy.plans import PlanCode, has_sms

    plano_original = tenant.plan
    tenant.plan = PlanCode.FREE
    tenant.save(update_fields=['plan'])
    confere(not has_sms(PlanCode.FREE), 'o plano Gratuito nao inclui SMS')
    row.sms_enabled = True
    row.sms_api_key_ciphertext, row.sms_api_key_metadata = encrypt_secret('chave-da-clinica')
    row.save()
    try:
        resolve_api_key(tenant.id)
        confere(False, 'o corte por plano vem antes da chave da clinica')
    except SmsChannelDisabled:
        confere(True, 'o corte por plano vem antes da chave da clinica')
    tenant.plan = plano_original
    tenant.save(update_fields=['plan'])

    print('=== 5. IA: o provedor da clinica desliga o da instalacao, e volta ===')
    from ai.models import AIProviderSettings
    from ai.providers import get_chat_model
    from base.models import InstallationSettings

    config = InstallationSettings.carregar()
    antes_ia = (config.ai_provider, config.ai_model)
    config.ai_provider, config.ai_model = 'nvidia', 'modelo-da-instalacao'
    config.save(update_fields=['ai_provider', 'ai_model', 'updated_at'])

    ia_row, _ = AIProviderSettings.objects.get_or_create(tenant_id=tenant.id)
    guardado_ia = (ia_row.provider, ia_row.model, ia_row.enabled,
                   ia_row.api_key_ciphertext, ia_row.api_key_metadata)
    try:
        # `AI_ENABLED=False` e o padrao do ambiente local (P-03 nasceu
        # disso). Sem ligar aqui, esta secao nao mede a cadeia de
        # provedor -- mede o interruptor global, que `check_ia_padrao`
        # ja cobre.
        contexto_ia = patch(
            'ai.providers.installation_api_key', return_value='chave-da-instalacao',
        )
        with override_settings(AI_ENABLED=True), contexto_ia:
            ia_row.enabled = False
            ia_row.model = ''
            ia_row.api_key_ciphertext = ''
            ia_row.save()
            usado = get_chat_model(tenant_id=tenant.id)
            nome = getattr(usado, 'model_name', None) or getattr(usado, 'model', None)
            confere(str(nome) == 'modelo-da-instalacao',
                    'sem provedor proprio, usa o da instalacao', str(nome))

            ia_row.provider = 'groq'
            ia_row.model = 'modelo-da-clinica'
            ia_row.enabled = True
            ia_row.api_key_ciphertext, ia_row.api_key_metadata = encrypt_secret('chave-da-clinica')
            ia_row.save()
            usado = get_chat_model(tenant_id=tenant.id)
            nome = getattr(usado, 'model_name', None) or getattr(usado, 'model', None)
            confere(str(nome) == 'modelo-da-clinica',
                    'com provedor proprio, o prontuario vai para o contrato dela', str(nome))

            # Desligar volta ao padrao -- a clinica nao fica sem IA.
            ia_row.enabled = False
            ia_row.save()
            usado = get_chat_model(tenant_id=tenant.id)
            nome = getattr(usado, 'model_name', None) or getattr(usado, 'model', None)
            confere(str(nome) == 'modelo-da-instalacao',
                    'desligando, volta ao da instalacao -- e nao fica sem IA', str(nome))

            # Meia-configuracao nao conta: `is_usable` exige ligada, com
            # chave e com modelo. Faltando qualquer uma, o pedido falharia
            # no provedor em vez de falhar aqui.
            ia_row.enabled = True
            ia_row.model = ''
            ia_row.save()
            usado = get_chat_model(tenant_id=tenant.id)
            nome = getattr(usado, 'model_name', None) or getattr(usado, 'model', None)
            confere(str(nome) == 'modelo-da-instalacao',
                    'configuracao pela metade cai no padrao, em vez de quebrar', str(nome))
    finally:
        (ia_row.provider, ia_row.model, ia_row.enabled,
         ia_row.api_key_ciphertext, ia_row.api_key_metadata) = guardado_ia
        ia_row.save()
        config.ai_provider, config.ai_model = antes_ia
        config.save(update_fields=['ai_provider', 'ai_model', 'updated_at'])
finally:
    for campo, valor in guardado.items():
        setattr(row, campo, valor)
    row.save()

print('=== 6. o nome fantasia e do inquilino ===')
from tenancy.forms import ClinicProfileForm

campos = ClinicProfileForm(tenant=tenant).fields
confere('trade_name' in campos, 'o campo existe no formulario de identidade da clinica')
confere(campos['trade_name'].label == 'Nome fantasia', 'com o rotulo certo',
        campos.get('trade_name').label if 'trade_name' in campos else '')
confere(not campos['trade_name'].required,
        'e nao e obrigatorio -- vazio cai na razao social')

form = ClinicProfileForm(tenant=tenant)
confere(form.fields['trade_name'].initial == tenant.trade_name,
        'o valor em vigor aparece preenchido')

# A razao social e o CNPJ continuam fora: sao o que a clinica e perante a
# Receita, chegam pelo convite, e editar aqui faria o contrato de adesao
# apontar para um nome que ninguem assinou.
for proibido in ('legal_name', 'cnpj', 'slug', 'plan'):
    confere(proibido not in campos, f'{proibido} continua fora deste formulario')

vista = Path(raiz, 'tenancy', 'admin_views.py').read_text(encoding='utf-8')
bloco = vista.split('class ClinicProfileView')[1].split('\nclass ')[0]
confere('tenant.trade_name = depois' in bloco, 'a view grava o nome fantasia no Tenant')
confere('trade_name_changed' in bloco,
        'e registra a troca na trilha -- o nome que o paciente le na receita '
        'e coisa que alguem vai querer datar depois')

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - cada clinica usa o seu, e desligando volta ao padrao da instalacao.')
