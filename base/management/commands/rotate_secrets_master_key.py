"""Passa os segredos da clínica da chave antiga para a `SECRETS_MASTER_KEY`.

Enquanto `SECRETS_MASTER_KEY` não existe, `base.crypto` cai na
`PFX_MASTER_KEY` — o que mantém a instalação funcionando e junta duas
finalidades que não deveriam se encontrar: comprometer a chave de SMS
passa a dar acesso ao certificado de assinatura. A tela de integrações
avisa disso.

Definir a chave separada, sozinho, **quebra** o que já estava gravado: a
chave de SMS, a senha de SMTP e a chave de IA foram embrulhadas com a
antiga, e a partir do restart nada mais as abre. Este comando é a metade
que falta — ele reembrulha as chaves de dados, da antiga para a nova.

O valor cifrado não é tocado. Quem o cifra é a chave de dados, e ela não
muda; só o embrulho troca de mestra. É exatamente para isto que o
envelope existe (ver `base.crypto`).

Ordem correta:

1. gerar a chave nova e montá-la **junto** com a antiga;
2. subir a aplicação — neste intervalo os segredos da clínica não abrem;
3. rodar este comando;
4. conferir a tela de integrações, que deixa de avisar.

Idempotente: um segredo que já abre com a nova é pulado. Interromper no
meio e rodar de novo é seguro.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from base.crypto import SecretUnavailable, rewrap_secret

#: Onde moram os segredos embrulhados por `base.crypto`.
#:
#: `documents.SigningCredential` **não** está aqui de propósito: o PFX é
#: embrulhado direto pela `PFX_MASTER_KEY` (`documents.credentials`), e é o
#: dono legítimo dela. A separação que este comando faz é justamente tirar
#: os outros segredos de perto dele.
CAMPOS = [
    ('communications.MessagingSettings', 'sms_api_key_ciphertext', 'sms_api_key_metadata',
     'chave de API do SMS'),
    ('communications.MessagingSettings', 'smtp_password_ciphertext', 'smtp_password_metadata',
     'senha de SMTP da clínica'),
    ('communications.DoctorEmailSettings', 'smtp_password_ciphertext', 'smtp_password_metadata',
     'senha de SMTP do médico'),
    ('ai.AIProviderSettings', 'api_key_ciphertext', 'api_key_metadata',
     'chave de API do provedor de IA'),
]


class Command(BaseCommand):
    help = 'Reembrulha os segredos da clínica da chave antiga para a SECRETS_MASTER_KEY.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--old-key', default=None,
            help='Chave antiga. Omitida, usa a PFX_MASTER_KEY, que é a de onde se sai.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Diz o que faria e não grava.',
        )

    def handle(self, *args, **options):
        from django.apps import apps

        nova = getattr(settings, 'SECRETS_MASTER_KEY', '')
        if not nova:
            raise CommandError(
                'SECRETS_MASTER_KEY não está definida. Gere a chave e monte-a antes — '
                'sem ela não há para onde rotacionar.'
            )
        antiga = options['old_key'] or getattr(settings, 'PFX_MASTER_KEY', '')
        if not antiga:
            raise CommandError(
                'Sem chave antiga: nem --old-key nem PFX_MASTER_KEY. Não há de onde sair.'
            )
        if antiga == nova:
            raise CommandError(
                'A chave nova é igual à antiga. Rotacionar para a mesma chave não '
                'separa nada — gere uma chave própria para SECRETS_MASTER_KEY.'
            )

        seco = options['dry_run']
        movidos = pulados = 0
        problemas = []

        for rotulo_modelo, campo_texto, campo_meta, descricao in CAMPOS:
            modelo = apps.get_model(rotulo_modelo)
            linhas = modelo.objects.exclude(**{campo_texto: ''})
            for linha in linhas:
                metadata = getattr(linha, campo_meta) or {}
                try:
                    novo_meta, mudou = rewrap_secret(metadata, antiga, nova)
                except SecretUnavailable as exc:
                    # Não interrompe: um segredo perdido é um a reinformar
                    # pela tela, e parar aqui deixaria os demais sem
                    # rotacionar — todos quebrados em vez de um.
                    problemas.append(
                        f'{descricao} de {linha.tenant_id}: {exc}',
                    )
                    continue
                if not mudou:
                    pulados += 1
                    continue
                movidos += 1
                if not seco:
                    setattr(linha, campo_meta, novo_meta)
                    linha.save(update_fields=[campo_meta])
                self.stdout.write(f'  {descricao} — {linha.tenant_id}')

        prefixo = '(simulação) ' if seco else ''
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'{prefixo}{movidos} segredo(s) reembrulhado(s), {pulados} já estava(m) na chave nova.'
        ))
        if problemas:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Estes não abriram com nenhuma das duas chaves e precisam ser '
                'informados de novo na tela de integrações:'
            ))
            for p in problemas:
                self.stdout.write(f'  - {p}')
