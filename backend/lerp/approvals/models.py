"""Approval engine: versioned decision tables plus maker-checker (plan section 5.3, layer 3).

A policy is a decision table for one document type: amount bands, each naming the role
that must approve and how many approvals it takes. Policies are versioned; a running
request keeps the version it started on.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from lerp.tenancy.models import LegalEntity, Role, TenantScopedModel


class ApprovalPolicy(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    document_type = models.CharField(max_length=50)
    version = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="MYR")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    activated_at = models.DateTimeField(null=True)

    class Meta:
        verbose_name_plural = "approval policies"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "id"], name="approvalpolicy_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=["tenant", "document_type", "version"], name="approvalpolicy_version_uniq"
            ),
            models.UniqueConstraint(
                fields=["tenant", "document_type"],
                condition=Q(status="active"),
                name="approvalpolicy_one_active",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document_type} v{self.version} ({self.status})"


class ApprovalRule(TenantScopedModel):
    """One amount band: min_amount <= amount < max_amount (no max means no upper limit)."""

    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.PROTECT, related_name="rules")
    min_amount = models.DecimalField(max_digits=18, decimal_places=2)
    max_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    required_role = models.CharField(max_length=32, choices=Role.choices)
    approvals_required = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["min_amount"]
        constraints = [
            models.CheckConstraint(
                condition=Q(min_amount__gte=0)
                & (Q(max_amount__isnull=True) | Q(max_amount__gt=F("min_amount"))),
                name="approvalrule_band_valid",
            ),
            models.CheckConstraint(
                condition=Q(approvals_required__gte=1), name="approvalrule_needs_approver"
            ),
        ]

    def __str__(self) -> str:
        upper = self.max_amount if self.max_amount is not None else "∞"
        return f"{self.min_amount}–{upper}: {self.approvals_required} × {self.required_role}"


class ApprovalRequest(TenantScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    legal_entity = models.ForeignKey(LegalEntity, on_delete=models.PROTECT, related_name="+")
    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.PROTECT, related_name="+")
    document_type = models.CharField(max_length=50)
    document_ref = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    # Copied from the matching rule when the request is submitted.
    required_role = models.CharField(max_length=32, choices=Role.choices)
    approvals_required = models.PositiveSmallIntegerField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "id"], name="approvalrequest_tenant_id_uniq"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="approvalrequest_amount_gte_0"),
        ]

    def __str__(self) -> str:
        return f"{self.document_type} {self.document_ref} {self.currency} {self.amount}"


class ApprovalDecision(TenantScopedModel):
    request = models.ForeignKey(ApprovalRequest, on_delete=models.PROTECT, related_name="decisions")
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    approved = models.BooleanField()
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "approver"], name="approvaldecision_once")
        ]

    def __str__(self) -> str:
        return f"{self.approver} {'approved' if self.approved else 'rejected'} {self.request}"
