"""An in-memory ledger for development, demos and the adapter contract tests.

It honours the same rules a real adapter must: balanced journals only, closed periods
refuse postings, and a repeated external reference is the same command.
"""

from datetime import date
from decimal import Decimal

from lerp.ledger.ports import (
    Balances,
    DraftPurchaseInvoice,
    EInvoiceStatus,
    IdempotencyConflict,
    Item,
    Journal,
    LedgerError,
    OpenItem,
    Party,
    PeriodClosed,
    PeriodStatus,
    PostingResult,
)


class InMemoryLedger:
    def __init__(self):
        self.parties: dict[tuple[str, str], Party] = {}
        self.items: dict[tuple[str, str], Item] = {}
        self.invoices: dict[str, DraftPurchaseInvoice] = {}
        self.journals: dict[str, Journal] = {}
        self.closed_periods: set[tuple[str, int, int]] = set()
        self.einvoices: dict[tuple[str, str], EInvoiceStatus] = {}

    # Test and demo helpers; real ledgers manage these themselves.
    def close_period(self, entity_code: str, year: int, month: int) -> None:
        self.closed_periods.add((entity_code, year, month))

    def set_einvoice_status(self, entity_code: str, document_ref: str, status: EInvoiceStatus):
        self.einvoices[(entity_code, document_ref)] = status

    # LedgerPort
    def upsert_party(self, entity_code: str, party: Party) -> str:
        self.parties[(entity_code, party.code)] = party
        return party.code

    def upsert_item(self, entity_code: str, item: Item) -> str:
        self.items[(entity_code, item.code)] = item
        return item.code

    def create_draft_purchase_invoice(self, invoice: DraftPurchaseInvoice) -> PostingResult:
        if (invoice.entity_code, invoice.supplier_code) not in self.parties:
            raise LedgerError(f"Unknown supplier {invoice.supplier_code!r}.")
        return self._idempotent(self.invoices, invoice.external_ref, invoice, "PINV")

    def post_journal(self, journal: Journal) -> PostingResult:
        journal.validate()
        if self.period_status(journal.entity_code, journal.posting_date) is PeriodStatus.CLOSED:
            raise PeriodClosed(f"{journal.posting_date:%Y-%m} is closed for {journal.entity_code}.")
        return self._idempotent(self.journals, journal.external_ref, journal, "JV")

    def open_items(self, entity_code: str, party_code: str | None = None) -> list[OpenItem]:
        return [
            OpenItem(inv.supplier_code, inv.invoice_number, inv.due_date, inv.total, inv.currency)
            for inv in self.invoices.values()
            if inv.entity_code == entity_code and party_code in (None, inv.supplier_code)
        ]

    def balances(self, entity_code: str, as_of: date) -> Balances:
        by_account: dict[str, Decimal] = {}
        for journal in self.journals.values():
            if journal.entity_code != entity_code or journal.posting_date > as_of:
                continue
            for line in journal.lines:
                by_account[line.account] = (
                    by_account.get(line.account, Decimal(0)) + line.debit - line.credit
                )
        return Balances(entity_code, as_of, by_account)

    def period_status(self, entity_code: str, on: date) -> PeriodStatus:
        if (entity_code, on.year, on.month) in self.closed_periods:
            return PeriodStatus.CLOSED
        return PeriodStatus.OPEN

    def einvoice_status(self, entity_code: str, document_ref: str) -> EInvoiceStatus:
        return self.einvoices.get((entity_code, document_ref), EInvoiceStatus.NOT_REQUIRED)

    @staticmethod
    def _idempotent(store: dict, external_ref: str, command, prefix: str) -> PostingResult:
        ledger_ref = f"{prefix}-{external_ref}"
        existing = store.get(external_ref)
        if existing is not None:
            if existing != command:
                raise IdempotencyConflict(f"{external_ref!r} was already used for another command.")
            return PostingResult(ledger_ref, created=False)
        store[external_ref] = command
        return PostingResult(ledger_ref, created=True)
