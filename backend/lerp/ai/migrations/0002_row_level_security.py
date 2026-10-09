from django.db import migrations

from lerp.tenancy.rls import enable_row_level_security


class Migration(migrations.Migration):
    dependencies = [("ai", "0001_initial")]

    operations = [enable_row_level_security("ai_aiusage")]
