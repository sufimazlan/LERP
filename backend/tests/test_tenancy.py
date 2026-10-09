"""Cross-tenant isolation (gate G1 in section 12 of the plan: zero leaks)."""

import pytest
from django.apps import apps
from django.db import IntegrityError, ProgrammingError, connection, transaction

from lerp.ids import uuid7
from lerp.tenancy.context import TenantContextRequired, current_tenant_id, tenant_context
from lerp.tenancy.models import LegalEntity, Role, TenantScopedModel, has_role
from lerp.tenancy.rls import POLICY_NAME

pytestmark = pytest.mark.django_db


def raw_names() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM tenancy_legalentity ORDER BY name")
        return [row[0] for row in cursor.fetchall()]


def test_database_role_cannot_bypass_row_level_security():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone() == (False, False), (
            "Run tests as a role without SUPERUSER/BYPASSRLS"
        )


def test_every_tenant_scoped_table_has_forced_row_level_security():
    tables = [
        model._meta.db_table for model in apps.get_models() if issubclass(model, TenantScopedModel)
    ]
    assert tables
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname FROM pg_class c
            WHERE c.relname = ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity
              AND EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND p.polname = %s)
            """,
            [tables, POLICY_NAME],
        )
        protected = {row[0] for row in cursor.fetchall()}
    assert set(tables) == protected


def test_each_tenant_sees_only_its_own_rows(entity_a, entity_b, tenant_a, tenant_b):
    with tenant_context(tenant_a):
        assert list(LegalEntity.objects.all()) == [entity_a]
        assert LegalEntity.objects.filter(pk=entity_b.pk).count() == 0
        # Raw SQL is filtered too: the database enforces this, not the ORM.
        assert raw_names() == ["Alpha Holdings Sdn Bhd"]
        assert LegalEntity._base_manager.filter(pk=entity_b.pk).count() == 0
    with tenant_context(tenant_b):
        assert list(LegalEntity.objects.all()) == [entity_b]


def test_no_tenant_context_sees_nothing(entity_a, entity_b):
    assert current_tenant_id() is None
    assert LegalEntity.objects.count() == 0
    assert raw_names() == []


def test_database_rejects_writes_into_another_tenant(entity_a, tenant_a, tenant_b):
    with tenant_context(tenant_a):
        with pytest.raises(ProgrammingError, match="row-level security"):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tenancy_legalentity "
                    "(id, tenant_id, code, name, registration_no, tax_id, base_currency) "
                    "VALUES (%s, %s, 'X', 'Intruder', '', '', 'MYR')",
                    [uuid7(), tenant_b.pk],
                )
        # Updates through raw SQL can't reach the other tenant's rows either.
        with connection.cursor() as cursor:
            cursor.execute("UPDATE tenancy_legalentity SET name = 'changed' WHERE code = 'HQ'")
            assert cursor.rowcount == 1
    with tenant_context(tenant_b):
        assert LegalEntity.objects.filter(name="changed").count() == 0


def test_orm_refuses_to_save_without_or_outside_the_tenant(tenant_a, tenant_b, entity_b):
    with pytest.raises(TenantContextRequired):
        LegalEntity(code="X", name="No tenant").save()
    with tenant_context(tenant_a):
        with pytest.raises(ValueError, match="another tenant"):
            entity_b.save()


def test_composite_foreign_key_blocks_cross_tenant_references(tenant_a, entity_b, make_user):
    user = make_user("eve", tenant_a)
    with tenant_context(tenant_a):
        with pytest.raises(IntegrityError, match="same_tenant"):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tenancy_rolegrant (id, tenant_id, user_id, legal_entity_id, role) "
                    "VALUES (%s, %s, %s, %s, 'approver')",
                    [uuid7(), tenant_a.pk, user.pk, entity_b.pk],
                )


def test_nested_contexts_restore_the_outer_tenant(entity_a, entity_b, tenant_a, tenant_b):
    with tenant_context(tenant_a):
        with tenant_context(tenant_b):
            assert raw_names() == ["Beta Holdings Sdn Bhd"]
            assert LegalEntity.objects.get() == entity_b
        assert raw_names() == ["Alpha Holdings Sdn Bhd"]
        assert LegalEntity.objects.get() == entity_a
        with pytest.raises(RuntimeError):
            with tenant_context(tenant_b):
                raise RuntimeError("boom")
        assert current_tenant_id() == tenant_a.pk
        assert raw_names() == ["Alpha Holdings Sdn Bhd"]


def test_role_grants_respect_entity_scope(tenant_a, entity_a, make_user):
    with tenant_context(tenant_a):
        other = LegalEntity.objects.create(code="SUB", name="Alpha Sub Sdn Bhd")
    scoped = make_user("sam", tenant_a, roles=[Role.APPROVER], legal_entity=entity_a)
    wide = make_user("wanda", tenant_a, roles=[Role.APPROVER])
    with tenant_context(tenant_a):
        assert has_role(scoped, Role.APPROVER, entity_a)
        assert not has_role(scoped, Role.APPROVER, other)
        assert not has_role(scoped, Role.APPROVER)
        assert has_role(wide, Role.APPROVER, other) and has_role(wide, Role.APPROVER)
        assert not has_role(wide, Role.CFO, entity_a)


def test_uuid7_is_time_ordered():
    first, second = uuid7(), uuid7()
    assert first.version == 7
    assert first.hex[:12] <= second.hex[:12]
