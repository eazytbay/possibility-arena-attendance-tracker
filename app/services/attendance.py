import calendar
import csv
import hmac
import io
import logging
import secrets
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..models import (ADULT_CATEGORIES, AGE_GROUPS, CATEGORIES, DEPARTMENTS, REGISTER_CATEGORIES, SEXES,
                      Attendance, AuditLog, Person, Service, db)
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
    att = Attendance(service_id=service.id, person_id=person.id, checked_in_by=user_id, source=source,
                     category_at_visit=person.category)
    db.session.add(att)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return Attendance.query.filter_by(service_id=service.id, person_id=person.id).one(), False
    _maybe_promote(person)
    return att, True


def visit_count(person_id: int) -> int:
    """Sundays this person was counted as a visitor."""
    return (Attendance.query.join(Person, Person.id == Attendance.person_id)
            .filter(Attendance.person_id == person_id,
                    db.func.coalesce(Attendance.category_at_visit, Person.category) == "visitor").count())


def _maybe_promote(person: Person) -> None:
    """After enough Sundays a visitor becomes a member. The attendance history keeps 'visitor' for those days."""
    limit = current_app.config.get("VISITOR_PROMOTE_AFTER", 4)
    if limit and person.category == "visitor" and visit_count(person.id) >= limit:
        person.category = "member"
        db.session.commit()
        audit("system", "visitor_promoted", f"{person.id}:{person.full_name}")


def visit_counts(ids) -> dict:
    if not ids:
        return {}
    rows = (db.session.query(Attendance.person_id, db.func.count())
            .join(Person, Person.id == Attendance.person_id)
            .filter(Attendance.person_id.in_(ids),
                    db.func.coalesce(Attendance.category_at_visit, Person.category) == "visitor")
            .group_by(Attendance.person_id).all())
    return dict(rows)


def parse_birthday(f):
    """Return (month, day, error). Both empty is fine; the year is never collected."""
    m, d = (f.get("birth_month") or "").strip(), (f.get("birth_day") or "").strip()
    if not m and not d:
        return None, None, None
    try:
        mi, di = int(m), int(d)
    except ValueError:
        return None, None, "Choose both the month and the day of birth, or leave both empty."
    if not 1 <= mi <= 12 or not 1 <= di <= calendar.monthrange(2000, mi)[1]:
        return None, None, "That birthday is not a valid date."
    return mi, di, None


def upsert_adult(name: str, phone: str | None, category: str, department: str | None,
                 birth=(None, None), sex: str | None = None):
    """Find by phone (or by exact name for a teen without a phone) or create.

    A known member is never downgraded to 'visitor'.
    """
    if phone:
        person = Person.query.filter_by(phone=phone).first()
    else:
        person = Person.query.filter(db.func.lower(Person.full_name) == name.lower(),
                                     Person.category == "teen", Person.phone.is_(None)).first()
    if person:
        if birth[0]:
            person.birth_month, person.birth_day = birth
        if sex:
            person.sex = sex
        if not (category == "visitor" and person.category in ADULT_CATEGORIES and person.category != "visitor"):
            person.category = category
            person.department = department
        person.full_name = name
        db.session.commit()
        return person, False
    person = Person(full_name=name, phone=phone, category=category, department=department,
                    birth_month=birth[0], birth_day=birth[1], sex=sex)
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
    att = Attendance.query.filter_by(person_id=person.id, service_id=service.id).first()
    category = (att.category_at_visit if att and att.category_at_visit else person.category)
    if category != "visitor":
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


def _match(att: Attendance, flt: dict) -> bool:
    person = att.person
    for k, v in flt.items():
        if not v:
            continue
        have = (att.category_at_visit or person.category) if k == "category" else getattr(person, k)
        if have != v:
            return False
    return True


def attendance_csv(service: Service, flt: dict | None = None) -> str:
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["service_date", "name", "phone", "category", "department", "sex", "visitor_status",
                "guardian", "age_group", "source", "checked_in_at", "released_at"])
    rows = Attendance.query.filter_by(service_id=service.id).order_by(Attendance.checked_in_at).all()
    for a in rows:
        p = a.person
        if flt and not _match(a, flt):
            continue
        w.writerow([_safe(x) for x in [
            service.service_date.isoformat(), p.full_name, p.phone or "", a.category_at_visit or p.category,
            p.department or "", p.sex or "",
            visitor_status(p, service), p.guardian.full_name if p.guardian else "", p.age_group or "",
            a.source, a.checked_in_at.astimezone(tz).strftime("%H:%M"),
            a.released_at.astimezone(tz).strftime("%H:%M") if a.released_at else "",
        ]])
    return buf.getvalue()


def filter_people(args):
    """Build the People query from request args: category, department, sex, month, q."""
    q = Person.query
    cat = args.get("category") if args.get("category") in CATEGORIES else None
    try:
        came_on = date.fromisoformat(args.get("came_on", ""))
    except ValueError:
        came_on = None
    if came_on:
        # Who was here that Sunday, and as what (a visitor then stays a visitor in that Sunday's list).
        sub = (db.session.query(Attendance.person_id).join(Service, Service.id == Attendance.service_id)
               .join(Person, Person.id == Attendance.person_id).filter(Service.service_date == came_on))
        if cat:
            sub = sub.filter(db.func.coalesce(Attendance.category_at_visit, Person.category) == cat)
        q = q.filter(Person.id.in_(sub))
    elif cat:
        q = q.filter(Person.category == cat)
    if args.get("department") in DEPARTMENTS:
        q = q.filter(Person.department == args["department"])
    if args.get("sex") in SEXES:
        q = q.filter(Person.sex == args["sex"])
    if (args.get("month") or "").isdigit() and 1 <= int(args["month"]) <= 12:
        q = q.filter(Person.birth_month == int(args["month"]))
    text = (args.get("q") or "").strip()
    if text:
        q = q.filter(Person.full_name.ilike(f"%{text}%"))
    return q.order_by(Person.full_name)


def people_csv(people=None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "phone", "category", "department", "sex", "birthday", "age_group", "guardian", "notes",
                "registered", "sundays_as_visitor"])
    people = list(people if people is not None else Person.query.order_by(Person.full_name))
    visits = visit_counts([p.id for p in people])
    for p in people:
        bday = f"{p.birth_day:02d} {calendar.month_abbr[p.birth_month]}" if p.birth_month else ""
        w.writerow([_safe(x) for x in [
            p.full_name, p.phone or "", p.category, p.department or "", p.sex or "", bday, p.age_group or "",
            p.guardian.full_name if p.guardian else "", p.notes or "", p.created_at.date().isoformat(),
            visits.get(p.id, 0),
        ]])
    return buf.getvalue()


def _find_existing(name: str, phone: str | None) -> Person | None:
    if phone:
        return Person.query.filter_by(phone=phone).first()
    return Person.query.filter(db.func.lower(Person.full_name) == name.lower(),
                               Person.category == "teen", Person.phone.is_(None)).first()


def register_full(f, svc: Service, user_id: int | None = None, source: str = "self", photo: bytes | None = None,
                  confirmed: bool = False):
    """Validate one registration form, save the adult and children, mark present.

    Returns (result_dict, None) on success or (None, error_message).
    If the person is already on record under a different name, or is already marked present today, nothing is
    changed and the result is {"confirm": <person on record>, "checked_in_at": <time or None>} so the caller can
    ask staff "same person?". Passing confirmed=True goes ahead and updates the details.
    """
    raw_phone = (f.get("phone") or "").strip()
    phone = normalize_phone(raw_phone) if raw_phone else None
    name = " ".join(f.get("full_name", "").split())[:120]
    category = f.get("category", "")
    department = f.get("department") or None
    sex = f.get("sex") or None
    if len(name) < 3:
        return None, "Please enter the full name."
    if category not in REGISTER_CATEGORIES:
        return None, "Please choose member, worker, minister, teen or visitor."
    if not phone and not (category == "teen" and not raw_phone):
        return None, "Enter a valid Nigerian mobile number, for example 08012345678."
    if department and department not in DEPARTMENTS:
        return None, "Please choose a department from the list."
    if sex and sex not in SEXES:
        return None, "Please choose male or female."
    bm, bd, berr = parse_birthday(f)
    if berr:
        return None, berr
    if category == "visitor":
        department = None
    if not confirmed:
        existing = _find_existing(name, phone)
        if existing:
            att = Attendance.query.filter_by(service_id=svc.id, person_id=existing.id).first()
            same_name = " ".join(existing.full_name.lower().split()) == name.lower()
            if att or not same_name:
                return {"confirm": existing, "checked_in_at": att.checked_in_at if att else None}, None
    person, created = upsert_adult(name, phone, category, department, (bm, bd), sex)
    if photo:
        person.photo, person.has_photo = photo, True
        db.session.commit()
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


def attendance_all_csv() -> str:
    """Every attendance record across all services, one row each, for analysis."""
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["service_date", "name", "phone", "category", "department", "sex", "guardian", "age_group",
                "source", "checked_in_at"])
    rows = (Attendance.query.join(Service).order_by(Service.service_date, Attendance.checked_in_at).all())
    for a in rows:
        p = a.person
        w.writerow([_safe(x) for x in [
            a.service.service_date.isoformat(), p.full_name, p.phone or "", a.category_at_visit or p.category,
            p.department or "", p.sex or "", p.guardian.full_name if p.guardian else "", p.age_group or "", a.source,
            a.checked_in_at.astimezone(tz).strftime("%H:%M"),
        ]])
    return buf.getvalue()
