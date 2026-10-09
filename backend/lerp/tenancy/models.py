"""Tenancy: platform → tenant → legal entity (plan section 5.4).

A tenant is a customer contract and the isolation boundary. A legal entity has its own
books, tax IDs and currency; a group of companies is one tenant with many entities.

Tenant and Membership form the platform-level registry and are read to establish the
tenant context, so they have no row-level security. Everything else extends
TenantScopedModel and lives under it.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from lerp.ids import uuid7
from lerp.tenancy.context import current_tenant_id, require_tenant_id


class Tenant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    class AIMode(models.TextChoices):
        OFF = "off", "Off"
        LOCAL_ONLY = "local_only", "Local models only"
        HYBRID = "hybrid", "Local and hosted models"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    slug = models.SlugField(max_length=63, unique=True)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    # Registry fields: where the tenant lives and what it may use. Moving a tenant from
    # the shared database to its own is a data copy plus a change to db_alias.
    db_alias = models.CharField(max_length=63, default="default")
    region = models.CharField(max_length=8, default="my")
    ledger_adapter = models.CharField(max_length=32, default="memory")
    ai_mode = models.CharField(max_length=16, choices=AIMode.choices, default=AIMode.OFF)
    ai_monthly_budget_myr = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    """One identity, one membership per tenant. Roles are granted per legal entity."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="memberships")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant"], name="membership_user_tenant_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.tenant}"


class TenantManager(models.Manager):
    """Scopes every query to the current tenant, and returns nothing without one."""

    def get_queryset(self):
        tenant_id = current_tenant_id()
        queryset = super().get_queryset()
        return queryset.none() if tenant_id is None else queryset.filter(tenant_id=tenant_id)


class TenantScopedModel(models.Model):
    """Base for every tenant-owned table. Its migration must call enable_row_level_security."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+", editable=False)

    objects = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        tenant_id = require_tenant_id()
        if self.tenant_id is None:
            self.tenant_id = tenant_id
        elif self.tenant_id != tenant_id:
            raise ValueError("Refusing to write a row that belongs to another tenant.")
        super().save(*args, **kwargs)


class LegalEntity(TenantScopedModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    registration_no = models.CharField(max_length=40, blank=True)  # SSM number
    tax_id = models.CharField(max_length=40, blank=True)  # LHDN TIN
    base_currency = models.CharField(max_length=3, default="MYR")

    class Meta:
        verbose_name_plural = "legal entities"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="legalentity_code_uniq"),
            models.UniqueConstraint(fields=["tenant", "id"], name="legalentity_tenant_id_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class Role(models.TextChoices):
    TENANT_ADMIN = "tenant_admin", "Tenant admin"
    AP_CLERK = "ap_clerk", "AP clerk"
    APPROVER = "approver", "Approver"
    FINANCE_MANAGER = "finance_manager", "Finance manager"
    CFO = "cfo", "CFO"
    AUDITOR = "auditor", "Auditor"


class RoleGrant(TenantScopedModel):
    """A role for a user, for one legal entity or (legal_entity empty) the whole tenant."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    legal_entity = models.ForeignKey(
        LegalEntity, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    role = models.CharField(max_length=32, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user", "legal_entity", "role"],
                name="rolegrant_uniq",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} {self.role} {self.legal_entity or 'all entities'}"


def has_role(user, role: str, legal_entity: LegalEntity | None = None) -> bool:
    """Whether ``user`` holds ``role`` in the current tenant.

    Without a legal entity only a tenant-wide grant counts; with one, a grant for that
    entity or a tenant-wide grant does.
    """
    grants = RoleGrant.objects.filter(user=user, role=role)
    if legal_entity is None:
        grants = grants.filter(legal_entity__isnull=True)
    else:
        grants = grants.filter(Q(legal_entity__isnull=True) | Q(legal_entity=legal_entity))
    return grants.exists()
