"""The contract every LedgerPort adapter must pass. Add each new adapter to ADAPTERS."""

from datetime import date
from decimal import Decimal

import pytest

from lerp.ledger.memory import InMemoryLedger
from lerp.ledger.ports import (
    DraftPurchaseInvoice,
    IdempotencyConflict,
    InvoiceLine,
    Journal,
    JournalLine,
    Party,
    PeriodClosed,
    PeriodStatus,
    UnbalancedJournal,
)

ADAPTERS = {"memory": InMemoryLedger}


@pytest.fixture(params=sorted(ADAPTERS))
def ledger(request):
    return ADAPTERS[request.param]()


def journal(ref="JV-1", debit="100.00", credit="100.00", on=date(2026, 10, 9)) -> Journal:
    return Journal(
        external_ref=ref,
        entity_code="HQ",
        posting_date=on,
        currency="MYR",
        lines=(
            JournalLine("6100-office", debit=Decimal(debit)),
            JournalLine("2100-ap", credit=Decimal(credit)),
        ),
    )


def test_posting_is_idempotent(ledger):
    first = ledger.post_journal(journal())
    again = ledger.post_journal(journal())
    assert first.created and not again.created
    assert first.ledger_ref == again.ledger_ref
    balances = ledger.balances("HQ", date(2026, 10, 31)).by_account
    assert balances == {"6100-office": Decimal("100.00"), "2100-ap": Decimal("-100.00")}


def test_reusing_a_reference_for_different_content_is_refused(ledger):
    ledger.post_journal(journal())
    with pytest.raises(IdempotencyConflict):
        ledger.post_journal(journal(debit="200.00", credit="200.00"))


@pytest.mark.parametrize(
    "lines",
    [
        (JournalLine("a", debit=Decimal("100")), JournalLine("b", credit=Decimal("99.99"))),
        (JournalLine("a", debit=Decimal("100")),),
        (
            JournalLine("a", debit=Decimal("100"), credit=Decimal("100")),
            JournalLine("b", credit=Decimal("0")),
        ),
        (JournalLine("a", debit=Decimal("-5")), JournalLine("b", credit=Decimal("-5"))),
    ],
)
def test_unbalanced_or_malformed_journals_are_refused(ledger, lines):
    bad = Journal("JV-X", "HQ", date(2026, 10, 9), "MYR", lines)
    with pytest.raises(UnbalancedJournal):
        ledger.post_journal(bad)


def test_float_amounts_are_refused(ledger):
    lines = (JournalLine("a", debit=100.0), JournalLine("b", credit=100.0))
    with pytest.raises(TypeError):
        ledger.post_journal(Journal("JV-F", "HQ", date(2026, 10, 9), "MYR", lines))


def test_closed_period_refuses_postings(ledger):
    if not hasattr(ledger, "close_period"):
        pytest.skip("adapter has no test hook for closing periods")
    ledger.close_period("HQ", 2026, 9)
    assert ledger.period_status("HQ", date(2026, 9, 30)) is PeriodStatus.CLOSED
    with pytest.raises(PeriodClosed):
        ledger.post_journal(journal(on=date(2026, 9, 30)))
    assert ledger.post_journal(journal(on=date(2026, 10, 1))).created


def test_draft_invoice_becomes_an_open_item(ledger):
    ledger.upsert_party("HQ", Party(code="SUP-1", name="Kedai Alat Tulis", kind="supplier"))
    invoice = DraftPurchaseInvoice(
        external_ref="INV-1",
        entity_code="HQ",
        supplier_code="SUP-1",
        invoice_number="A-1001",
        invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 31),
        currency="MYR",
        lines=(
            InvoiceLine("Paper", Decimal("80.00"), "6100-office", "SST-ST"),
            InvoiceLine("Pens", Decimal("20.00"), "6100-office", "SST-ST"),
        ),
    )
    assert ledger.create_draft_purchase_invoice(invoice).created
    assert not ledger.create_draft_purchase_invoice(invoice).created
    [item] = ledger.open_items("HQ", "SUP-1")
    assert (item.document_ref, item.amount_outstanding) == ("A-1001", Decimal("100.00"))
