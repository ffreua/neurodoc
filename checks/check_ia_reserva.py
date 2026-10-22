"""A reserva de IA da instalação assume quando o principal falha -- e só aí?

Em 2026 a NVIDIA aposentou o modelo padrão da instalação e a IA de quem
dependia dele ficou quarenta dias parada, sem ninguém saber. A 1.23 trouxe
duas peças: a **reserva**, que responde sozinha quando a chamada ao
principal falha, e a **vigilância** de hora em hora, que avisa por e-mail.

A reserva é a primeira exceção deliberada à regra de nunca trocar de
provedor em silêncio (RT-04), e as perguntas são as travas dela:

- desligada, nada troca: o principal que falha continua sendo o erro;
- ligada, o principal fora do ar (503) e o tempo esgotado passam para a
  reserva, e o artefato grava que **foi a reserva** que respondeu;
- a resposta que chega e não passa na validação **não** troca;
- a clínica com IA própria **nunca** recua para a reserva;
- no chat, a troca só antes da primeira palavra;
- cada uso conta, com a trilha **sem** chave nem conteúdo;
- no console: a chave grava cifrada e nunca volta à tela, ligar exige a
  verificação em verde, desligar é um clique;
- a vigilância manda um e-mail na passagem para a falha, não repete a
  cada hora, e zera quando volta.

Nenhuma chamada sai para a internet: os provedores são simulados.
"""
import time
import uuid
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import transaction
from django.test import Client
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
settings.SECURE_SSL_REDIRECT = False
settings.AI_ENABLED = True

from accounts.models import User
from ai import providers, services, tasks
from ai.chat_models import ChatMessage, ChatSession
from ai.models import AIArtifact, AIJob, AIJobKind, AIJobStatus, AIProviderSettings
from audit.models import AuditEvent
from base.crypto import encrypt_secret
from base.models import InstallationSettings
from clinical.models import Encounter, EncounterStatus
from notifications.models import Notification
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.plans import PlanCode

falhas = []
SUFIXO = f'@reserva-{uuid.uuid4().hex[:8]}.invalid'


def conferir(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


tenant = Tenant.objects.get(slug='demo-clinica-a')
doctor = next((
    m for m in Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).select_related('user').order_by('user__email')
    if m.can_practice_clinically()
), None)
encontros = list(Encounter.objects.filter(
    tenant=tenant, physician_membership=doctor, status=EncounterStatus.FINALIZED,
).order_by('id')) if doctor else []
if doctor is None or not encontros:
    print('PULADO: demonstração sem médico verificado e atendimento finalizado')
    raise SystemExit(0)

# ------------------------------------------------------------ estado guardado
config = InstallationSettings.carregar()
CAMPOS_RESERVA = [
    'ai_reserva_ativa', 'ai_reserva_provider', 'ai_reserva_model', 'ai_reserva_base_url',
    'ai_reserva_chave_cifrada', 'ai_reserva_chave_meta', 'ai_reserva_chave_dica',
    'ai_reserva_modelos', 'ai_reserva_checked_at', 'ai_reserva_check_ok',
    'ai_reserva_check_detail', 'ai_reserva_usos', 'ai_reserva_usada_em',
    'ai_alerta_enviado_em',
]
original = {campo: getattr(config, campo) for campo in CAMPOS_RESERVA}
plano_original = tenant.plan
ia_da_clinica = AIProviderSettings.objects.filter(tenant=tenant).first()
ia_da_clinica_ligada = ia_da_clinica.enabled if ia_da_clinica else None
jobs, sessoes = [], []
inicio_trilha = timezone.now()


def restaurar():
    linha = InstallationSettings.carregar()
    for campo, valor in original.items():
        setattr(linha, campo, valor)
    linha.save(update_fields=CAMPOS_RESERVA + ['updated_at'])
    tenant.plan = plano_original
    tenant.save(update_fields=['plan'])
    if ia_da_clinica is not None:
        AIProviderSettings.objects.filter(pk=ia_da_clinica.pk).update(enabled=ia_da_clinica_ligada)
    Notification.objects.filter(target_type='ai_job', target_id__in=[j.id for j in jobs]).delete()
    AIArtifact.objects.filter(job__in=jobs).delete()
    AIJob.objects.filter(id__in=[j.id for j in jobs]).delete()
    Notification.objects.filter(target_type='chat_session', target_id__in=sessoes).delete()
    ChatMessage.objects.filter(session_id__in=sessoes).delete()
    ChatSession.objects.filter(id__in=sessoes).delete()
    for conta in User.objects.filter(email__endswith=SUFIXO):
        conta.email = f'aposentado-{uuid.uuid4().hex[:12]}@reserva.invalid'
        conta.is_active = False
        conta.is_superuser = False
        conta.is_staff = False
        conta.set_unusable_password()
        conta.save()


# A clínica de demonstração precisa ter IA no plano e **não** ter a própria.
tenant.plan = PlanCode.COMPLETE
tenant.save(update_fields=['plan'])
if ia_da_clinica is not None:
    AIProviderSettings.objects.filter(pk=ia_da_clinica.pk).update(enabled=False)


def configurar_reserva(ativa):
    cifrada, meta = encrypt_secret('sk-roteiro-reserva-chave-0000')
    InstallationSettings.objects.filter(pk=config.pk).update(
        ai_reserva_ativa=ativa, ai_reserva_provider='openrouter',
        ai_reserva_model='modelo-reserva', ai_reserva_base_url='',
        ai_reserva_chave_cifrada=cifrada, ai_reserva_chave_meta=meta,
        ai_reserva_check_ok=True, ai_reserva_usos=0, ai_reserva_usada_em=None,
    )


# ------------------------------------------------------------ provedores simulados
class Resposta:
    def __init__(self, texto):
        self.content = texto


class ForaDoAr(Exception):
    status_code = 503


RESUMO_VALIDO = (
    '{"summary": "Resumo escrito pela reserva.", "qualitative_hypotheses": [], '
    '"missing_information": "", "limitations": "Roteiro.", "source_refs": []}'
)


class Falha:
    model_name = 'principal-quebrado'

    def invoke(self, prompt):
        raise ForaDoAr('provedor fora do ar')

    def stream(self, prompt):
        raise ForaDoAr('provedor fora do ar')


class Lento:
    model_name = 'principal-lento'

    def invoke(self, prompt):
        time.sleep(3)
        return Resposta(RESUMO_VALIDO)


class Lixo:
    model_name = 'principal-responde-lixo'

    def invoke(self, prompt):
        return Resposta('isto nao e JSON nenhum')


class Parcial:
    model_name = 'principal-cai-no-meio'

    def stream(self, prompt):
        yield Resposta('Começo da resposta ')
        raise ForaDoAr('caiu no meio')


class Reserva:
    model_name = 'modelo-reserva'

    def invoke(self, prompt):
        return Resposta(RESUMO_VALIDO)

    def stream(self, prompt):
        yield Resposta('Resposta da reserva.')


def novo_job(timeout=30):
    for encontro in encontros:
        job = AIJob.objects.create(
            tenant=tenant, user=doctor.user, membership=doctor,
            patient=encontro.patient, encounter=encontro,
            kind=AIJobKind.ENCOUNTER_SUMMARY, source_version=encontro.row_version,
            purpose='roteiro da reserva', status=AIJobStatus.QUEUED,
            limits={'timeout_seconds': timeout, 'max_output_chars': 20000},
            idempotency_key=f'roteiro-reserva-{uuid.uuid4()}',
        )
        jobs.append(job)
        return job
    return None


def rodar(principal, timeout=30):
    job = novo_job(timeout)
    reserva = MagicMock(side_effect=lambda: Reserva())
    with patch('ai.services.get_chat_model', return_value=principal), \
            patch('ai.services.installation_reserve_model', reserva):
        with transaction.atomic():
            services.run_job(str(job.id))
    job.refresh_from_db()
    return job, reserva.call_count


def usos():
    return InstallationSettings.carregar().ai_reserva_usos


try:
    with patch('ai.tasks.verificar_reserva_da_instalacao.delay'), \
            patch('ai.tasks.verificar_provedor_da_instalacao.delay'):

        print('=== 1. reserva desligada: o principal que falha continua sendo o erro ===')
        configurar_reserva(ativa=False)
        job, chamadas = rodar(Falha())
        print(f'  status={job.status}  reserva chamada={chamadas}  usos={usos()}')
        if job.status == AIJobStatus.BLOCKED_PRIVACY:
            print('PULADO: a política de privacidade barra o atendimento da demonstração')
            raise SystemExit(0)
        conferir(job.status == AIJobStatus.FAILED, 'com a reserva desligada o job não falhou')
        conferir(chamadas == 0, 'a reserva desligada foi chamada')
        conferir(usos() == 0, 'a reserva desligada contou uso')

        print('=== 2. reserva ligada, principal fora do ar (503): a reserva responde ===')
        configurar_reserva(ativa=True)
        job, chamadas = rodar(Falha())
        artefato = AIArtifact.objects.filter(job=job).first()
        print(f'  status={job.status}  reserva chamada={chamadas}  usos={usos()}  '
              f'provedor do artefato={getattr(artefato, "provider", None)}')
        conferir(job.status == AIJobStatus.SUCCEEDED, 'a reserva ligada não salvou o job')
        conferir(chamadas == 1, 'a reserva não foi chamada uma vez')
        conferir(usos() == 1, 'o uso da reserva não foi contado')
        conferir(artefato is not None and artefato.provider == 'openrouter'
                 and artefato.model == 'modelo-reserva',
                 'o artefato não grava que foi a reserva que respondeu')

        print('=== 3. a trilha registra o uso, sem chave e sem conteúdo ===')
        evento = AuditEvent.objects.filter(
            action='ai.reserva_usada', object_id=job.id, created_at__gte=inicio_trilha,
        ).first()
        texto = str(getattr(evento, 'integrity_metadata', ''))
        print(f'  evento={bool(evento)}  falha registrada={"status_http" in texto}')
        conferir(evento is not None, 'o uso da reserva não entrou na trilha')
        conferir('sk-roteiro' not in texto and 'Resumo' not in texto,
                 'a trilha da reserva carrega chave ou conteúdo')
        conferir('503' in texto, 'a trilha não diz por que o principal falhou')

        print('=== 4. tempo esgotado no principal também passa para a reserva ===')
        job, chamadas = rodar(Lento(), timeout=1)
        print(f'  status={job.status}  reserva chamada={chamadas}')
        conferir(job.status == AIJobStatus.SUCCEEDED and chamadas == 1,
                 'o tempo esgotado no principal não passou para a reserva')

        print('=== 5. resposta que chega e não passa na validação NÃO troca ===')
        antes = usos()
        job, chamadas = rodar(Lixo())
        print(f'  status={job.status}  reserva chamada={chamadas}')
        conferir(job.status == AIJobStatus.FAILED, 'a resposta inválida não reprovou o job')
        conferir(chamadas == 0 and usos() == antes,
                 'a resposta inválida do principal acionou a reserva')

        print('=== 6. a clínica com IA própria nunca recua para a reserva ===')
        with patch('ai.providers._tenant_settings', return_value=object()):
            utilizavel = providers.reserva_utilizavel(tenant.id)
            job, chamadas = rodar(Falha())
        print(f'  reserva utilizável={utilizavel}  status={job.status}  reserva chamada={chamadas}')
        conferir(not utilizavel, 'a reserva vale para clínica com IA própria')
        conferir(job.status == AIJobStatus.FAILED and chamadas == 0,
                 'a clínica com IA própria recuou para a reserva')

        print('=== 7. chat: a reserva responde se o principal falha antes da primeira palavra ===')
        from ai import chat_services

        def turno(principal):
            sessao = ChatSession.objects.create(
                tenant=tenant, owner_user=doctor.user, patient=None, title='roteiro reserva',
            )
            sessoes.append(sessao.id)
            pergunta = chat_services.post_user_message(sessao, 'Como bloqueio um horário?')
            resposta = chat_services.start_assistant_message(sessao)
            reserva = MagicMock(side_effect=lambda: Reserva())
            with patch('ai.tasks.get_chat_model', return_value=principal), \
                    patch('ai.tasks.installation_reserve_model', reserva), \
                    patch('ai.tasks.publish_event'):
                retorno = tasks.run_chat_turn(str(resposta.id), str(pergunta.id))
            resposta.refresh_from_db()
            return retorno, resposta, reserva.call_count

        antes = usos()
        retorno, resposta, chamadas = turno(Falha())
        print(f'  status={retorno.get("status")}  texto={resposta.content!r}  reserva chamada={chamadas}')
        conferir(retorno.get('status') == 'complete' and 'reserva' in resposta.content,
                 'o chat não foi respondido pela reserva')
        conferir(usos() == antes + 1, 'o uso da reserva no chat não foi contado')

        print('=== 8. chat: depois da primeira palavra, não troca ===')
        antes = usos()
        retorno, resposta, chamadas = turno(Parcial())
        print(f'  status={retorno.get("status")}  reserva chamada={chamadas}')
        conferir(retorno.get('status') == 'failed' and chamadas == 0 and usos() == antes,
                 'o chat trocou de provedor no meio de uma resposta')

        print('=== 9. verificação da reserva decifra a chave e grava o resultado ===')
        conferido = MagicMock(return_value=(True, 'openrouter respondeu.', ['m1', 'modelo-reserva']))
        with patch('ai.tasks._conferir_provedor', conferido):
            resultado = tasks.verificar_reserva_da_instalacao()
        linha = InstallationSettings.carregar()
        chave_usada = conferido.call_args.args[3] if conferido.call_args else None
        print(f'  ok={resultado.get("ok")}  modelos={linha.ai_reserva_modelos}')
        conferir(chave_usada == 'sk-roteiro-reserva-chave-0000',
                 'a verificação da reserva não usou a chave gravada')
        conferir(linha.ai_reserva_check_ok is True and 'modelo-reserva' in linha.ai_reserva_modelos,
                 'a verificação da reserva não gravou o resultado')

        print('=== 10. vigilância: um e-mail na falha, sem repetir a cada hora, e zera na volta ===')
        su = User.objects.create_superuser(
            email=f'su-reserva{SUFIXO}', password=None, email_verified_at=timezone.now(),
        )
        InstallationSettings.objects.filter(pk=config.pk).update(ai_alerta_enviado_em=None)
        falhou = {'ok': False, 'detalhe': 'O modelo X não está entre os 10 que nvidia oferece.'}
        with patch('ai.tasks.verificar_provedor_da_instalacao', return_value=falhou), \
                patch('ai.tasks.verificar_reserva_da_instalacao',
                      return_value={'ok': True, 'detalhe': 'ok'}), \
                patch('django.core.mail.send_mail') as envio:
            primeira = tasks.vigiar_ia_da_instalacao()
            segunda = tasks.vigiar_ia_da_instalacao()
        corpo = envio.call_args.args[1] if envio.call_args else ''
        destinos = envio.call_args.args[3] if envio.call_args else []
        print(f'  e-mails={envio.call_count}  para o superadministrador={su.email in destinos}  '
              f'diz que a reserva cobre={"seguem atendidas" in corpo}')
        conferir(envio.call_count == 1, 'a vigilância não mandou exatamente um e-mail em duas rodadas')
        conferir(su.email in destinos, 'o aviso não foi ao superadministrador')
        conferir('seguem atendidas' in corpo, 'o aviso não diz que a reserva está cobrindo')
        conferir(primeira.get('alerta') and not segunda.get('alerta'),
                 'o aviso se repetiu na hora seguinte')
        with patch('ai.tasks.verificar_provedor_da_instalacao',
                   return_value={'ok': True, 'detalhe': 'ok'}), \
                patch('ai.tasks.verificar_reserva_da_instalacao',
                      return_value={'ok': True, 'detalhe': 'ok'}), \
                patch('django.core.mail.send_mail') as envio_volta:
            tasks.vigiar_ia_da_instalacao()
        zerou = InstallationSettings.carregar().ai_alerta_enviado_em is None
        print(f'  na volta: e-mails={envio_volta.call_count}  alerta zerado={zerou}')
        conferir(zerou and envio_volta.call_count == 0, 'a volta do principal não zerou o aviso')

        print('=== 11. console: grava cifrada, nunca mostra, liga só verificada ===')
        if not TOTPDevice.objects.filter(user=su, confirmed=True).exists():
            TOTPDevice.objects.create(user=su, name='roteiro-reserva', confirmed=True)
        console = Client()
        console.force_login(su)
        requisicao = type('R', (), {'session': console.session, 'user': su})()
        otp_login(requisicao, TOTPDevice.objects.filter(user=su, confirmed=True).first())
        requisicao.session.save()
        console.cookies['sessionid'] = requisicao.session.session_key
        url = '/instalacao/operacao/provedor-de-ia/reserva/'
        chave = 'sk-or-v1-roteiro-segredo-ABCDEF123456'

        console.post(url, {'acao': 'gravar', 'provedor': 'openrouter',
                           'modelo': 'meta-llama/llama-3.3-70b-instruct', 'chave': chave})
        linha = InstallationSettings.carregar()
        pagina = console.get('/instalacao/operacao/').content.decode(errors='replace')
        print(f'  cifrada={bool(linha.ai_reserva_chave_cifrada) and chave not in linha.ai_reserva_chave_cifrada}  '
              f'dica={linha.ai_reserva_chave_dica!r}  chave na página={chave in pagina}  '
              f'ativa depois de gravar={linha.ai_reserva_ativa}')
        conferir(linha.ai_reserva_chave_cifrada and chave not in linha.ai_reserva_chave_cifrada,
                 'a chave da reserva não foi cifrada')
        conferir(linha.reserva_api_key() == chave, 'a chave cifrada não abre de volta')
        conferir(chave not in pagina, 'a chave da reserva aparece na tela do console')
        conferir('data-nd-ia-reserva' in pagina, 'o cartão da reserva não aparece no console')
        conferir(not linha.ai_reserva_ativa, 'gravar a reserva não a deixou desligada até verificar')

        console.post(url, {'acao': 'ligar'})
        recusou = not InstallationSettings.carregar().ai_reserva_ativa
        InstallationSettings.objects.filter(pk=config.pk).update(ai_reserva_check_ok=True)
        console.post(url, {'acao': 'ligar'})
        ligou = InstallationSettings.carregar().ai_reserva_ativa
        console.post(url, {'acao': 'desligar'})
        desligou = not InstallationSettings.carregar().ai_reserva_ativa
        console.post(url, {'acao': 'apagar_chave'})
        apagada = not InstallationSettings.carregar().ai_reserva_chave_cifrada
        print(f'  ligar sem verificar recusado={recusou}  ligar verificada={ligou}  '
              f'desligar={desligou}  apagar chave={apagada}')
        conferir(recusou, 'a reserva ligou sem verificação em verde')
        conferir(ligou, 'a reserva verificada não ligou')
        conferir(desligou, 'desligar a reserva não funcionou')
        conferir(apagada, 'apagar a chave da reserva não funcionou')

        trilha = set(AuditEvent.objects.filter(
            created_at__gte=inicio_trilha, action__startswith='ops.installation_ai_reserve',
        ).values_list('action', flat=True))
        sem_chave = not AuditEvent.objects.filter(
            created_at__gte=inicio_trilha, integrity_metadata__icontains='roteiro-segredo',
        ).exists()
        print(f'  na trilha: {sorted(trilha)}  sem a chave={sem_chave}')
        conferir({'ops.installation_ai_reserve_changed', 'ops.installation_ai_reserve_enabled',
                  'ops.installation_ai_reserve_disabled'} <= trilha,
                 'as mudanças da reserva não entraram na trilha')
        conferir(sem_chave, 'a trilha do console carrega a chave da reserva')

        print('=== 12. sem acesso: o console da reserva não abre para quem não é superadministrador ===')
        comum = Client()
        comum.force_login(doctor.user)
        r = comum.post(url, {'acao': 'ligar'})
        print(f'  médico -> HTTP {r.status_code}')
        conferir(r.status_code == 404, 'o console da reserva respondeu a quem não é superadministrador')

        # A OpenRouter repassa cada pedido a um de dezenas de provedores (em
        # 2026-10-22, 37 para o modelo da reserva, alguns na China). O que vai
        # para a relação de suboperadores só é verdade se o pedido da
        # instalação levar a restrição — e a chave da clínica, não.
        print('=== 13. OpenRouter da instalação: só retenção zero, sem treino, sem os excluídos ===')
        from ai.providers import ROTEAMENTO_OPENROUTER_DA_INSTALACAO as ROT, _build

        def roteamento(modelo):
            return (getattr(modelo, 'extra_body', None) or {}).get('provider')

        inst = _build('openrouter', 'x/y', 'sk-roteiro', '', da_instalacao=True)
        clin = _build('openrouter', 'x/y', 'sk-roteiro', '')
        outro = _build('openai', 'gpt-x', 'sk-roteiro', '', da_instalacao=True)
        print(f'  instalação={roteamento(inst)}  clínica={roteamento(clin)}  outro provedor={roteamento(outro)}')
        conferir(roteamento(inst) == ROT, 'a OpenRouter da instalação saiu sem a restrição de roteamento')
        conferir(ROT.get('zdr') is True and ROT.get('data_collection') == 'deny',
                 'a restrição não exige retenção zero e recusa de treino')
        conferir({'baidu', 'alibaba', 'siliconflow', 'streamlake'} <= set(ROT.get('ignore', [])),
                 'os provedores excluídos sumiram da restrição')
        conferir(roteamento(clin) is None, 'a chave da clínica recebeu o roteamento da instalação')
        conferir(roteamento(outro) is None, 'provedor que não é a OpenRouter recebeu parâmetro dela')
        from ai.providers import installation_reserve_model
        configurar_reserva(ativa=False)
        conferir(roteamento(installation_reserve_model()) == ROT,
                 'o cliente da reserva não leva a restrição de roteamento')
finally:
    restaurar()

print('---')
if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)
print('OK: a reserva assume só quando o principal falha, é contada e auditada, e a vigilância avisa.')
