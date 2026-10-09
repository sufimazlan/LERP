"""Which LedgerPort adapter serves which tenant, chosen by Tenant.ledger_adapter."""

from collections.abc import Callable

from lerp.ledger.memory import InMemoryLedger
from lerp.ledger.ports import LedgerPort

_factories: dict[str, Callable[[object], LedgerPort]] = {}
_memory_ledgers: dict[object, InMemoryLedger] = {}


def register(name: str, factory: Callable[[object], LedgerPort]) -> None:
    """Register an adapter factory, called with the tenant (e.g. to read its credentials)."""
    _factories[name] = factory


def ledger_for(tenant) -> LedgerPort:
    try:
        factory = _factories[tenant.ledger_adapter]
    except KeyError:
        raise LookupError(f"No ledger adapter named {tenant.ledger_adapter!r}.") from None
    return factory(tenant)


register("memory", lambda tenant: _memory_ledgers.setdefault(tenant.pk, InMemoryLedger()))
