"""A trilha de auditoria passa a ser imutável **no banco**.

Até aqui ela era imutável por convenção: `record_audit_event` só insere,
o admin registra a tabela como somente-leitura e nenhuma parte do código
atualiza ou apaga uma linha. Nada disso é uma garantia — o usuário de
banco da aplicação recebia `UPDATE` e `DELETE` sobre todas as tabelas
(`ops/postgres_init.sh`), e proteger a tela não torna a tabela imutável.
Uma trilha que quem invade pode reescrever não serve para a única coisa
que uma trilha faz, que é valer contra quem a operou.

São duas defesas, de propósito:

- o **REVOKE** tira o direito do papel da aplicação, que é o que um
  ataque pela aplicação teria em mãos;
- o **trigger** recusa a alteração venha de quem vier, inclusive do dono
  do esquema e de um `psql` aberto no servidor.

Desfazer é possível e deixa rastro: `migrate audit 0002` derruba as duas,
e é o caminho a usar se algum dia uma correção de esquema precisar tocar
linhas antigas. O ponto não é tornar impossível — é tornar deliberado.
"""

from django.db import migrations

FUNCAO = """
CREATE OR REPLACE FUNCTION audit_auditevent_somente_insercao() RETURNS trigger AS $funcao$
BEGIN
    RAISE EXCEPTION 'audit_auditevent e somente-insercao: % recusado', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$funcao$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER audit_auditevent_imutavel
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_auditevent_somente_insercao();
"""

# O papel da aplicacao nao existe no ambiente local, onde o Django conecta
# como `postgres`: condicionar a existencia evita quebrar o `migrate` de
# desenvolvimento por causa de uma protecao que so faz sentido em producao.
REVOGAR = """
DO $revogar$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neurodoc_app') THEN
        REVOKE UPDATE, DELETE ON audit_auditevent FROM neurodoc_app;
    END IF;
END
$revogar$;
"""

CONCEDER = """
DO $conceder$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neurodoc_app') THEN
        GRANT UPDATE, DELETE ON audit_auditevent TO neurodoc_app;
    END IF;
END
$conceder$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0002_alter_auditevent_outcome'),
    ]

    operations = [
        migrations.RunSQL(
            sql=FUNCAO + TRIGGER + REVOGAR,
            reverse_sql=(
                'DROP TRIGGER IF EXISTS audit_auditevent_imutavel ON audit_auditevent;'
                'DROP FUNCTION IF EXISTS audit_auditevent_somente_insercao();'
                + CONCEDER
            ),
        ),
    ]
