"""One-off group messages (programme reminders). An admin writes the text, checks a preview, then confirms.

Safety rules, all enforced here and covered by tests:
  * only adults/teens with a phone number who have not opted out are ever texted (never children);
  * a draft is created at preview time and can be confirmed exactly once, so a double tap or a page
    refresh cannot send twice;
  * every recipient is its own row, claimed before sending, so two workers never text the same person;
  * a person whose send was interrupted is marked failed, never retried automatically (no double texts);
  * nothing is sent before 08:00 or after 20:00 Lagos time; a confirmed message waits for the hourly job.
"""
import logging
import math
import re
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app

from ..models import Attendance, Broadcast, BroadcastRecipient, DEPARTMENTS, Person, PersonDepartment, Service, db
from .greetings import SEND_FROM_HOUR, SEND_UNTIL_HOUR, _clean
from .message_text import MAX_NAME, greeting_name

log = logging.getLogger(__name__)

AUDIENCES = {
    "all": "Everyone (members, workers, ministers and teens)",
    "workers": "All workers",
    "visitors": "Visitors (not yet counted as members)",
    "members": "Members only",
    "departments": "Workers in chosen departments",
}
MAX_CHARS = 459            # three SMS pages
STALE_AFTER = timedelta(minutes=10)


def pages(n_chars: int) -> int:
    """SMS pages: 160 characters for one page, then 153 per page when a message is joined together."""
    return 1 if n_chars <= 160 else math.ceil(n_chars / 153)


def check_text(raw: str) -> tuple[str, str | None]:
    """Clean the text and return (text, error). Plain characters only, so it is not garbled on the phone."""
    text = _clean((raw or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not text:
        return text, "Write the message first."
    if any(ord(ch) > 126 or (ord(ch) < 32 and ch != "\n") for ch in text):
        return text, "Use plain letters and numbers only (no emoji or special symbols), so it shows properly on every phone."
    if re.search(r"\{(?!name\})[^}]*\}", text):
        return text, "Only {name} can go inside curly brackets."
    if len(worst_case(text)) > MAX_CHARS:
        return text, f"Too long. The limit is {MAX_CHARS} characters (three SMS pages)."
    return text, None


def worst_case(text: str) -> str:
    return text.replace("{name}", "W" * MAX_NAME)


def render(text: str, person: Person) -> str:
    return text.replace("{name}", greeting_name(person.full_name))


def audience_label(kind: str, departments: list[str]) -> str:
    if kind == "departments":
        return "Workers in " + ", ".join(departments)
    return AUDIENCES[kind]


def audience_people(kind: str, departments: list[str]) -> tuple[list[Person], int]:
    """(people who will be texted, people in the group who are skipped for no phone or opted out)."""
    q = Person.query.filter(Person.category != "child")
    if kind == "all":
        q = q.filter(Person.category.in_(("member", "worker", "minister", "teen")))
    elif kind == "workers":
        q = q.filter(Person.category == "worker")
    elif kind == "members":
        q = q.filter(Person.category == "member")
    elif kind == "visitors":
        q = q.filter(Person.category == "visitor")
    elif kind == "departments":
        q = q.filter(Person.dept_rows.any(PersonDepartment.department.in_(departments or ["-"])))
    else:
        raise ValueError(kind)
    everyone = q.order_by(Person.id).all()
    sendable = [p for p in everyone if p.phone and p.sms_opt_in]
    return sendable, len(everyone) - len(sendable)


def parse_audience(form) -> tuple[str, list[str], str | None]:
    kind = form.get("audience", "")
    if kind not in AUDIENCES:
        return kind, [], "Choose who the message is for."
    depts = [d for d in DEPARTMENTS if d in form.getlist("department")]
    if kind == "departments" and not depts:
        return kind, depts, "Tick at least one department."
    return kind, (depts if kind == "departments" else []), None


def create_draft(user: str, kind: str, departments: list[str], text: str) -> Broadcast:
    people, _ = audience_people(kind, departments)
    cap = current_app.config.get("SMS_BROADCAST_MAX", 500)
    if len(people) > cap:
        raise ValueError(f"That is {len(people)} people; the limit for one message is {cap}.")
    b = Broadcast(created_by=user, audience=audience_label(kind, departments), text=text, status="draft")
    b.recipients = [BroadcastRecipient(person_id=p.id, status="pending") for p in people]
    db.session.add(b)
    db.session.commit()
    return b


def present_today_ids() -> set[int]:
    """People checked in at today's service (Lagos date), so they can be left out of a reminder in one tap."""
    from .attendance import today_local
    svc = Service.query.filter_by(service_date=today_local()).first()
    if not svc:
        return set()
    return {a.person_id for a in Attendance.query.filter_by(service_id=svc.id)}


def apply_selection(broadcast_id: int, person_ids: set[int]) -> int:
    """While still a draft: only the ticked people stay on the list, the rest are left out. Returns how many remain."""
    b = db.session.get(Broadcast, broadcast_id)
    if not b or b.status != "draft":
        return 0
    keep = 0
    for r in b.recipients:
        if r.person_id in person_ids:
            r.status, keep = "pending", keep + 1
        else:
            r.status = "skipped"
    db.session.commit()
    return keep


def confirm(broadcast_id: int) -> bool:
    """Draft -> queued. True only for the single call that wins; repeat calls (double tap) get False."""
    n = Broadcast.query.filter_by(id=broadcast_id, status="draft").update({"status": "queued"})
    db.session.commit()
    return n == 1


def cancel(broadcast_id: int) -> None:
    b = db.session.get(Broadcast, broadcast_id)
    if not b or b.status not in ("draft", "queued"):
        return
    BroadcastRecipient.query.filter_by(broadcast_id=b.id, status="pending").update({"status": "skipped"})
    b.status = "cancelled"
    db.session.commit()


def counts(b: Broadcast) -> dict[str, int]:
    out = {"pending": 0, "sending": 0, "sent": 0, "failed": 0, "skipped": 0}
    for r in b.recipients:
        out[r.status] = out.get(r.status, 0) + 1
    out["total"] = len(b.recipients)
    return out


def in_send_hours(now: datetime | None = None) -> bool:
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    now = (now or datetime.now(tz)).astimezone(tz)
    return SEND_FROM_HOUR <= now.hour < SEND_UNTIL_HOUR


def _expire_stale(b: Broadcast) -> None:
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    for r in b.recipients:
        if r.status == "sending" and (r.updated_at.replace(tzinfo=r.updated_at.tzinfo or timezone.utc) < cutoff):
            r.status, r.error = "failed", "interrupted; check the Bulk SMS Nigeria report before resending"
    db.session.commit()


def process(provider, broadcast_id: int | None = None, now: datetime | None = None,
            enforce_hours: bool = True) -> dict[str, int | bool | str | None]:
    """Send pending recipients of queued broadcasts (one, or all). Safe to call repeatedly and concurrently."""
    report = {"sent": 0, "failed": 0, "outside_hours": False, "stopped": None}
    if provider is None:
        return report
    if enforce_hours and not in_send_hours(now):
        report["outside_hours"] = True
        return report
    q = Broadcast.query.filter_by(status="queued")
    if broadcast_id is not None:
        q = q.filter_by(id=broadcast_id)
    for b in q.order_by(Broadcast.id).all():
        _expire_stale(b)
        for r in list(b.recipients):
            if r.status != "pending":
                continue
            person = r.person
            won = BroadcastRecipient.query.filter_by(broadcast_id=b.id, person_id=r.person_id, status="pending") \
                .update({"status": "sending"})
            db.session.commit()
            if won != 1:
                continue                                  # someone else claimed it
            if not person.phone or not person.sms_opt_in:  # changed since the preview
                BroadcastRecipient.query.filter_by(broadcast_id=b.id, person_id=r.person_id) \
                    .update({"status": "skipped", "error": "no phone or opted out"})
                db.session.commit()
                continue
            result = provider.send(person.phone, render(b.text, person))
            row = BroadcastRecipient.query.filter_by(broadcast_id=b.id, person_id=r.person_id).one()
            row.status = "sent" if result.ok else "failed"
            row.provider_id = result.message_id
            row.error = None if result.ok else f"{result.code or ''} {result.error or ''}".strip()[:200]
            db.session.commit()
            if result.ok:
                report["sent"] += 1
            else:
                report["failed"] += 1
                log.warning("Broadcast %s: SMS failed for person %s: %s", b.id, person.id, row.error)
                if result.fatal:
                    b.error = (row.error or "provider refused")[:200]
                    db.session.commit()
                    report["stopped"] = b.error
                    return report
        db.session.refresh(b)
        if not any(x.status in ("pending", "sending") for x in b.recipients):
            b.status = "done"
            db.session.commit()
    return report


def start_in_background(app, broadcast_id: int) -> None:
    """Send without making the admin wait (a long list takes minutes). The hourly job picks up anything left."""
    from .sms import provider_from_config

    def work():
        with app.app_context():
            try:
                process(provider_from_config(app.config), broadcast_id)
            except Exception:  # noqa: BLE001 - never let a thread die silently
                log.exception("Broadcast %s crashed", broadcast_id)
            finally:
                db.session.remove()

    if app.config.get("TESTING"):
        work()
    else:
        threading.Thread(target=work, daemon=True, name=f"broadcast-{broadcast_id}").start()
