import json

from django.db import connection, transaction
from django.utils import timezone

from lerp.audit.models import AuditEvent, canonical_json
from lerp.tenancy.context import require_tenant_id

GENESIS_HASH = "0" * 64


def record(action: str, *, object_type: str, object_id, actor=None, data=None) -> AuditEvent:
    """Append an event to the current tenant's audit chain."""
    tenant_id = require_tenant_id()
    # Store exactly what was hashed: round-trip through JSON so Decimals, dates and UUIDs
    # come back from the database in the same form.
    data = json.loads(canonical_json(data or {}))
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Serialise appends per tenant so two writers never claim the same seq.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"audit:{tenant_id}"]
            )
        last = AuditEvent.objects.order_by("-seq").only("seq", "hash").first()
        event = AuditEvent(
            tenant_id=tenant_id,
            seq=last.seq + 1 if last else 1,
            occurred_at=timezone.now(),
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            data=data,
            prev_hash=last.hash if last else GENESIS_HASH,
        )
        event.hash = event.compute_hash()
        event.save()
    return event


def verify_chain() -> int | None:
    """Return the seq of the first broken event in the current tenant's chain, or None."""
    require_tenant_id()
    expected_prev = GENESIS_HASH
    expected_seq = 1
    for event in AuditEvent.objects.order_by("seq").iterator():
        if (
            event.seq != expected_seq
            or event.prev_hash != expected_prev
            or event.hash != event.compute_hash()
        ):
            return event.seq
        expected_prev = event.hash
        expected_seq += 1
    return None
