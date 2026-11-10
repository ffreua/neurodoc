"""Carrega a CID-11 da tabulação simples da OMS (planilha em português).

A instalação já recebe a CID-11 sozinha, na subida, da planilha que vem no
repositório (`catalogs.cid.ensure_cid11`). Este comando é para a **versão
seguinte**: quando a OMS publicar uma nova, baixe a "Simple Tabulation" em
português de icd.who.int e rode

    docker compose exec app python manage.py import_cid11 \
        --arquivo /caminho/SimpleTabulation-ICD-11-MMS-pt.xlsx --versao 2026-01 --dry-run

Com `--dry-run` a planilha é lida e conferida sem gravar. Sem ele, a
versão nova é gravada ao lado da anterior e passa a ser a ativa; a
anterior fica como substituída, e o que já foi registrado no prontuário
não muda — a hipótese guarda o código e a descrição do dia em que foi
escrita.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from catalogs import cid


class Command(BaseCommand):
    help = 'Carrega a CID-11 (tabulação simples da OMS, em português).'

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default=str(cid.CID11_ARQUIVO), help='Planilha .xlsx da OMS.')
        parser.add_argument('--versao', default=cid.CID11_VERSAO, help='Versão da classificação (ex.: 2025-01).')
        parser.add_argument('--dry-run', action='store_true', help='Lê e confere, sem gravar.')

    def handle(self, *args, **opcoes):
        arquivo, versao = opcoes['arquivo'], opcoes['versao']
        # O SHA-256 conferido é o da planilha que vem no repositório; outra
        # planilha é outra versão, e quem a trouxe responde por ela.
        da_casa = arquivo == str(cid.CID11_ARQUIVO) and versao == cid.CID11_VERSAO
        try:
            if opcoes['dry_run']:
                linhas = cid.ler_planilha(arquivo)
                self.stdout.write(f'{len(linhas)} códigos lidos; nada foi gravado.')
                return
            release, total = cid.importar(arquivo, versao, cid.CID11_SHA256 if da_casa else '')
        except FileNotFoundError as exc:
            raise CommandError(f'Planilha não encontrada: {arquivo}') from exc
        except cid.PlanilhaInvalida as exc:
            raise CommandError(str(exc)) from exc
        except IntegrityError as exc:
            raise CommandError(f'A versão {versao} da CID-11 já foi carregada.') from exc
        self.stdout.write(self.style.SUCCESS(f'CID-11 {release.version} ativa, com {total} códigos.'))
