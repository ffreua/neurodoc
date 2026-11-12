"""Confere se houve backup completo nas últimas 26 horas.

**O aviso de falha só cobria o backup que roda e falha** (auditoria de
2026-11-11). Timer desligado, unidade não reinstalada depois de um
`setup_deploy`, systemd que não disparou: nada disso é falha do serviço do
backup — ele simplesmente não roda —, e nenhum e-mail saía. A cópia
externa no SSD também não reclamava: copiava o que havia, e o que havia
era cada vez mais velho.

Esta conferência roda pelo seu próprio timer
(`neurodoc-backup-vigia.timer`), separada do backup de propósito: um vigia
que dependesse do mesmo timer morreria junto com ele. Saindo com erro, o
`OnFailure=` manda o mesmo e-mail do backup que falhou.

Lê a data do arquivo `COMPLETE`, que `ops/backup.py` só escreve no fim de
um backup inteiro.
"""
import sys
import time
from pathlib import Path

from ops.deploy import configuration

#: Um dia e duas horas: o backup roda às 03h00 com até dez minutos de
#: atraso sorteado e pode esperar trava por quase uma hora e meia.
IDADE_MAXIMA_HORAS = 26


def main():
    raiz = Path(configuration()['BACKUP_DIR'])
    marcas = list(raiz.glob('*/COMPLETE')) if raiz.is_dir() else []
    if not marcas:
        print(f'NAO HA BACKUP COMPLETO em {raiz}.', file=sys.stderr)
        return 1
    mais_novo = max(m.stat().st_mtime for m in marcas)
    horas = (time.time() - mais_novo) / 3600
    if horas > IDADE_MAXIMA_HORAS:
        print(
            f'O BACKUP COMPLETO MAIS RECENTE TEM {horas:.0f} HORAS (limite {IDADE_MAXIMA_HORAS}). '
            'Confira: systemctl list-timers neurodoc-backup.timer; '
            'journalctl -u neurodoc-backup.service -n 50',
            file=sys.stderr,
        )
        return 1
    print(f'Backup completo mais recente: {horas:.1f} h.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
