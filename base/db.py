from django.db import migrations


def composite_tenant_foreign_key(child_table, child_fk_column, parent_table, constraint_name):
    """Build forward/reverse RunSQL operations enforcing that a child row's
    (tenant_id, <fk>) pair references an existing (tenant_id, id) pair on the
    parent table, so a row cannot reference an object from another tenant.

    ``parent_table`` must already carry a UNIQUE(tenant_id, id) constraint,
    which every TenantModel subclass gets automatically (base.models.TenantModel).
    """
    forward = (
        f'ALTER TABLE {child_table} '
        f'ADD CONSTRAINT {constraint_name} '
        f'FOREIGN KEY (tenant_id, {child_fk_column}) '
        f'REFERENCES {parent_table} (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE'
    )
    reverse = f'ALTER TABLE {child_table} DROP CONSTRAINT {constraint_name}'
    return migrations.RunSQL(sql=forward, reverse_sql=reverse)
