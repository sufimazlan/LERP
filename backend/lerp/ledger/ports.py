"""LedgerPort: the single boundary between LERP and the books (plan section 5.1).

The ledger (the pilot's existing system, or a bundled ERPNext) stays the system of
record for posted journals, balances, tax and statutory reports. LERP talks to it only
through this interface, with one adapter per ledger, so ledgers can be swapped or added
without touching the rest of the platform.

Every command carries an external reference. Adapters must treat a repeat of the same
reference as the same command (idempotency), so a retried posting never posts twice.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class LedgerError(Exception):
    pass


class UnbalancedJournal(LedgerError):
    pass


class PeriodClosed(LedgerError):
    pass


class IdempotencyConflict(LedgerError):
    """An external reference was reused for a different command."""


class PeriodStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class EInvoiceStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Party:
    code: str
    name: str
    kind: str  # "supplier" or "customer"
    tax_id: str = ""


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    uom: str = "unit"


@dataclass(frozen=True)
class InvoiceLine:
    description: str
    amount: Decimal
    account: str
    tax_code: str = ""


@dataclass(frozen=True)
class DraftPurchaseInvoice:
    external_ref: str
    entity_code: str
    supplier_code: str
    invoice_number: str
    invoice_date: date
    due_date: date
    currency: str
    lines: tuple[InvoiceLine, ...]

    @property
    def total(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal(0))


@dataclass(frozen=True)
class JournalLine:
    account: str
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    memo: str = ""


@dataclass(frozen=True)
class Journal:
    external_ref: str
    entity_code: str
    posting_date: date
    currency: str
    lines: tuple[JournalLine, ...]
    memo: str = ""

    def validate(self) -> None:
        if len(self.lines) < 2:
            raise UnbalancedJournal("A journal needs at least two lines.")
        for line in self.lines:
            if not isinstance(line.debit, Decimal) or not isinstance(line.credit, Decimal):
                raise TypeError("Journal amounts must be Decimal, never float.")
            if line.debit < 0 or line.credit < 0 or (line.debit > 0) == (line.credit > 0):
                raise UnbalancedJournal(
                    f"Line {line.account!r} must have exactly one positive side."
                )
        debits = sum((line.debit for line in self.lines), Decimal(0))
        credits = sum((line.credit for line in self.lines), Decimal(0))
        if debits != credits:
            raise UnbalancedJournal(f"Debits {debits} do not equal credits {credits}.")


@dataclass(frozen=True)
class PostingResult:
    ledger_ref: str
    created: bool  # False when the external reference had already been posted


@dataclass(frozen=True)
class OpenItem:
    party_code: str
    document_ref: str
    due_date: date
    amount_outstanding: Decimal
    currency: str


@dataclass(frozen=True)
class Balances:
    entity_code: str
    as_of: date
    by_account: dict[str, Decimal] = field(default_factory=dict)  # debit positive


class LedgerPort(Protocol):
    def upsert_party(self, entity_code: str, party: Party) -> str: ...

    def upsert_item(self, entity_code: str, item: Item) -> str: ...

    def create_draft_purchase_invoice(self, invoice: DraftPurchaseInvoice) -> PostingResult: ...

    def post_journal(self, journal: Journal) -> PostingResult: ...

    def open_items(self, entity_code: str, party_code: str | None = None) -> list[OpenItem]: ...

    def balances(self, entity_code: str, as_of: date) -> Balances: ...

    def period_status(self, entity_code: str, on: date) -> PeriodStatus: ...

    def einvoice_status(self, entity_code: str, document_ref: str) -> EInvoiceStatus: ...
