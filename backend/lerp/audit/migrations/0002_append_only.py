from django.db import migrations

from lerp.tenancy.rls import enable_row_level_security


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        enable_row_level_security("audit_auditevent"),
        migrations.RunSQL(
            sql=[
                """
                CREATE FUNCTION audit_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'audit events are append-only';
                END $$
                """,
                """
                CREATE TRIGGER audit_event_append_only
                BEFORE UPDATE OR DELETE ON audit_auditevent
                FOR EACH ROW EXECUTE FUNCTION audit_reject_change()
                """,
            ],
            reverse_sql=[
                "DROP TRIGGER IF EXISTS audit_event_append_only ON audit_auditevent",
                "DROP FUNCTION IF EXISTS audit_reject_change()",
            ],
        ),
    ]
