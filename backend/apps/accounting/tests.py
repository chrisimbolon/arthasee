# =============================================================================
# === backend/apps/accounting/tests.py ===
# =============================================================================
"""
No HTTP endpoints exist for apps.accounting yet — Sprint 1 was
schema + event bus + seed command only, Phase 4 is where
apps/accounting/urls.py and real API views land. These are TestCase,
not APITestCase, and go straight at the model/manager layer
(JournalEntry.post(), Account.balance(), the seed_coa command) — the
only surface that actually exists to test right now.
"""
import uuid
from datetime import date
from decimal import Decimal

from apps.accounting import journal_generator
from apps.core.events.bus import default_bus
from apps.core.models import Outbox
from apps.inventory.events import PartConsumed
from apps.invoicing.events import InvoiceIssued
from apps.organizations.models import Organization
from apps.payments.events import PaymentReceived
from apps.workorders.events import WorkOrderCompleted
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Account, AccountingPeriod, JournalEntry, JournalLine


class SeedCoaTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")

    def test_seed_creates_every_standard_account(self):
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.assertEqual(Account.objects.filter(organization=self.org).count(), 22)
        # A handful of specific codes, not just the count — the count
        # alone wouldn't catch a wrong code silently replacing a real
        # one from the Roadmap v2.2 COA Blueprint.
        for code in ["1001", "1201", "1301", "1302", "2010", "2101", "4001", "4002", "4003", "5001"]:
            self.assertTrue(
                Account.objects.filter(organization=self.org, code=code).exists(),
                f"expected seeded account {code} to exist",
            )

    def test_seed_is_idempotent(self):
        """
        The exact real scenario this matters for — re-running the
        command after STANDARD_COA gains a new account later must
        never duplicate or overwrite anything a shop's own accountant
        has since customized.
        """
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        account_1001 = Account.objects.get(organization=self.org, code="1001")
        account_1001.name = "Kas (Customized)"
        account_1001.save(update_fields=["name"])

        call_command("seed_coa", organization=str(self.org.id), verbosity=0)

        self.assertEqual(Account.objects.filter(organization=self.org).count(), 22)
        account_1001.refresh_from_db()
        self.assertEqual(account_1001.name, "Kas (Customized)")

    def test_seed_scopes_accounts_per_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Accounting")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.assertEqual(Account.objects.filter(organization=other_org).count(), 0)


class JournalEntryPostTests(TestCase):
    """
    JournalEntry.post() is the ONE real write path (see models.py's
    own module docstring) — every one of these proves a real
    guarantee that path is supposed to hold, not incidental behavior.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.wip = Account.objects.get(organization=self.org, code="1302")
        self.inventory = Account.objects.get(organization=self.org, code="1301")
        self.ar = Account.objects.get(organization=self.org, code="1201")
        self.service_revenue = Account.objects.get(organization=self.org, code="4001")
        self.parts_revenue = Account.objects.get(organization=self.org, code="4002")

    def test_balanced_two_line_entry_posts_successfully(self):
        entry = JournalEntry.post(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.DOMAIN_EVENT, event_type="PartConsumed",
            lines=[
                {"account": self.wip, "debit": Decimal("600000")},
                {"account": self.inventory, "credit": Decimal("600000")},
            ],
        )
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(entry.entry_number, "000001")
        self.assertEqual(self.wip.balance(), Decimal("600000"))
        self.assertEqual(self.inventory.balance(), Decimal("-600000"))

    def test_balanced_three_line_split_revenue_entry_posts_successfully(self):
        """
        The exact real shape Sprint 2's InvoiceIssued handler will
        produce once revenue is split per line-item type (Roadmap
        v2.2's own fix over v2.1's single-account posting).
        """
        entry = JournalEntry.post(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.DOMAIN_EVENT, event_type="InvoiceIssued",
            lines=[
                {"account": self.ar, "debit": Decimal("2500000")},
                {"account": self.service_revenue, "credit": Decimal("2000000")},
                {"account": self.parts_revenue, "credit": Decimal("500000")},
            ],
        )
        self.assertEqual(entry.lines.count(), 3)
        self.assertEqual(self.ar.balance(), Decimal("2500000"))
        self.assertEqual(self.service_revenue.balance(), Decimal("2000000"))
        self.assertEqual(self.parts_revenue.balance(), Decimal("500000"))

    def test_unbalanced_entry_raises_and_writes_nothing(self):
        with self.assertRaises(ValueError):
            JournalEntry.post(
                organization=self.org, posting_date=date(2026, 8, 7),
                source=JournalEntry.Source.MANUAL,
                lines=[
                    {"account": self.wip, "debit": Decimal("600000")},
                    {"account": self.inventory, "credit": Decimal("500000")},
                ],
            )
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)

    def test_single_line_entry_rejected(self):
        with self.assertRaises(ValueError):
            JournalEntry.post(
                organization=self.org, posting_date=date(2026, 8, 7),
                source=JournalEntry.Source.MANUAL,
                lines=[{"account": self.wip, "debit": Decimal("600000")}],
            )

    def test_zero_total_entry_rejected(self):
        with self.assertRaises(ValueError):
            JournalEntry.post(
                organization=self.org, posting_date=date(2026, 8, 7),
                source=JournalEntry.Source.MANUAL,
                lines=[
                    {"account": self.wip, "debit": Decimal("0")},
                    {"account": self.inventory, "credit": Decimal("0")},
                ],
            )

    def test_line_with_both_sides_set_rejected(self):
        with self.assertRaises(ValueError):
            JournalEntry.post(
                organization=self.org, posting_date=date(2026, 8, 7),
                source=JournalEntry.Source.MANUAL,
                lines=[
                    {"account": self.wip, "debit": Decimal("600000"), "credit": Decimal("600000")},
                    {"account": self.inventory, "credit": Decimal("600000")},
                ],
            )

    def test_entry_numbers_increment_per_organization(self):
        for _ in range(3):
            JournalEntry.post(
                organization=self.org, posting_date=date(2026, 8, 7),
                source=JournalEntry.Source.MANUAL,
                lines=[
                    {"account": self.wip, "debit": Decimal("1000")},
                    {"account": self.inventory, "credit": Decimal("1000")},
                ],
            )
        numbers = list(JournalEntry.objects.order_by("sequence_number").values_list("entry_number", flat=True))
        self.assertEqual(numbers, ["000001", "000002", "000003"])

    def test_entry_numbering_is_scoped_per_organization(self):
        """Same real guarantee as InvoiceSequence's own scoping test
        in apps.invoicing — two different shops both legitimately
        get entry_number 000001, not a collision."""
        other_org = Organization.objects.create(name="Bengkel Lain Accounting Numbering")
        call_command("seed_coa", organization=str(other_org.id), verbosity=0)
        other_wip = Account.objects.get(organization=other_org, code="1302")
        other_inv = Account.objects.get(organization=other_org, code="1301")

        JournalEntry.post(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.MANUAL,
            lines=[{"account": self.wip, "debit": Decimal("1000")}, {"account": self.inventory, "credit": Decimal("1000")}],
        )
        other_entry = JournalEntry.post(
            organization=other_org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.MANUAL,
            lines=[{"account": other_wip, "debit": Decimal("1000")}, {"account": other_inv, "credit": Decimal("1000")}],
        )
        self.assertEqual(other_entry.entry_number, "000001")


class AccountBalanceTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.cash = Account.objects.get(organization=self.org, code="1001")  # debit-normal
        self.ap = Account.objects.get(organization=self.org, code="2001")    # credit-normal

    def test_debit_normal_account_increases_with_debit(self):
        JournalEntry.post(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.MANUAL,
            lines=[{"account": self.cash, "debit": Decimal("500000")}, {"account": self.ap, "credit": Decimal("500000")}],
        )
        self.assertEqual(self.cash.balance(), Decimal("500000"))

    def test_credit_normal_account_increases_with_credit(self):
        JournalEntry.post(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.MANUAL,
            lines=[{"account": self.cash, "debit": Decimal("500000")}, {"account": self.ap, "credit": Decimal("500000")}],
        )
        self.assertEqual(self.ap.balance(), Decimal("500000"))

    def test_balance_as_of_excludes_later_postings(self):
        JournalEntry.post(
            organization=self.org, posting_date=date(2026, 1, 10),
            source=JournalEntry.Source.MANUAL,
            lines=[{"account": self.cash, "debit": Decimal("100000")}, {"account": self.ap, "credit": Decimal("100000")}],
        )
        JournalEntry.post(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.MANUAL,
            lines=[{"account": self.cash, "debit": Decimal("50000")}, {"account": self.ap, "credit": Decimal("50000")}],
        )
        self.assertEqual(self.cash.balance(as_of=date(2026, 2, 1)), Decimal("100000"))
        self.assertEqual(self.cash.balance(), Decimal("150000"))


class DatabaseConstraintTests(TestCase):
    """
    Proves the guardrails hold even against direct ORM misuse that
    bypasses JournalEntry.post() entirely — defense in depth, per the
    honest limitation noted in models.py's own module docstring.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.cash = Account.objects.get(organization=self.org, code="1001")

    def test_accounting_period_end_before_start_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AccountingPeriod.objects.create(
                    organization=self.org,
                    start_date=date(2026, 8, 31),
                    end_date=date(2026, 8, 1),
                )

    def test_journal_line_with_both_sides_zero_rejected_by_db(self):
        entry = JournalEntry.objects.create(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.MANUAL,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                JournalLine.objects.create(
                    organization=self.org, journal_entry=entry, account=self.cash,
                    debit_amount=Decimal("0"), credit_amount=Decimal("0"),
                )

    def test_journal_line_with_both_sides_set_rejected_by_db(self):
        entry = JournalEntry.objects.create(
            organization=self.org, posting_date=date(2026, 8, 7),
            source=JournalEntry.Source.MANUAL,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                JournalLine.objects.create(
                    organization=self.org, journal_entry=entry, account=self.cash,
                    debit_amount=Decimal("500"), credit_amount=Decimal("500"),
                )

class PostingEngineIntegrationTests(TestCase):
    """
    End-to-end proof that a real domain event, published through the
    real default_bus, produces a real, balanced JournalEntry — not
    just that posting_engine.resolve() returns the right dict in
    isolation. First test in the whole Sprint 1+2 arc that exercises
    the FULL chain: event -> bus -> dispatcher -> AccountingEventHandler
    -> journal_generator -> JournalEntry -> Account.balance().

    Events are constructed directly here rather than through the real
    workorders/invoicing/payments HTTP flows — this class's job is
    proving the accounting side of the pipeline specifically, not
    re-testing those apps' own already-covered creation flows.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)

    def test_part_consumed_posts_wip_and_inventory(self):
        event = PartConsumed(
            organization_id=self.org.id, part_id=uuid.uuid4(),
            work_order_id=uuid.uuid4(), material_line_id=uuid.uuid4(),
            quantity=Decimal("2.00"), unit_price_at_time=Decimal("60000.00"),
            amount=Decimal("120000.00"),
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        entry = JournalEntry.objects.get(reference_event_id=event.event_id)
        self.assertEqual(entry.event_type, "PartConsumed")
        self.assertEqual(entry.lines.count(), 2)

        wip = Account.objects.get(organization=self.org, code="1302")
        inventory = Account.objects.get(organization=self.org, code="1301")
        # .balance() reads back through a real NUMERIC(14,2) column —
        # 2 decimal places, not the 4 a raw Decimal multiplication
        # would show. Verified by hand before writing this assertion,
        # matches the exact "600000.00" pattern already seen live in
        # this project's own shell output earlier this session.
        self.assertEqual(wip.balance(), Decimal("120000.00"))
        self.assertEqual(inventory.balance(), Decimal("-120000.00"))

    def test_work_order_completed_posts_cogs_and_wip(self):
        event = WorkOrderCompleted(
            organization_id=self.org.id, work_order_id=uuid.uuid4(),
            service_record_id=uuid.uuid4(), amount=Decimal("500000.0000"),
            material_line_count=1,
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        cogs = Account.objects.get(organization=self.org, code="5001")
        wip = Account.objects.get(organization=self.org, code="1302")
        self.assertEqual(cogs.balance(), Decimal("500000.00"))
        self.assertEqual(wip.balance(), Decimal("-500000.00"))

    def test_work_order_completed_with_zero_amount_posts_nothing(self):
        """
        The exact real case behind Chris's own decision — a
        labor-only job still publishes the event (real audit fact in
        Outbox), but produces no journal entry, since
        JournalEntry.post() itself refuses a zero-total posting. The
        Outbox row must still read PROCESSED, not FAILED — the
        handler succeeded, it just had nothing to post.
        """
        event = WorkOrderCompleted(
            organization_id=self.org.id, work_order_id=uuid.uuid4(),
            service_record_id=uuid.uuid4(), amount=Decimal("0"),
            material_line_count=0,
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        self.assertFalse(JournalEntry.objects.filter(reference_event_id=event.event_id).exists())
        row = Outbox.objects.get(event_id=event.event_id)
        self.assertEqual(row.status, Outbox.Status.PROCESSED)

    def test_invoice_issued_posts_ar_and_split_revenue(self):
        event = InvoiceIssued(
            organization_id=self.org.id, invoice_id=uuid.uuid4(),
            service_amount=Decimal("100000.0000"), parts_amount=Decimal("250000.0000"),
            total=Decimal("350000.0000"), line_item_count=2,
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        entry = JournalEntry.objects.get(reference_event_id=event.event_id)
        self.assertEqual(entry.lines.count(), 3)

        ar = Account.objects.get(organization=self.org, code="1201")
        service_rev = Account.objects.get(organization=self.org, code="4001")
        parts_rev = Account.objects.get(organization=self.org, code="4002")
        self.assertEqual(ar.balance(), Decimal("350000.00"))
        self.assertEqual(service_rev.balance(), Decimal("100000.00"))
        self.assertEqual(parts_rev.balance(), Decimal("250000.00"))

    def test_invoice_issued_with_only_parts_omits_the_zero_service_line(self):
        """
        An all-parts invoice (service_amount=0) must produce exactly
        2 lines, not 3 with a zero-value one — a $0 credit line would
        violate JournalLine's own DB constraint if it were ever
        included.
        """
        event = InvoiceIssued(
            organization_id=self.org.id, invoice_id=uuid.uuid4(),
            service_amount=Decimal("0"), parts_amount=Decimal("250000.0000"),
            total=Decimal("250000.0000"), line_item_count=1,
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        entry = JournalEntry.objects.get(reference_event_id=event.event_id)
        self.assertEqual(entry.lines.count(), 2)

    def test_payment_received_cash_posts_to_cash_account(self):
        event = PaymentReceived(
            organization_id=self.org.id, invoice_id=uuid.uuid4(),
            payment_id=uuid.uuid4(), amount=Decimal("250000.00"), method="cash",
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        cash = Account.objects.get(organization=self.org, code="1001")
        ar = Account.objects.get(organization=self.org, code="1201")
        self.assertEqual(cash.balance(), Decimal("250000.00"))
        self.assertEqual(ar.balance(), Decimal("-250000.00"))

    def test_payment_received_bank_transfer_posts_to_bank_account(self):
        event = PaymentReceived(
            organization_id=self.org.id, invoice_id=uuid.uuid4(),
            payment_id=uuid.uuid4(), amount=Decimal("100000.00"), method="bank_transfer",
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        bank = Account.objects.get(organization=self.org, code="1101")
        self.assertEqual(bank.balance(), Decimal("100000.00"))

    def test_calling_post_for_event_twice_does_not_double_post(self):
        """
        UPDATED — no longer goes through default_bus.publish() twice.
        Outbox.event_id has its own unique=True constraint, so a
        literal second publish() for the same event_id raises
        IntegrityError at the Outbox-creation step, before ever
        reaching this idempotency guard — a real, correct guarantee,
        just a DIFFERENT one (no duplicate Outbox rows) than what
        this test is actually about.

        The real scenario journal_generator's own idempotency check
        guards against is a future retry/redelivery mechanism
        re-invoking the HANDLER for an event whose Outbox row already
        exists, without creating a second row — calling
        journal_generator.post_for_event() directly, twice, is what
        actually simulates that, bypassing the bus/Outbox layer on
        purpose for this specific test.
        """
        event = PartConsumed(
            organization_id=self.org.id, part_id=uuid.uuid4(),
            work_order_id=uuid.uuid4(), material_line_id=uuid.uuid4(),
            quantity=Decimal("1.00"), unit_price_at_time=Decimal("60000.00"),
            amount=Decimal("60000.00"),
        )
        journal_generator.post_for_event(event)
        journal_generator.post_for_event(event)  # same event, called again directly

        self.assertEqual(
            JournalEntry.objects.filter(reference_event_id=event.event_id).count(), 1,
        )
        
    def test_missing_chart_of_accounts_marks_outbox_failed_not_silent(self):
        """
        The real production risk this whole design surfaced — an
        organization with no seeded COA must not silently lose a real
        economic event. It fails loudly (Outbox FAILED, error
        captured), not silently with nothing posted and no trace.
        """
        unseeded_org = Organization.objects.create(name="Belum Di-seed")
        event = PartConsumed(
            organization_id=unseeded_org.id, part_id=uuid.uuid4(),
            work_order_id=uuid.uuid4(), material_line_id=uuid.uuid4(),
            quantity=Decimal("1.00"), unit_price_at_time=Decimal("60000.00"),
            amount=Decimal("60000.00"),
        )
        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        row = Outbox.objects.get(event_id=event.event_id)
        self.assertEqual(row.status, Outbox.Status.FAILED)
        self.assertIn("AccountingEventHandler", row.last_error)
        self.assertFalse(JournalEntry.objects.filter(reference_event_id=event.event_id).exists())

