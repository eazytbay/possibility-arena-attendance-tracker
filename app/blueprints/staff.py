from zoneinfo import ZoneInfo

import re
from datetime import datetime, timezone

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template,
                   request, url_for)
from sqlalchemy import or_

from .. import limiter
from ..models import AGE_GROUPS, DEPARTMENTS, MONTHS, REGISTER_CATEGORIES, SEXES, Attendance, Person, db
from ..services.attendance import (assign_pickup_code, audit, get_or_create_service,
                                   mark_present, register_full, upsert_adult, visitor_status)
from ..services.phone import normalize_phone
from ..services.photos import process_photo
from .auth import current_user, role_required

bp = Blueprint("staff", __name__)


@bp.route("/enrol", methods=["GET", "POST"])
@role_required("usher", "media")
def enrol():
    """Staff-operated registration: take someone's details and mark them present."""
    svc = get_or_create_service()
    user = current_user()
    form, error = {}, None
    if request.method == "POST":
        form = request.form
        photo, error = None, None
        try:
            photo = process_photo(request.files.get("photo"))
        except ValueError as exc:
            error = str(exc)
        res = None
        if not error:
            res, error = register_full(form, svc, user.id, "staff", photo, confirmed=form.get("confirmed") == "1")
        if not error and res.get("confirm"):
            existing = res["confirm"]
            tz = ZoneInfo(current_app.config["TIMEZONE"])
            at = res["checked_in_at"]
            notice = {"name": existing.full_name, "category": existing.category, "department": existing.department,
                      "phone": existing.phone, "present_at": at.astimezone(tz).strftime("%I:%M%p").lstrip("0").lower() if at else None,
                      "same_name": " ".join(existing.full_name.lower().split()) == " ".join(form.get("full_name", "").lower().split())}
            count = Attendance.query.filter_by(service_id=svc.id).count()
            return render_template("enrol.html", service=svc, count=count, form=form, error=None, notice=notice,
                                   categories=REGISTER_CATEGORIES, sexes=SEXES, departments=DEPARTMENTS,
                                   age_groups=AGE_GROUPS, months=MONTHS)
        if not error:
            p = res["person"]
            audit(user.username, "enrol", f"{p.id}:{p.full_name}")
            tag = f" ({res['status']})" if res["status"] else ""
            flash(f"{p.full_name}{tag} is marked present." + ("" if res["created"] else " Already on record: details updated."))
            return redirect(url_for("staff.enrol"))
    count = Attendance.query.filter_by(service_id=svc.id).count()
    return render_template("enrol.html", service=svc, count=count, form=form, error=error,
                           categories=REGISTER_CATEGORIES, sexes=SEXES, departments=DEPARTMENTS, age_groups=AGE_GROUPS,
                           months=MONTHS, notice=None)


@bp.get("/photo/<int:pid>.jpg")
@role_required("usher", "media")
def photo(pid):
    person = db.get_or_404(Person, pid)
    if person.category == "child" or not person.has_photo:
        abort(404)
    return Response(person.photo, mimetype="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@bp.get("/display")
@role_required("media")
def display():
    svc = get_or_create_service()
    url = current_app.config["PUBLIC_BASE_URL"].rstrip("/") + "/register"
    return render_template("display.html", svc=svc, url=url)


@bp.get("/checkin")
@role_required("usher", "media")
def checkin():
    svc = get_or_create_service()
    count = Attendance.query.filter_by(service_id=svc.id).count()
    return render_template("checkin.html", service=svc, count=count)


@bp.get("/api/search")
@role_required("usher", "media")
def search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    svc = get_or_create_service()
    digits = re.sub(r"\D", "", q)
    cond = Person.full_name.ilike(f"%{q}%")
    if len(digits) >= 3:
        cond = or_(cond, Person.phone.like(f"%{digits}%"))
    people = Person.query.filter(Person.category != "child", cond).order_by(Person.full_name).limit(15).all()
    present = {a.person_id for a in Attendance.query.filter(
        Attendance.service_id == svc.id, Attendance.person_id.in_([p.id for p in people]))}
    return jsonify([{
        "id": p.id, "name": p.full_name, "category": p.category, "department": p.department or "",
        "phone_tail": (p.phone or "")[-4:], "present": p.id in present, "photo": p.has_photo,
    } for p in people])


@bp.post("/api/checkin/<int:pid>")
@role_required("usher", "media")
def api_checkin(pid):
    person = db.get_or_404(Person, pid)
    if person.category == "child":
        return jsonify(error="Children are checked in from the Children page."), 400
    user = current_user()
    svc = get_or_create_service()
    _, created = mark_present(person, svc, user.id, "usher")
    if created:
        audit(user.username, "checkin", f"{person.id}:{person.full_name}")
    return jsonify(ok=True, created=created, status=visitor_status(person, svc))


@bp.post("/api/visitor")
@role_required("usher", "media")
def api_visitor():
    data = request.get_json(silent=True) or {}
    name = " ".join(str(data.get("name", "")).split())[:120]
    phone = normalize_phone(str(data.get("phone", "")))
    if len(name) < 3 or not phone:
        return jsonify(error="Enter the full name and a valid mobile number."), 400
    user = current_user()
    svc = get_or_create_service()
    person, _ = upsert_adult(name, phone, "visitor", None)
    mark_present(person, svc, user.id, "usher")
    audit(user.username, "visitor", f"{person.id}:{person.full_name}")
    return jsonify(ok=True, name=person.full_name, status=visitor_status(person, svc))


@bp.get("/children")
@role_required("children")
def children():
    svc = get_or_create_service()
    kids = Person.query.filter_by(category="child").order_by(Person.full_name).all()
    atts = {a.person_id: a for a in Attendance.query.filter_by(service_id=svc.id)}
    rows = []
    for k in kids:
        g_present = bool(k.guardian and k.guardian_id in atts)
        a = atts.get(k.id)
        rows.append({"id": k.id, "name": k.full_name, "age": k.age_group or "", "notes": k.notes or "",
                     "guardian": k.guardian.full_name if k.guardian else "",
                     "guardian_present": g_present,
                     "state": "released" if a and a.released_at else "in" if a else "out",
                     "code": a.pickup_code if a and not a.released_at else ""})
    rows.sort(key=lambda r: (not r["guardian_present"], r["name"]))
    return render_template("children.html", rows=rows, service=svc)


@bp.post("/api/children/<int:pid>/checkin")
@role_required("children")
def child_checkin(pid):
    child = db.get_or_404(Person, pid)
    if child.category != "child":
        return jsonify(error="Not a child record."), 400
    user = current_user()
    svc = get_or_create_service()
    att, created = mark_present(child, svc, user.id, "usher")
    code = assign_pickup_code(att)
    if created:
        audit(user.username, "child_checkin", f"{child.id}:{child.full_name}")
    return jsonify(ok=True, code=code)


@bp.post("/api/children/release")
@role_required("children")
@limiter.limit("30 per minute")
def child_release():
    code = str((request.get_json(silent=True) or {}).get("code", "")).strip()
    svc = get_or_create_service()
    att = Attendance.query.filter_by(service_id=svc.id, pickup_code=code, released_at=None).first() if code else None
    if not att:
        return jsonify(error="No waiting child has that pickup code."), 404
    user = current_user()
    att.released_at = datetime.now(timezone.utc)
    att.released_by = user.id
    db.session.commit()
    audit(user.username, "child_release", f"{att.person_id}:{att.person.full_name}")
    g = att.person.guardian
    return jsonify(ok=True, child=att.person.full_name, guardian=g.full_name if g else "")
