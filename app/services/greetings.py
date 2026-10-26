"""Daily greetings: a birthday message on each person's birthday and a new-month message on the 1st."""
import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import current_app

from ..models import MessageLog, Person, db
from .message_text import HOLIDAYS, birthday_text, holiday_text, new_month_text

log = logging.getLogger(__name__)

SEND_FROM_HOUR, SEND_UNTIL_HOUR = 8, 20  # Nigerian rules: no promotional-style messages before 8am or after 8pm
MAX_ATTEMPTS = 3


@dataclass
class Due:
    person: Person
    kind: str
    period_key: str
    text: str


@dataclass
class RunReport:
    sent: int = 0
    failed: int = 0
    skipped_done: int = 0
    outside_hours: bool = False
    stopped_early: str | None = None
    dry_lines: list[str] = field(default_factory=list)


def _first_name(person: Person) -> str:
    return (person.full_name.split() or ["friend"])[0].capitalize()


def _clean(text: str) -> str:
    """Keep text plain so it stays one 160-character SMS page (no emoji or curly quotes)."""
    return text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


def _birthday_today(person: Person, day: date) -> bool:
    if not person.birth_month or not person.birth_day:
        return False
    if (person.birth_month, person.birth_day) == (2, 29) and not calendar.isleap(day.year):
        return (day.month, day.day) == (2, 28)  # leap-day birthdays are greeted on 28 February
    return (person.birth_month, person.birth_day) == (day.month, day.day)


def due_messages(day: date) -> list[Due]:
    cfg = current_app.config
    eligible = Person.query.filter(Person.category != "child", Person.phone.isnot(None),
                                   Person.sms_opt_in.is_(True)).order_by(Person.id).all()
    out: list[Due] = []
    for p in eligible:
        if _birthday_today(p, day):
            out.append(Due(p, "birthday", day.isoformat(),
                           _clean(birthday_text(_first_name(p), p.id, day.year, cfg.get("SMS_TEXT_BIRTHDAY") or None))))
        holiday = HOLIDAYS.get((day.month, day.day))
        if holiday:
            kind = holiday[0]
            out.append(Due(p, kind, day.isoformat(), _clean(holiday_text(kind, _first_name(p), day.year))))
        elif day.day == 1:
            out.append(Due(p, "new_month", f"{day.year}-{day.month:02d}",
                           _clean(new_month_text(_first_name(p), calendar.month_name[day.month],
                                                 day.year, day.month, cfg.get("SMS_TEXT_NEW_MONTH") or None))))
    return out


def run_greetings(provider, now: datetime | None = None, dry_run: bool = False,
                  enforce_hours: bool = True) -> RunReport:
    """Send everything that is due today and not yet sent. Safe to run many times a day."""
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    now = (now or datetime.now(tz)).astimezone(tz)
    report = RunReport()
    if enforce_hours and not dry_run and not (SEND_FROM_HOUR <= now.hour < SEND_UNTIL_HOUR):
        report.outside_hours = True
        return report
    for due in due_messages(now.date()):
        row = MessageLog.query.filter_by(person_id=due.person.id, kind=due.kind, period_key=due.period_key).first()
        if row and (row.status == "sent" or row.attempts >= MAX_ATTEMPTS):
            report.skipped_done += 1
            continue
        if dry_run or provider is None:
            report.dry_lines.append(f"{due.kind}: {due.person.full_name} ({due.person.phone}) -> {due.text}")
            continue
        result = provider.send(due.person.phone, due.text)
        if row is None:
            row = MessageLog(person_id=due.person.id, kind=due.kind, period_key=due.period_key, attempts=0)
            db.session.add(row)
        row.attempts += 1
        row.status = "sent" if result.ok else "failed"
        row.provider_id = result.message_id
        row.error = None if result.ok else f"{result.code or ''} {result.error or ''}".strip()[:200]
        db.session.commit()
        if result.ok:
            report.sent += 1
        else:
            report.failed += 1
            log.warning("SMS failed for person %s (%s): %s", due.person.id, due.kind, row.error)
            if result.fatal:
                report.stopped_early = row.error or "provider refused"
                break
    return report
