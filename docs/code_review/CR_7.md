# Code Review — Phase 7: Alert Sinks, Recipients, Sent Notifications

## Summary

The implementation is clean and well-structured. The `AlertSink` Protocol is a proper seam, the ring buffer logic is correct, and the dispatcher integrates with the scheduler without coupling the incident service to the alert layer. Three issues stand out: `LogSink` inserts a notification row even when there are no recipients (inconsistent with `SmtpSink` and arguably wrong per spec), the recipients `POST` endpoint has a TOCTOU race that produces an unhandled 500 instead of 409 on concurrent duplicate inserts, and the dispatcher fetches recipients without a `user_id` filter (harmless now, silent footgun for any future multi-user work).

---

## Issues

### [Major] `LogSink.send_email` inserts a row even when `recipients` is empty

**File:** `backend/src/heartbeat/alerts/log_sink.py:30–53`

**Description:** `SmtpSink` guards against empty recipients with an early return before calling `aiosmtplib.send` — correctly, because there is nobody to send to. `LogSink` has no equivalent guard; it always inserts into `sent_notifications` regardless of whether `recipients` is `[]`. Per REQUIREMENTS.md §6.4: "every email the system **would have sent** is captured." If there are no recipients, no email would be sent, so nothing should be captured. The current behavior silently fills the ring buffer with zero-recipient ghost rows and is explicitly tested in `test_no_notifications_when_no_recipients` as correct — but that test is asserting the wrong behavior.

**Fix:** Add the same early-return guard as `SmtpSink`:
```python
async def send_email(self, ..., recipients: list[str]) -> None:
    if not recipients:
        return
    async with self._session_factory() as session:
        ...
```
Update the test to assert `count == 0` when there are no recipients.

---

### [Major] `create_recipient` has a TOCTOU race that returns 500 on concurrent duplicate inserts

**File:** `backend/src/heartbeat/api/recipients.py:37–44`

**Description:** The route first checks for an existing row with a `SELECT`, then `INSERT`s if none is found. Two concurrent requests with the same address can both pass the check and then collide on the `uq_email_recipients_user_address` unique constraint, causing the second to raise a SQLAlchemy `IntegrityError` that propagates as a 500 instead of the expected 409. For a single-user MVP the race is unlikely in practice, but it is still a correctness gap.

**Fix:** Catch the `IntegrityError` and convert it to a 409, or drop the pre-check entirely and rely solely on the DB constraint:
```python
from sqlalchemy.exc import IntegrityError

try:
    session.add(EmailRecipient(user_id=_USER_ID, address=payload.address))
    await session.commit()
    await session.refresh(recipient)
    return recipient
except IntegrityError:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Address already exists")
```

---

### [Major] `AlertDispatcher.dispatch` fetches all recipients without a `user_id` filter

**File:** `backend/src/heartbeat/services/alert_dispatcher.py:65–69`

**Description:** The query `select(EmailRecipient).order_by(EmailRecipient.id)` fetches every row in `email_recipients` regardless of `user_id`. For the single-user MVP this is always correct (only user 1 exists). But it is inconsistent with every other point in the codebase that touches this table — the recipients API always filters by `_USER_ID = 1`. If a future multi-user migration adds more users, the dispatcher would silently notify all users' recipients for any incident.

**Fix:** Add a where clause:
```python
select(EmailRecipient)
.where(EmailRecipient.user_id == 1)
.order_by(EmailRecipient.id)
```

---

### [Minor] `SentNotification.recipients` typed as `Mapped[list]` instead of `Mapped[list[str]]`

**File:** `backend/src/heartbeat/models/sent_notification.py:29`

**Description:** The `recipients` column is declared as `Mapped[list]`. The JSONB column stores a JSON array, and SQLAlchemy's type system cannot enforce the inner type at the DB level, but the application code — the `AlertSink` Protocol, `SentNotificationRead`, and every call site — treats recipients as `list[str]`. Using `Mapped[list]` loses that information at the model layer and allows a silent type mismatch if, for example, a non-string value is accidentally stored.

**Fix:** Change to `Mapped[list[str]]`. No migration needed; the DB column type is unchanged.

---

### [Minor] `SmtpSink` SMTP errors are not logged at the sink level

**File:** `backend/src/heartbeat/alerts/smtp_sink.py:38–46`

**Description:** If `aiosmtplib.send` raises (auth failure, connection refused, TLS error), the exception propagates to `AlertDispatcher.dispatch`'s `except Exception` handler, which logs "Alert dispatch failed for incident N". The actual SMTP error is included via `logger.exception`, but the log message does not distinguish a delivery failure from a dispatcher logic failure (e.g., incident not found). In practice this makes alert delivery failures harder to triage.

**Fix:** Wrap the `aiosmtplib.send` call in a try/except within `SmtpSink` and log a specific warning before re-raising, so the dispatcher's catch-all still fires but logs carry context from both layers:
```python
try:
    await aiosmtplib.send(...)
except Exception:
    logger.warning("SMTP delivery failed for incident %d", incident_id, exc_info=True)
    raise
```

---

### [Minor] Email address validation does not require a dot in the domain

**File:** `backend/src/heartbeat/schemas/email_recipient.py:13`

**Description:** The validator accepts any string containing `@` as long as it does not start or end with `@`. Strings like `"foo@bar"` or `"a@b"` pass validation. A minimal improvement would be to verify the domain part contains at least one dot: `"." in v.split("@", 1)[1]`. This still does not catch all invalid addresses, but it rejects the most common typos.

**Fix:**
```python
local, domain = v.split("@", 1)
if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
    raise ValueError("invalid email address")
```

---

### [Nit] `apply_check_result` docstring explains what, not why

**File:** `backend/src/heartbeat/services/incident_service.py:23`

**Description:** The docstring reads: "Update streak state and open/close incidents. Returns events for alert dispatch." The first sentence describes what the function name already conveys. Per the project coding standard: "Don't explain WHAT the code does." The second sentence is non-obvious and worth keeping, but it should explain the *why* — specifically that events must be dispatched after commit so the dispatcher can use a fresh session without risking seeing uncommitted state.

**Fix:**
```python
# Returns (kind, incident) pairs to be dispatched after the caller commits;
# dispatching post-commit ensures the dispatcher opens a fresh session to
# a fully consistent snapshot.
```

---

### [Nit] `wait_for_dispatch` docstring is misleading

**File:** `backend/src/heartbeat/scheduler.py:57–60`

**Description:** The docstring says "For use in tests." but `stop()` calls the same gather logic (lines 53–54). The method is also used for clean shutdown. "For use in tests" implies it is unsafe or inappropriate to call otherwise, which is not true.

**Fix:** Change the docstring to: "Wait for all pending dispatch tasks to complete."

---

### [Nit] `_build_message` uses `else` instead of `elif` for the closed branch

**File:** `backend/src/heartbeat/services/alert_dispatcher.py:30`

**Description:** The `else` branch implicitly handles `NotificationKind.incident_closed`. If a new value is ever added to the enum (e.g., `incident_acknowledged`), it would silently use the closed-incident message format. An explicit `elif` plus a final `raise ValueError` is more defensive.

**Fix:**
```python
elif kind == NotificationKind.incident_closed:
    ...
else:
    raise ValueError(f"Unknown notification kind: {kind}")
```

---

## Positive observations

- `AlertSink` as a Protocol (not ABC) is the right choice: both `LogSink` and `SmtpSink` satisfy it without any shared base class or coupling. Swapping in a new sink requires no changes to the protocol definition.
- `NotificationKind` placement in `models/sent_notification.py` follows the established project pattern (`ErrorCategory` in `models/check_result.py`, `StreakOutcome` in `models/endpoint.py`) — canonical in models, imported elsewhere. No circular dependency risk.
- The ring buffer SQL is correct and NULL-safe: `DELETE WHERE id < (SELECT id ORDER BY id DESC OFFSET N-1 LIMIT 1)` deletes nothing when ≤N rows exist because `id < NULL` is always false in SQL. The correctness is proven in-comment and verified by the test.
- `apply_check_result` returns `list[tuple[NotificationKind, Incident]]` rather than calling the dispatcher directly. This cleanly separates the incident service from the alert layer — `incident_service.py` imports nothing from `alerts/` and the scheduler is the integration point. The design is easy to test in isolation.
- Dispatch tasks are tracked in `_dispatch_tasks` and awaited on `stop()`. Ghost tasks cannot outlive the scheduler's lifetime, preventing resource leaks on shutdown.
- `SmtpSink` uses `from __future__ import annotations` with `TYPE_CHECKING` to avoid triggering `settings = Settings()` at import time. This is the correct approach; it allows the unit test to import `SmtpSink` without a `DATABASE_URL` environment variable.
- `SequenceChecker` in `test_alerts.py` raises `IndexError` on exhaustion (strict mode), in contrast to the cycling version in `test_incidents.py`. This is the right behavior: a test that drives more ticks than the sequence has entries should fail loudly rather than silently reuse outcomes.
- The `ring_buffer_size` parameter on `LogSink` (default `_RING_BUFFER_SIZE = 1000`) is a clean solution to the test performance problem. The production constant is unchanged; the test simply exercises the same code path at a smaller scale.
- The notifications route's cursor pagination (`before_id`) is applied at the SQLAlchemy statement level before execution, not as post-processing, so `LIMIT` always sees the correctly scoped result set.
- The migration's `downgrade()` correctly issues `DROP TYPE IF EXISTS notification_kind` after dropping `sent_notifications`. This matches the `error_category` pattern established in Phase 5.
