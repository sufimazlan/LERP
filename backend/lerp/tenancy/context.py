"""The current tenant, held in two places that must agree.

- A context variable, read by the ORM's default managers (the second line of defence).
- The PostgreSQL setting ``app.tenant_id``, read by the row-level security policies
  (the first line). It is set with ``set_config(..., true)``, the function form of
  SET LOCAL, so it lasts only for the current transaction and survives PgBouncer's
  transaction pooling.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connections, transaction

_current_tenant: ContextVar[uuid.UUID | None] = ContextVar("lerp_tenant_id", default=None)


class TenantContextRequired(RuntimeError):
    """Tenant-scoped data was touched outside a tenant context."""


def current_tenant_id() -> uuid.UUID | None:
    return _current_tenant.get()


def require_tenant_id() -> uuid.UUID:
    tenant_id = _current_tenant.get()
    if tenant_id is None:
        raise TenantContextRequired("This operation needs a tenant context: use tenant_context().")
    return tenant_id


@contextmanager
def tenant_context(tenant, using: str = "default") -> Iterator[uuid.UUID]:
    """Run the block inside one transaction scoped to ``tenant`` (a Tenant or its id)."""
    tenant_id = getattr(tenant, "pk", tenant)
    if not isinstance(tenant_id, uuid.UUID):
        tenant_id = uuid.UUID(str(tenant_id))
    previous = _current_tenant.get()
    token = _current_tenant.set(tenant_id)
    try:
        with transaction.atomic(using=using):
            _set_database_tenant(tenant_id, using)
            yield tenant_id
            # Restore the outer context when nested. If the block raised, the rollback to
            # the savepoint restores it instead.
            _set_database_tenant(previous, using)
    finally:
        _current_tenant.reset(token)


def _set_database_tenant(tenant_id: uuid.UUID | None, using: str) -> None:
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id) if tenant_id else ""]
        )
