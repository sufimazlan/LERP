"""Migration operations for the database-level tenancy controls (plan section 5.4).

Every tenant-scoped table gets row-level security keyed on ``app.tenant_id``, forced
even for the table owner. Relationships between tenant-scoped tables get a composite
foreign key on (tenant_id, id), so no row can point at another tenant's row even if
application code tries.
"""

from django.db import migrations

POLICY_NAME = "tenant_isolation"
CURRENT_TENANT_SQL = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def enable_row_level_security(table: str) -> migrations.RunSQL:
    return migrations.RunSQL(
        sql=[
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY {POLICY_NAME} ON {table} "
            f"USING (tenant_id = {CURRENT_TENANT_SQL}) "
            f"WITH CHECK (tenant_id = {CURRENT_TENANT_SQL})",
        ],
        reverse_sql=[
            f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ],
    )


def same_tenant_foreign_key(table: str, column: str, target_table: str) -> migrations.RunSQL:
    """Require ``table.column`` to reference a ``target_table`` row of the same tenant.

    The target needs a unique constraint on (tenant, id).
    """
    name = f"{table}_{column}_same_tenant"
    return migrations.RunSQL(
        sql=(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY (tenant_id, {column}) REFERENCES {target_table} (tenant_id, id)"
        ),
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )
