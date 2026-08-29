# =============================================================================
# === backend/apps/core/tests.py ===
# =============================================================================
"""
apps.core has two real, testable pieces right now: TenantScopedModel
(exercised indirectly through every other app's own model tests —
no independent behavior to isolate on its own) and the event bus
infrastructure (apps.core.events.*), which has no dedicated coverage
anywhere else in the codebase. Exercised directly here using small,
purpose-built DomainEvent/EventHandler subclasses, since no real
domain event exists anywhere in the codebase until Sprint 2.

Each test that touches default_bus uses its own uniquely-named
DomainEvent subclass (a distinct event_type string per test) via
_make_event_class() below, rather than sharing one across tests —
default_bus is a real module-level singleton with no unsubscribe()
method (by design — nothing in production ever needs to unsubscribe),
so tests sharing an event_type would leak subscribed handlers into
each other across the whole test run, making results order-dependent.
Giving every test its own event_type sidesteps that without needing
to add throwaway test-only surface to production code.

transaction.on_commit() callbacks don't fire inside Django TestCase's
default wrapping transaction (which is rolled back at the end of each
test, never actually committed) — every dispatch-related test below
uses self.captureOnCommitCallbacks(execute=True) specifically to
force those callbacks to run, matching real request/response
behavior. Without it, a test could pass for the wrong reason (the
handler silently never running at all, rather than genuinely running
after commit).
"""
import dataclasses
import inspect
import uuid
from dataclasses import dataclass, field

from apps.core.events.bus import default_bus
from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent
from apps.core.events.registry import event_class_for
from apps.core.models import Outbox
from apps.organizations.models import Organization
from django.db import IntegrityError, transaction
from django.test import TestCase


def _make_event_class(type_name):
    """
    One throwaway DomainEvent subclass per test, carrying its own
    distinct event_type string — see module docstring for why this
    matters. Parameter deliberately NOT named event_type — Python
    treats any name assigned anywhere in a class body as local to
    that class body for the ENTIRE body, including the right-hand
    side of the same line that assigns it, which silently breaks the
    closure over an identically-named enclosing variable. Caught by
    testing this exact helper standalone before relying on it here.
    """
    @dataclass(frozen=True)
    class _TestEvent(DomainEvent):
        amount: str = "0"
        event_type: str = field(init=False, default=type_name, kw_only=True)

    return _TestEvent


class RecordingHandler(EventHandler):
    """Test double — records every event it receives, never fails."""

    def __init__(self, handles):
        self.handles = handles
        self.received = []

    def handle(self, event):
        self.received.append(event)


class FailingHandler(EventHandler):
    """Test double — always raises, to prove dispatcher failure handling."""

    def __init__(self, handles):
        self.handles = handles

    def handle(self, event):
        raise RuntimeError("deliberate test failure")


class DomainEventContractTests(TestCase):
    """No database involved — a DomainEvent is a plain dataclass, per
    interfaces.py's own module docstring."""

    def test_base_class_cannot_be_instantiated_directly(self):
        with self.assertRaises(TypeError):
            DomainEvent(organization_id=uuid.uuid4())

    def test_subclass_without_event_type_override_raises(self):
        @dataclass(frozen=True)
        class _NoEventType(DomainEvent):
            pass

        with self.assertRaises(NotImplementedError):
            _NoEventType(organization_id=uuid.uuid4())

    def test_event_is_immutable(self):
        EventCls = _make_event_class("Test.Immutable")
        event = EventCls(organization_id=uuid.uuid4(), amount="100")
        with self.assertRaises(Exception):
            event.amount = "200"

    def test_payload_excludes_envelope_fields(self):
        EventCls = _make_event_class("Test.PayloadShape")
        org_id = uuid.uuid4()
        event = EventCls(organization_id=org_id, amount="2.00")

        payload = event.payload()
        self.assertEqual(payload, {"amount": "2.00"})
        self.assertNotIn("organization_id", payload)
        self.assertNotIn("event_id", payload)
        self.assertNotIn("occurred_at", payload)
        self.assertNotIn("event_type", payload)

    def test_event_id_and_occurred_at_are_auto_generated_and_distinct_per_instance(self):
        EventCls = _make_event_class("Test.AutoFields")
        first = EventCls(organization_id=uuid.uuid4())
        second = EventCls(organization_id=uuid.uuid4())
        self.assertIsNotNone(first.event_id)
        self.assertIsNotNone(first.occurred_at)
        self.assertNotEqual(first.event_id, second.event_id)

    def test_class_level_event_type_matches_instance_level(self):
        """
        The exact thing _make_event_class()'s own docstring above
        warns about — proven here directly, not just relied upon
        silently by every other test in this file that does
        handles=(EventCls.event_type,) before any instance exists.
        """
        EventCls = _make_event_class("Test.ClassLevelAccess")
        instance = EventCls(organization_id=uuid.uuid4())
        self.assertEqual(EventCls.event_type, "Test.ClassLevelAccess")
        self.assertEqual(EventCls.event_type, instance.event_type)


class EventBusPublishTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")

    def test_publish_creates_an_outbox_row(self):
        EventCls = _make_event_class("Test.PublishCreatesOutboxRow")
        event = EventCls(organization_id=self.org.id, amount="123.45")

        default_bus.publish(event)

        row = Outbox.objects.get(event_id=event.event_id)
        self.assertEqual(row.event_type, "Test.PublishCreatesOutboxRow")
        self.assertEqual(row.organization_id, self.org.id)
        self.assertEqual(row.payload, {"amount": "123.45"})

    def test_no_subscribers_marks_outbox_processed_not_failed(self):
        """
        No handler subscribed yet for a given event_type is expected
        and fine — most events won't have an accounting handler wired
        up until Sprint 2 — not a failure state.
        """
        EventCls = _make_event_class("Test.NoSubscribers")
        event = EventCls(organization_id=self.org.id)

        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        row = Outbox.objects.get(event_id=event.event_id)
        self.assertEqual(row.status, Outbox.Status.PROCESSED)

    def test_handler_dispatch_is_deferred_until_commit(self):
        """
        The real guarantee this whole design exists for — a handler
        must not run before the publishing transaction actually
        commits. Deliberately does NOT use
        captureOnCommitCallbacks(execute=True) here — this test wants
        to prove the callback has NOT fired yet, immediately after
        publish() returns.
        """
        EventCls = _make_event_class("Test.DeferredUntilCommit")
        handler = RecordingHandler(handles=(EventCls.event_type,))
        default_bus.subscribe(handler)
        event = EventCls(organization_id=self.org.id)

        default_bus.publish(event)

        self.assertEqual(len(handler.received), 0, "handler must not run before commit")

    def test_handler_runs_after_commit(self):
        EventCls = _make_event_class("Test.RunsAfterCommit")
        handler = RecordingHandler(handles=(EventCls.event_type,))
        default_bus.subscribe(handler)
        event = EventCls(organization_id=self.org.id, amount="99")

        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        self.assertEqual(len(handler.received), 1)
        self.assertEqual(handler.received[0].event_id, event.event_id)

        row = Outbox.objects.get(event_id=event.event_id)
        self.assertEqual(row.status, Outbox.Status.PROCESSED)

    def test_failing_handler_marks_outbox_failed_with_error_captured(self):
        EventCls = _make_event_class("Test.HandlerFails")
        handler = FailingHandler(handles=(EventCls.event_type,))
        default_bus.subscribe(handler)
        event = EventCls(organization_id=self.org.id)

        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        row = Outbox.objects.get(event_id=event.event_id)
        self.assertEqual(row.status, Outbox.Status.FAILED)
        self.assertEqual(row.attempts, 1)
        self.assertIn("FailingHandler", row.last_error)

    def test_one_failing_handler_does_not_block_other_handlers(self):
        """
        One handler blowing up must not stop a second, unrelated
        handler subscribed to the same event from doing its own job —
        each handler's failure is isolated, per dispatcher.py's own
        per-handler try/except. The Outbox row still ends up FAILED
        overall (any failure marks the whole row FAILED) — but the
        healthy handler's work still genuinely happened.
        """
        EventCls = _make_event_class("Test.PartialFailure")
        failing = FailingHandler(handles=(EventCls.event_type,))
        recording = RecordingHandler(handles=(EventCls.event_type,))
        default_bus.subscribe(failing)
        default_bus.subscribe(recording)
        event = EventCls(organization_id=self.org.id)

        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        self.assertEqual(len(recording.received), 1)
        row = Outbox.objects.get(event_id=event.event_id)
        self.assertEqual(row.status, Outbox.Status.FAILED)

    def test_multiple_healthy_handlers_all_receive_the_same_event(self):
        EventCls = _make_event_class("Test.MultipleHandlers")
        handler_a = RecordingHandler(handles=(EventCls.event_type,))
        handler_b = RecordingHandler(handles=(EventCls.event_type,))
        default_bus.subscribe(handler_a)
        default_bus.subscribe(handler_b)
        event = EventCls(organization_id=self.org.id)

        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        self.assertEqual(len(handler_a.received), 1)
        self.assertEqual(len(handler_b.received), 1)

    def test_handler_subscribed_to_a_different_event_type_is_not_called(self):
        EventCls = _make_event_class("Test.OnlyForThisType")
        OtherEventCls = _make_event_class("Test.NotThisType")
        handler = RecordingHandler(handles=(OtherEventCls.event_type,))
        default_bus.subscribe(handler)
        event = EventCls(organization_id=self.org.id)

        with self.captureOnCommitCallbacks(execute=True):
            default_bus.publish(event)

        self.assertEqual(len(handler.received), 0)


class OutboxModelTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")

    def _row_for(self, type_name):
        EventCls = _make_event_class(type_name)
        event = EventCls(organization_id=self.org.id)
        row = Outbox.objects.create(
            organization=self.org, event_id=event.event_id, event_type=event.event_type,
            payload=event.payload(), occurred_at=event.occurred_at,
        )
        return row

    def test_mark_processed_sets_status_and_timestamp(self):
        row = self._row_for("Test.MarkProcessed")
        self.assertIsNone(row.processed_at)

        row.mark_processed()
        row.refresh_from_db()
        self.assertEqual(row.status, Outbox.Status.PROCESSED)
        self.assertIsNotNone(row.processed_at)

    def test_mark_failed_increments_attempts_and_records_latest_error(self):
        row = self._row_for("Test.MarkFailed")

        row.mark_failed("first failure")
        row.refresh_from_db()
        self.assertEqual(row.status, Outbox.Status.FAILED)
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.last_error, "first failure")

        row.mark_failed("second failure")
        row.refresh_from_db()
        self.assertEqual(row.attempts, 2)
        self.assertEqual(row.last_error, "second failure")

    def test_event_id_is_unique(self):
        EventCls = _make_event_class("Test.UniqueEventId")
        event = EventCls(organization_id=self.org.id)
        Outbox.objects.create(
            organization=self.org, event_id=event.event_id, event_type=event.event_type,
            payload=event.payload(), occurred_at=event.occurred_at,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Outbox.objects.create(
                    organization=self.org, event_id=event.event_id, event_type=event.event_type,
                    payload=event.payload(), occurred_at=event.occurred_at,
                )


class EventRegistryCompletenessTests(TestCase):
    """
    28 Aug 2026 — real, structural guard against the exact gap that's
    now bitten this codebase THREE times (Aug 9, Aug 22, 28 Aug): a
    new event type ships correctly for LIVE dispatch, but nobody
    remembers apps.core.events.registry.py is a SEPARATE, second
    place that also needs it — invisible until a real Outbox row
    actually needs replaying and fails with a raw KeyError.

    Deliberately does NOT rely on a hand-maintained list of "every
    event type" that could itself silently drift out of date — walks
    apps.accounting.posting_engine's own real, live module namespace
    for every DomainEvent subclass it actually imports (the EXACT
    same sourcing method registry.event_class_for()'s own docstring
    already documents using, confirmed directly against that file),
    and confirms each one is retrievable from the registry AND maps
    back to the correct class. A future event added to
    posting_engine.py but forgotten in registry.py fails THIS test
    immediately, the very next time the suite runs — not silently,
    only during a real production incident's own replay attempt, a
    fourth time.

    Reads each event class's own real event_type default via
    dataclasses.fields() rather than instantiating one — every event
    class declares event_type as field(init=False, default="...",
    kw_only=True); the literal default is directly inspectable
    without needing a real organization_id or any other required
    argument.
    """

    def test_every_event_type_posting_engine_handles_is_registered_for_replay(self):
        from apps.accounting import posting_engine

        event_classes = [
            obj for _, obj in vars(posting_engine).items()
            if inspect.isclass(obj) and issubclass(obj, DomainEvent) and obj is not DomainEvent
        ]
        # Sanity check on the discovery mechanism itself — if this
        # ever comes back empty, posting_engine.py's own import shape
        # changed in a way that broke discovery, and a passing result
        # below would be trusting a test that silently checked
        # nothing at all.
        self.assertGreater(
            len(event_classes), 0,
            "Found zero DomainEvent subclasses imported into posting_engine.py — "
            "either that module's own imports changed shape, or this test's own "
            "discovery logic is broken. Investigate before trusting this test's "
            "own 'passed' result.",
        )

        missing = []
        for event_cls in event_classes:
            event_type_field = next(f for f in dataclasses.fields(event_cls) if f.name == "event_type")
            event_type_value = event_type_field.default
            try:
                registered_cls = event_class_for(event_type_value)
            except ValueError:
                missing.append(event_cls.__name__)
                continue
            if registered_cls is not event_cls:
                missing.append(
                    f"{event_cls.__name__} (registry maps {event_type_value!r} to a "
                    f"DIFFERENT class: {registered_cls.__name__})"
                )

        self.assertEqual(
            missing, [],
            f"The following event type(s) are imported by posting_engine.py — meaning "
            f"they can be posted via a real, LIVE first-time dispatch right now — but "
            f"are missing from, or incorrectly mapped in, "
            f"apps.core.events.registry.event_class_for(). A real, already-FAILED "
            f"Outbox row for any of these could never be replayed. Add each one to "
            f"that registry's own dict: {missing}",
        )
