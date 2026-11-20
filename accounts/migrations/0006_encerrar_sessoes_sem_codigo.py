"""Encerra, uma vez, as sessões que nunca passaram pelo código.

Até 2026-11-20 o `/admin/login/` abria sessão só com a senha, e a tela de
configurar o segundo fator transformava essa sessão em verificada. As duas
portas foram fechadas no código; esta migração fecha o que ficou aberto
antes delas: toda sessão de quem tem segundo fator confirmado e que não
traz a marca do código (`otp_device_id`) é apagada. A pessoa entra de novo,
pelo login que pede o código. Sessões de quem não tem segundo fator, e as
verificadas, ficam (auditoria externa de 2026-11-20).

Sem volta: apagar sessão não tem o que desfazer.
"""
from django.db import migrations
from django.utils import timezone


def encerrar(apps, schema_editor):
    from django.contrib.sessions.backends.db import SessionStore

    Session = apps.get_model('sessions', 'Session')
    TOTPDevice = apps.get_model('otp_totp', 'TOTPDevice')
    com_codigo = {str(u) for u in TOTPDevice.objects.filter(confirmed=True).values_list('user_id', flat=True)}
    if not com_codigo:
        return
    decodificador = SessionStore()
    apagar = []
    for sessao in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        try:
            dados = decodificador.decode(sessao.session_data)
        except Exception:                                   # noqa: BLE001
            continue
        if str(dados.get('_auth_user_id', '')) in com_codigo and not dados.get('otp_device_id'):
            apagar.append(sessao.session_key)
    Session.objects.filter(session_key__in=apagar).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_dispositivoconfiavel'),
        ('sessions', '0001_initial'),
        ('otp_totp', '0001_initial'),
    ]

    operations = [migrations.RunPython(encerrar, migrations.RunPython.noop)]
