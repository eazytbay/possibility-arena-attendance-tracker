import io
from datetime import date

import qrcode
from flask import (Blueprint, Response, current_app, flash, redirect, render_template,
                   request, send_file, url_for)
from sqlalchemy import func

import re

from werkzeug.security import generate_password_hash

from ..models import CATEGORIES, DEPARTMENTS, MONTHS, ROLES, SEXES, Attendance, Person, Service, User, db
from ..services.absence import absent_csv, absent_on, missed_in_a_row, sundays_held
from ..services.attendance import (attendance_all_csv, attendance_csv, audit, get_or_create_service, new_access_code,
                                   filter_people, people_csv, visit_counts, visitor_status)
from .auth import current_user, owner_required, role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _csv_response(text: str, filename: str) -> Response:
    return Response("﻿" + text, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@bp.get("/")
@role_required()
def dashboard():
    svc = get_or_create_service()
    base = Attendance.query.filter_by(service_id=svc.id)
    total = base.count()
    cat_expr = func.coalesce(Attendance.category_at_visit, Person.category)
    by_cat = dict(db.session.query(cat_expr, func.count()).select_from(Attendance)
                  .join(Person, Person.id == Attendance.person_id)
                  .filter(Attendance.service_id == svc.id).group_by(cat_expr).all())
    by_dept = db.session.query(Person.department, func.count()).join(
        Attendance, Attendance.person_id == Person.id).filter(
        Attendance.service_id == svc.id, Person.department.isnot(None)).group_by(Person.department).all()
    visitors = [a.person for a in base.all() if (a.category_at_visit or a.person.category) == "visitor"]
    first_time = sum(1 for p in visitors if visitor_status(p, svc) == "first-time visitor")
    services = Service.query.order_by(Service.service_date.desc()).limit(20).all()
    today = date.today()
    birthdays = (Person.query.filter(Person.birth_month == svc.service_date.month, Person.category != "child")
                 .order_by(Person.birth_day, Person.full_name).all())
    return render_template("admin.html", svc=svc, total=total, by_cat=by_cat, by_dept=sorted(by_dept),
                           first_time=first_time, services=services,
                           people_total=Person.query.count(), birthdays=birthdays,
                           today_day=svc.service_date.day, month_name=svc.service_date.strftime('%B'))


@bp.post("/service/code")
@role_required()
def regenerate_code():
    svc = get_or_create_service()
    svc.access_code = new_access_code()
    db.session.commit()
    audit(current_user().username, "new_code", svc.service_date.isoformat())
    flash("A new service code is active. The old one no longer works.")
    return redirect(url_for("admin.dashboard"))


@bp.post("/service/toggle")
@role_required()
def toggle_registration():
    svc = get_or_create_service()
    svc.registration_open = not svc.registration_open
    db.session.commit()
    audit(current_user().username, "registration_open" if svc.registration_open else "registration_closed",
          svc.service_date.isoformat())
    flash("Self check-in is open." if svc.registration_open else "Self check-in is closed.")
    return redirect(url_for("admin.dashboard"))


@bp.get("/export/attendance.csv")
@role_required()
def export_attendance():
    try:
        d = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        d = get_or_create_service().service_date
    svc = Service.query.filter_by(service_date=d).first()
    if not svc:
        flash(f"No attendance was recorded on {d.strftime('%d %B %Y')}.")
        return redirect(url_for("admin.dashboard"))
    flt = {"category": request.args.get("category") if request.args.get("category") in CATEGORIES else None,
           "department": request.args.get("department") if request.args.get("department") in DEPARTMENTS else None,
           "sex": request.args.get("sex") if request.args.get("sex") in SEXES else None}
    audit(current_user().username, "export_attendance", d.isoformat())
    return _csv_response(attendance_csv(svc, flt), f"attendance-{d.isoformat()}.csv")


@bp.get("/export/all-attendance.csv")
@role_required()
def export_all_attendance():
    audit(current_user().username, "export_all_attendance")
    return _csv_response(attendance_all_csv(), "attendance-all-services.csv")


@bp.get("/export/people.csv")
@role_required()
def export_people():
    audit(current_user().username, "export_people", request.query_string.decode()[:200])
    return _csv_response(people_csv(filter_people(request.args).all()), "people.csv")


@bp.get("/people")
@role_required()
def people():
    rows = filter_people(request.args).limit(600).all()
    services = Service.query.order_by(Service.service_date.desc()).limit(30).all()
    return render_template("people.html", rows=rows, services=services,
                           visits=visit_counts([p.id for p in rows]), args=request.args, categories=CATEGORIES,
                           departments=DEPARTMENTS, sexes=SEXES, months=MONTHS,
                           query=request.query_string.decode())


@bp.get("/qr.png")
@role_required("media")
def qr_png():
    url = current_app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("public.register")
    img = qrcode.make(url, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@bp.get("/poster")
@role_required()
def poster():
    url = current_app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("public.register")
    return render_template("poster.html", url=url)


_USERNAME = re.compile(r"^[a-z0-9._-]{3,40}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.get("/team")
@owner_required
def team():
    return render_template("team.html", users=User.query.order_by(User.role, User.username).all(),
                           roles=[r for r in ROLES if r != "owner"], me=current_user())


@bp.post("/team")
@owner_required
def team_add():
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower() or None
    role = request.form.get("role", "")
    password = request.form.get("password", "")
    if not _USERNAME.match(username):
        flash("Username: 3 to 40 letters, numbers, dots, dashes or underscores.")
    elif email and (len(email) > 120 or not _EMAIL.match(email)):
        flash("That email address does not look right.")
    elif role not in ROLES or role == "owner":
        flash("Choose a valid role. There can only be one owner.")
    elif len(password) < 8:
        flash("The password needs at least 8 characters.")
    elif User.query.filter(db.or_(User.username == username, User.email == (email or username))).first():
        flash("That username or email already exists.")
    else:
        db.session.add(User(username=username, email=email, role=role,
                            password_hash=generate_password_hash(password)))
        db.session.commit()
        audit(current_user().username, "team_add", f"{username}:{role}")
        flash(f"Created {role} login '{username}'.")
    return redirect(url_for("admin.team"))


@bp.post("/team/<int:uid>/delete")
@owner_required
def team_delete(uid):
    user = db.get_or_404(User, uid)
    if user.role == "owner":
        flash("The owner login cannot be removed here.")
    else:
        db.session.delete(user)
        db.session.commit()
        audit(current_user().username, "team_delete", user.username)
        flash(f"Removed '{user.username}'.")
    return redirect(url_for("admin.team"))


@bp.post("/team/<int:uid>/password")
@owner_required
def team_password(uid):
    user = db.get_or_404(User, uid)
    password = request.form.get("password", "")
    if len(password) < 8:
        flash("The password needs at least 8 characters.")
    else:
        user.password_hash = generate_password_hash(password)
        db.session.commit()
        audit(current_user().username, "team_password", user.username)
        flash(f"Password changed for '{user.username}'.")
    return redirect(url_for("admin.team"))


def _absence_args():
    sundays = sundays_held()
    try:
        day = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        day = sundays[-1].service_date if sundays else date.today()
    mode = "streak" if request.args.get("mode") == "streak" else "one"
    rows, note = missed_in_a_row(day) if mode == "streak" else absent_on(day)
    return sundays, day, mode, rows, note


@bp.get("/absent")
@role_required()
def absent():
    sundays, day, mode, rows, note = _absence_args()
    return render_template("absent.html", sundays=list(reversed(sundays)), day=day, mode=mode, rows=rows, note=note,
                           lookback=current_app.config["ABSENT_LOOKBACK"], n=current_app.config["MISSED_IN_A_ROW"],
                           query=request.query_string.decode())


@bp.get("/export/absent.csv")
@role_required()
def export_absent():
    _, day, mode, rows, _ = _absence_args()
    audit(current_user().username, "export_absent", f"{mode}:{day.isoformat()}")
    return _csv_response(absent_csv(rows), f"absent-{mode}-{day.isoformat()}.csv")
