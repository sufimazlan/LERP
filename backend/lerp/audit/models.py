import hashlib
import json

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from lerp.tenancy.models import TenantScopedModel


def canonical_json(value) -> str:
    return json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))


class AuditEvent(TenantScopedModel):
    """One entry in a tenant's append-only, hash-chained audit trail (plan section 5.5).

    Each event's hash covers its content and the previous event's hash, so editing or
    removing any event breaks every hash after it. A database trigger rejects UPDATE
    and DELETE for every role, the app's included.
    """

    seq = models.PositiveBigIntegerField()
    occurred_at = models.DateTimeField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    data = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "seq"], name="auditevent_seq_uniq")
        ]

    def __str__(self) -> str:
        return f"#{self.seq} {self.action} {self.object_type}:{self.object_id}"

    def compute_hash(self) -> str:
        payload = {
            "tenant": str(self.tenant_id),
            "seq": self.seq,
            "occurred_at": self.occurred_at.isoformat(),
            "actor": self.actor_id,
            "action": self.action,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "data": self.data,
            "prev_hash": self.prev_hash,
        }
        return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
