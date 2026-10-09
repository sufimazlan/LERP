from django.conf import settings
from django.db import models

from lerp.tenancy.models import TenantScopedModel


class AIUsage(TenantScopedModel):
    """One metered model call: what ran, for which task, and what it cost."""

    occurred_at = models.DateTimeField(auto_now_add=True)
    task = models.CharField(max_length=64)
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=100)
    is_local = models.BooleanField()
    data_class = models.CharField(max_length=16)
    input_tokens = models.PositiveIntegerField()
    output_tokens = models.PositiveIntegerField()
    cost_myr = models.DecimalField(max_digits=12, decimal_places=6)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )

    class Meta:
        verbose_name = "AI usage"
        verbose_name_plural = "AI usage"
        indexes = [models.Index(fields=["tenant", "occurred_at"], name="aiusage_tenant_time_idx")]

    def __str__(self) -> str:
        return f"{self.task} via {self.model}: RM {self.cost_myr}"
