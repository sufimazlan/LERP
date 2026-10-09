from django.db import migrations

from lerp.tenancy.rls import enable_row_level_security, same_tenant_foreign_key


class Migration(migrations.Migration):
    dependencies = [("approvals", "0001_initial"), ("tenancy", "0002_row_level_security")]

    operations = [
        enable_row_level_security("approvals_approvalpolicy"),
        enable_row_level_security("approvals_approvalrule"),
        enable_row_level_security("approvals_approvalrequest"),
        enable_row_level_security("approvals_approvaldecision"),
        same_tenant_foreign_key("approvals_approvalrule", "policy_id", "approvals_approvalpolicy"),
        same_tenant_foreign_key(
            "approvals_approvalrequest", "legal_entity_id", "tenancy_legalentity"
        ),
        same_tenant_foreign_key(
            "approvals_approvalrequest", "policy_id", "approvals_approvalpolicy"
        ),
        same_tenant_foreign_key(
            "approvals_approvaldecision", "request_id", "approvals_approvalrequest"
        ),
    ]
