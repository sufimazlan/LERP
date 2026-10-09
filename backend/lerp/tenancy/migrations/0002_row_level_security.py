from django.db import migrations

from lerp.tenancy.rls import enable_row_level_security, same_tenant_foreign_key


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0001_initial")]

    operations = [
        enable_row_level_security("tenancy_legalentity"),
        enable_row_level_security("tenancy_rolegrant"),
        same_tenant_foreign_key("tenancy_rolegrant", "legal_entity_id", "tenancy_legalentity"),
    ]
