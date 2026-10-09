from decimal import Decimal

import pytest
from django.db import DatabaseError, connection, transaction

from lerp.audit import services as audit
from lerp.audit.models import AuditEvent
from lerp.tenancy.context import TenantContextRequired, tenant_context

pytestmark = pytest.mark.django_db


def test_events_form_a_verifiable_chain_per_tenant(tenant_a, tenant_b, make_user):
    user = make_user("ann", tenant_a)
    with tenant_context(tenant_a):
        first = audit.record(
            "invoice.captured", object_type="invoice", object_id="INV-1", actor=user
        )
        second = audit.record(
            "invoice.approved",
            object_type="invoice",
            object_id="INV-1",
            data={"amount": Decimal("1234.50"), "currency": "MYR"},
        )
        assert (first.seq, second.seq) == (1, 2)
        assert second.prev_hash == first.hash
        assert audit.verify_chain() is None
    with tenant_context(tenant_b):
        assert audit.record("x", object_type="t", object_id=1).seq == 1  # separate chain
        assert AuditEvent.objects.count() == 1


def test_database_rejects_updates_and_deletes(tenant_a):
    with tenant_context(tenant_a):
        event = audit.record("invoice.captured", object_type="invoice", object_id="INV-1")
        for statement in (
            "UPDATE audit_auditevent SET action = 'x'",
            "DELETE FROM audit_auditevent",
        ):
            with pytest.raises(DatabaseError, match="append-only"):
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(statement)
        with pytest.raises(DatabaseError, match="append-only"):
            with transaction.atomic():
                event.delete()


def test_tampering_is_detected(tenant_a):
    with tenant_context(tenant_a):
        for n in range(3):
            audit.record("step", object_type="doc", object_id=n)
        # Simulate an attacker with table-owner rights who disables the trigger.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")  # flush deferred FK checks first
            cursor.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER audit_event_append_only")
            cursor.execute("UPDATE audit_auditevent SET object_id = 'forged' WHERE seq = 2")
            cursor.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER audit_event_append_only")
        assert audit.verify_chain() == 2


def test_recording_needs_a_tenant():
    with pytest.raises(TenantContextRequired):
        audit.record("x", object_type="t", object_id=1)
