"""A trilha recusa também o `TRUNCATE`.

O gatilho da 0003 é `BEFORE UPDATE OR DELETE ... FOR EACH ROW`, e o
`TRUNCATE` não passa por gatilho de linha: o dono do esquema (o papel das
migrações, ou um `psql` aberto no servidor) esvaziava a tabela inteira num
comando, sem disparar nada. O papel da aplicação não tem `TRUNCATE`
(`ops/postgres_init.sh` só concede `SELECT, INSERT, UPDATE, DELETE`), então a
porta era a de quem opera o banco — justamente quem a trilha precisa valer
contra. Anotado na §25 do `PRE_DEPLOY_AUDIT.md` e reforçado por
@meirakalile-ship-it (2026-11-17).

O mesmo `audit_auditevent_somente_insercao()` serve: a função só levanta a
exceção, e vale para gatilho de comando como para o de linha.

Fica de fora, de propósito, o `ALTER TABLE ... DISABLE TRIGGER` pelo dono:
nenhum gatilho impede quem pode desligá-lo. Torná-lo detectável pede um
hash encadeado com o último elo guardado fora do servidor — trabalho
registrado como pendente, porque serializar toda escrita da trilha numa
trava muda o desempenho de cada transação que audita.
"""

from django.db import migrations

TRIGGER = """
CREATE TRIGGER audit_auditevent_sem_truncate
    BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_auditevent_somente_insercao();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0004_auditevent_outcome_falha'),
    ]

    operations = [
        migrations.RunSQL(
            sql=TRIGGER,
            reverse_sql='DROP TRIGGER IF EXISTS audit_auditevent_sem_truncate ON audit_auditevent;',
        ),
    ]
