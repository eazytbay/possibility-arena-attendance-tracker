"""Who was missing? Compares the People list against the Sundays attended.

Only Sunday services count (a midweek test day or special service is ignored). Only adults and teens are listed:
children are followed up through their parents, and one-time visitors are not regulars yet.
"""
import csv
import io
from dataclasses import dataclass
from datetime import date

from flask import current_app

from ..models import Attendance, Person, Service, db
from .attendance import _safe

FOLLOW_UP_CATEGORIES = ("member", "worker", "minister", "teen")


@dataclass
class Row:
    person: Person
    last_seen: date | None
    recent_sundays: int  # Sundays attended in the look-back window


def sundays_held(upto: date | None = None) -> list[Service]:
    svcs = [s for s in Service.query.all() if s.service_date.weekday() == 6 and (upto is None or s.service_date <= upto)]
    return sorted(svcs, key=lambda s: s.service_date)


def _present_map(service_ids) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    if not service_ids:
        return out
    for pid, sid in db.session.query(Attendance.person_id, Attendance.service_id).filter(
            Attendance.service_id.in_(list(service_ids))):
        out.setdefault(pid, set()).add(sid)
    return out


def _last_seen(person_ids) -> dict[int, date]:
    if not person_ids:
        return {}
    rows = (db.session.query(Attendance.person_id, db.func.max(Service.service_date))
            .join(Service, Service.id == Attendance.service_id)
            .filter(Attendance.person_id.in_(list(person_ids))).group_by(Attendance.person_id).all())
    return dict(rows)


def _settings():
    cfg = current_app.config
    return cfg.get("ABSENT_LOOKBACK", 8), cfg.get("MISSED_IN_A_ROW", 3)


def _build(candidates: list[Person], present: dict[int, set[int]], window_ids: set[int], recent_ids: set[int]):
    seen = _last_seen([p.id for p in candidates])
    rows = []
    for p in candidates:
        mine = present.get(p.id, set())
        rows.append(Row(p, seen.get(p.id), len(mine & window_ids)))
    rows.sort(key=lambda r: (r.person.full_name.lower()))
    return rows


def _people():
    return Person.query.filter(Person.category.in_(FOLLOW_UP_CATEGORIES)).all()


def absent_on(day: date) -> tuple[list[Row], str]:
    """Regulars (came at least once in the look-back Sundays before `day`) who were not there on `day`."""
    lookback, _ = _settings()
    svcs = sundays_held(day)
    target = next((s for s in svcs if s.service_date == day), None)
    if not target:
        return [], f"No Sunday service was recorded on {day.strftime('%d %B %Y')}."
    before = [s for s in svcs if s.service_date < day][-lookback:]
    if not before:
        return [], "There is no earlier Sunday to compare with yet."
    ids = {s.id for s in before} | {target.id}
    present = _present_map(ids)
    window = {s.id for s in before}
    out = [p for p in _people() if present.get(p.id, set()) & window and target.id not in present.get(p.id, set())]
    return _build(out, present, window, {target.id}), ""


def missed_in_a_row(day: date) -> tuple[list[Row], str]:
    """Regulars who missed each of the last N Sundays up to and including `day`."""
    lookback, n = _settings()
    svcs = sundays_held(day)
    recent = svcs[-n:]
    earlier = svcs[:-n][-lookback:]
    if len(recent) < n or not earlier:
        return [], f"Needs at least {n + 1} Sundays on record. There are {len(svcs)} so far."
    ids = {s.id for s in recent} | {s.id for s in earlier}
    present = _present_map(ids)
    window, recent_ids = {s.id for s in earlier}, {s.id for s in recent}
    out = [p for p in _people() if present.get(p.id, set()) & window and not (present.get(p.id, set()) & recent_ids)]
    return _build(out, present, window, recent_ids), ""


def absent_csv(rows: list[Row]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "phone", "category", "department", "last_seen", "sundays_attended_recently"])
    for r in rows:
        p = r.person
        w.writerow([_safe(x) for x in [p.full_name, p.phone or "", p.category, p.department or "",
                                       r.last_seen.isoformat() if r.last_seen else "", r.recent_sundays]])
    return buf.getvalue()
