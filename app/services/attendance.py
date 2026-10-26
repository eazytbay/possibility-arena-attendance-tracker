import csv
import hmac
import io
import logging
import secrets
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..models import (ADULT_CATEGORIES, AGE_GROUPS, DEPARTMENTS, Attendance, AuditLog, Person,
                      Service, db)
from .phone import normalize_phone

log = logging.getLogger(__name__)


def today_local() -> date:
    return datetime.now(ZoneInfo(current_app.config["TIMEZONE"])).date()


def audit(actor: str, action: str, detail: str = "") -> None:
    db.session.add(AuditLog(actor=actor, action=action, detail=detail[:300]))
    db.session.commit()


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid read-aloud mistakes


def new_access_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(5))


def code_is_valid(service: Service, supplied: str) -> bool:
    return bool(service.access_code) and hmac.compare_digest(
        (supplied or "").strip().upper(), service.access_code)


def get_or_create_service(d: date | None = None) -> Service:
    d = d or today_local()
    svc = Service.query.filter_by(service_date=d).first()
    if svc:
        if not svc.access_code:
            svc.access_code = new_access_code()
            db.session.commit()
        return svc
    svc = Service(service_date=d, name=f"Service {d.isoformat()}", access_code=new_access_code())
    db.session.add(svc)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        svc = Service.query.filter_by(service_date=d).one()
    return svc


def mark_present(person: Person, service: Service, user_id: int | None = None, source: str = "usher"):
    """Idempotent: marking the same person twice for a service returns the existing row."""
    existing = Attendance.query.filter_by(service_id=service.id, person_id=person.id).first()
    if existing:
        return existing, False
    att = Attendance(service_id=service.id, person_id=person.id, checked_in_by=user_id, source=source)
    db.session.add(att)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return Attendance.query.filter_by(service_id=service.id, person_id=person.id).one(), False
    return att, True


def upsert_adult(name: str, phone: str, category: str, department: str | None):
    """Find by phone or create. A known member is never downgraded to 'visitor'."""
    person = Person.query.filter_by(phone=phone).first()
    if person:
        if not (category == "visitor" and person.category in ADULT_CATEGORIES and person.category != "visitor"):
            person.category = category
            person.department = department
        person.full_name = name
        db.session.commit()
        return person, False
    person = Person(full_name=name, phone=phone, category=category, department=department)
    db.session.add(person)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return Person.query.filter_by(phone=phone).one(), False
    return person, True


def add_child(guardian: Person, name: str, age_group: str | None, notes: str | None) -> Person:
    for c in guardian.children:
        if c.full_name.strip().lower() == name.strip().lower():
            c.age_group, c.notes = age_group, notes
            db.session.commit()
            return c
    child = Person(full_name=name, category="child", age_group=age_group, notes=notes, guardian_id=guardian.id)
    db.session.add(child)
    db.session.commit()
    return child


def assign_pickup_code(att: Attendance) -> str:
    if att.pickup_code:
        return att.pickup_code
    used = {a.pickup_code for a in Attendance.query.filter_by(service_id=att.service_id) if a.pickup_code}
    while True:
        code = f"{secrets.randbelow(10000):04d}"
        if code not in used:
            break
    att.pickup_code = code
    db.session.commit()
    return code


def visitor_status(person: Person, service: Service) -> str:
    if person.category != "visitor":
        return ""
    earlier = (
        Attendance.query.join(Service)
        .filter(Attendance.person_id == person.id, Service.service_date < service.service_date)
        .count()
    )
    return "returning visitor" if earlier else "first-time visitor"


def _safe(cell) -> str:
    """Neutralise spreadsheet formula injection in exported text."""
    s = "" if cell is None else str(cell)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def attendance_csv(service: Service) -> str:
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["service_date", "name", "phone", "category", "department", "visitor_status",
                "guardian", "age_group", "source", "checked_in_at", "released_at"])
    rows = Attendance.query.filter_by(service_id=service.id).order_by(Attendance.checked_in_at).all()
    for a in rows:
        p = a.person
        w.writerow([_safe(x) for x in [
            service.service_date.isoformat(), p.full_name, p.phone or "", p.category, p.department or "",
            visitor_status(p, service), p.guardian.full_name if p.guardian else "", p.age_group or "",
            a.source, a.checked_in_at.astimezone(tz).strftime("%H:%M"),
            a.released_at.astimezone(tz).strftime("%H:%M") if a.released_at else "",
        ]])
    return buf.getvalue()


def people_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "phone", "category", "department", "age_group", "guardian", "notes", "registered"])
    for p in Person.query.order_by(Person.full_name):
        w.writerow([_safe(x) for x in [
            p.full_name, p.phone or "", p.category, p.department or "", p.age_group or "",
            p.guardian.full_name if p.guardian else "", p.notes or "", p.created_at.date().isoformat(),
        ]])
    return buf.getvalue()


def register_full(f, svc: Service, user_id: int | None = None, source: str = "self"):
    """Validate one registration form, save the adult and children, mark present.

    Returns (result_dict, None) on success or (None, error_message).
    """
    phone = normalize_phone(f.get("phone"))
    name = " ".join(f.get("full_name", "").split())[:120]
    category = f.get("category", "")
    department = f.get("department") or None
    if len(name) < 3:
        return None, "Please enter the full name."
    if not phone:
        return None, "Enter a valid Nigerian mobile number, for example 08012345678."
    if category not in ADULT_CATEGORIES:
        return None, "Please choose member, worker, minister or visitor."
    if department and department not in DEPARTMENTS:
        return None, "Please choose a department from the list."
    if category == "visitor":
        department = None
    person, created = upsert_adult(name, phone, category, department)
    status = visitor_status(person, svc)
    mark_present(person, svc, user_id, source)
    kids = []
    names, ages, notes = f.getlist("child_name"), f.getlist("child_age"), f.getlist("child_notes")
    for i, cname in enumerate(names[:12]):
        cname = " ".join(cname.split())[:120]
        if not cname:
            continue
        age = ages[i] if i < len(ages) and ages[i] in AGE_GROUPS else None
        note = (notes[i] if i < len(notes) else "").strip()[:300] or None
        kids.append(add_child(person, cname, age, note))
    return {"person": person, "created": created, "kids": kids or list(person.children), "status": status}, None
