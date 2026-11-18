"""Descarta o material dos certificados revogados antes da correção de 2026-11-17.

Até então revogar só trocava o status, e o PFX cifrado e a chave embrulhada
ficavam (`documents.credentials.descartar_material`). A revogação nova já
descarta; este comando alcança as antigas. Idempotente.

Roda no `app`, que é quem monta o volume de assinatura.
"""

from django.core.management.base import BaseCommand

from documents.credentials import descartar_material
from documents.models import SigningCredential, SigningCredentialStatus


class Command(BaseCommand):
    help = 'Apaga PFX cifrado e chave embrulhada dos certificados já revogados.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Conta e não apaga.')

    def handle(self, *args, **options):
        revogados = SigningCredential.objects.filter(status=SigningCredentialStatus.REVOKED)
        descartados = 0
        for credencial in revogados:
            if 'descartada_em' in (credencial.wrapped_key_metadata or {}):
                continue
            descartados += 1
            if not options['dry_run']:
                descartar_material(credencial)
        prefixo = '(simulação) ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefixo}{descartados} certificado(s) revogado(s) descartado(s).'
        ))
