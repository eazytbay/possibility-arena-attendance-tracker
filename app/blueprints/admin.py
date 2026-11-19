import io
from datetime import date

import qrcode
from flask import (Blueprint, Response, current_app, flash, redirect, render_template,
                   request, send_file, url_for)
from sqlalchemy import func

import re

from werkzeug.security import generate_password_hash

from ..models import (AGE_GROUPS, Broadcast, CATEGORIES, DEPARTMENTS, REGISTER_CATEGORIES, MONTHS, ROLES, SEXES, Attendance, Person,
                      PersonDepartment, Service, User, db)
from ..services.absence import absent_csv, absent_on, missed_in_a_row, sundays_held
from ..services.attendance import (parse_birthday, parse_departments, attendance_all_csv, attendance_csv, audit, get_or_create_service, latest_service, new_access_code, next_service_date,
                                   filter_people, people_csv, visit_counts, visitor_status)
from ..services import broadcast as bc
from ..services.phone import normalize_phone
from ..services.sms import provider_from_config
from ..services.photos import photo_from_request, process_photo
from .auth import current_user, owner_required, role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _csv_response(text: str, filename: str) -> Response:
    return Response("﻿" + text, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@bp.get("/")
@role_required()
def dashboard():
    svc = get_or_create_service(next_service_date())   # today's service, or the coming one: its code and self check-in switch
    last = latest_service()                              # the service whose numbers are shown below
    base = Attendance.query.filter_by(service_id=last.id) if last else Attendance.query.filter(db.false())
    total = base.count()
    cat_expr = func.coalesce(Attendance.category_at_visit, Person.category)
    by_cat = dict(db.session.query(cat_expr, func.count()).select_from(Attendance)
                  .join(Person, Person.id == Attendance.person_id)
                  .filter(Attendance.service_id == (last.id if last else 0)).group_by(cat_expr).all())
    # A person who serves in two departments is counted once in each of them.
    by_dept = db.session.query(PersonDepartment.department, func.count()).join(
        Attendance, Attendance.person_id == PersonDepartment.person_id).filter(
        Attendance.service_id == (last.id if last else 0)).group_by(PersonDepartment.department).all()
    visitors = [a.person for a in base.all() if (a.category_at_visit or a.person.category) == "visitor"]
    first_time = sum(1 for p in visitors if visitor_status(p, last) == "first-time visitor")
    services = Service.query.order_by(Service.service_date.desc()).limit(20).all()
    today = date.today()
    birthdays = (Person.query.filter(Person.birth_month == today.month, Person.category != "child")
                 .order_by(Person.birth_day, Person.full_name).all())
    return render_template("admin.html", svc=svc, last=last, is_today=svc.service_date == today, total=total, by_cat=by_cat, by_dept=sorted(by_dept),
                           first_time=first_time, services=services,
                           people_total=Person.query.count(), birthdays=birthdays,
                           today_day=today.day, month_name=today.strftime('%B'))


@bp.post("/service/code")
@role_required()
def regenerate_code():
    svc = get_or_create_service(next_service_date())
    svc.access_code = new_access_code()
    db.session.commit()
    audit(current_user().username, "new_code", svc.service_date.isoformat())
    flash("A new service code is active. The old one no longer works.")
    return redirect(url_for("admin.dashboard"))


@bp.post("/service/toggle")
@role_required()
def toggle_registration():
    svc = get_or_create_service(next_service_date())
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
        last = latest_service()
        d = last.service_date if last else date.today()
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


@bp.route("/person/<int:pid>/edit", methods=["GET", "POST"])
@role_required("media")
def edit_person(pid):
    """Change what is on record for one person: details, photo, birthday and greeting messages."""
    person = db.get_or_404(Person, pid)
    is_child = person.category == "child"
    error = None
    if request.method == "POST":
        f = request.form
        name = " ".join(f.get("full_name", "").split())[:120]
        if len(name) < 3:
            error = "Please enter the full name."
        elif is_child:
            age = f.get("age_group") or None
            if age and age not in AGE_GROUPS:
                error = "Please choose an age group from the list."
            else:
                person.full_name, person.age_group = name, age
                person.notes = (f.get("notes") or "").strip()[:300] or None
        else:
            category = f.get("category", "")
            raw_phone = (f.get("phone") or "").strip()
            phone = normalize_phone(raw_phone) if raw_phone else None
            departments, derr = parse_departments(f)
            sex = f.get("sex") or None
            bm, bd, berr = parse_birthday(f)
            if category not in REGISTER_CATEGORIES:
                error = "Please choose a category."
            elif not phone and not (category == "teen" and not raw_phone):
                error = "Enter a valid Nigerian mobile number, for example 08012345678."
            elif derr:
                error = derr
            elif sex and sex not in SEXES:
                error = "Please choose male or female."
            elif berr:
                error = berr
            else:
                other = Person.query.filter(Person.phone == phone, Person.id != person.id).first() if phone else None
                if other:
                    error = f"That number already belongs to {other.full_name}. Each person needs their own number."
            photo = None
            if not error:
                try:
                    photo = photo_from_request(request)
                except ValueError as exc:
                    error = str(exc)
            if not error:
                person.full_name, person.phone, person.category = name, phone, category
                person.set_departments([] if category == "visitor" else departments)
                person.sex, person.birth_month, person.birth_day = sex, bm, bd
                person.sms_opt_in = f.get("sms_opt_in") == "1"
                if f.get("remove_photo") == "1":
                    person.photo, person.has_photo = None, False
                if photo:
                    person.photo, person.has_photo = photo, True
        if not error:
            db.session.commit()
            audit(current_user().username, "edit_person", f"{person.id}:{person.full_name}")
            flash(f"{person.full_name} was updated.")
            return redirect(url_for("admin.people"))
        db.session.rollback()
    return render_template("person_edit.html", p=person, is_child=is_child, error=error, form=request.form,
                           categories=REGISTER_CATEGORIES, sexes=SEXES, departments=DEPARTMENTS,
                           age_groups=AGE_GROUPS, months=MONTHS)


# ---- Messages: one-off texts to a group (programme reminders) --------------------------------------------

def _sms_on() -> bool:
    return provider_from_config(current_app.config) is not None


@bp.get("/messages")
@role_required()
def messages():
    recent = Broadcast.query.filter(Broadcast.status != "draft").order_by(Broadcast.id.desc()).limit(15).all()
    return render_template("messages.html", audiences=bc.AUDIENCES, departments=DEPARTMENTS, form=request.args,
                           recent=recent, counts=bc.counts, sms_on=_sms_on(), error=None,
                           cap=current_app.config["SMS_BROADCAST_MAX"])


@bp.post("/messages/preview")
@role_required()
def messages_preview():
    kind, depts, err = bc.parse_audience(request.form)
    text, terr = bc.check_text(request.form.get("text", ""))
    err = err or terr
    draft = None
    if not err:
        try:
            draft = bc.create_draft(current_user().username, kind, depts, text)
        except ValueError as exc:
            err = str(exc)
    if err:
        recent = Broadcast.query.filter(Broadcast.status != "draft").order_by(Broadcast.id.desc()).limit(15).all()
        return render_template("messages.html", audiences=bc.AUDIENCES, departments=DEPARTMENTS, form=request.form,
                               recent=recent, counts=bc.counts, sms_on=_sms_on(), error=err,
                               cap=current_app.config["SMS_BROADCAST_MAX"]), 400
    _, skipped = bc.audience_people(kind, depts)
    return _preview_page(draft, skipped)


def _preview_page(b: Broadcast, skipped: int = 0, phone: str = ""):
    people = [r.person for r in b.recipients]
    longest = max((len(bc.render(b.text, p)) for p in people), default=len(b.text))
    n_pages = bc.pages(longest)
    return render_template("message_preview.html", b=b, n=len(people), skipped=skipped, people=people,
                           here=bc.present_today_ids(), picked={r.person_id for r in b.recipients if r.status == "pending"},
                           samples=[(p.full_name, bc.render(b.text, p)) for p in people[:3]], longest=longest,
                           n_pages=n_pages, credits=n_pages * len(people), sms_on=_sms_on(),
                           in_hours=bc.in_send_hours(), phone=phone)


@bp.post("/messages/test")
@role_required()
def messages_test():
    """Send the draft to ONE number (the admin's own) so it can be read on a real phone before everyone gets it."""
    b = db.session.get(Broadcast, request.form.get("id", type=int) or 0)
    phone = normalize_phone(request.form.get("phone", ""))
    provider = provider_from_config(current_app.config)
    if not b or b.status != "draft":
        flash("That draft is no longer available. Start again.")
        return redirect(url_for("admin.messages"))
    if provider is None:
        flash("SMS is switched off, so nothing can be sent.")
    elif not phone:
        flash("Enter a valid Nigerian mobile number for the test.")
    elif not bc.in_send_hours():
        flash("Texts can only be sent between 8am and 8pm. Try the test again in the morning.")
    else:
        sample = Person(full_name=current_user().username, phone=phone)
        res = provider.send(phone, bc.render(b.text, sample))
        flash("Test sent. Check your phone." if res.ok else f"The test failed: {res.error or res.code}")
        audit(current_user().username, "message_test", f"draft {b.id}")
    return redirect(url_for("admin.messages_preview_again", bid=b.id))


@bp.get("/messages/<int:bid>/preview")
@role_required()
def messages_preview_again(bid: int):
    b = db.session.get(Broadcast, bid)
    if not b or b.status != "draft":
        return redirect(url_for("admin.messages"))
    return _preview_page(b, 0, request.args.get("phone", ""))


@bp.post("/messages/<int:bid>/send")
@role_required()
def messages_send(bid: int):
    if request.form.get("sure") != "yes":
        flash("Tick the box to confirm you have checked the message and the number of people.")
        return redirect(url_for("admin.messages_preview_again", bid=bid))
    if not _sms_on():
        flash("SMS is switched off, so nothing was sent.")
        return redirect(url_for("admin.messages_preview_again", bid=bid))
    if request.form.get("selection") == "1":
        if bc.apply_selection(bid, {int(x) for x in request.form.getlist("person") if x.isdigit()}) == 0:
            flash("No one is ticked. Tick at least one person.")
            return redirect(url_for("admin.messages_preview_again", bid=bid))
    if bc.confirm(bid):
        audit(current_user().username, "message_send", f"broadcast {bid}")
        bc.start_in_background(current_app._get_current_object(), bid)
    return redirect(url_for("admin.message_status", bid=bid))


@bp.get("/messages/<int:bid>")
@role_required()
def message_status(bid: int):
    b = db.session.get(Broadcast, bid)
    if not b or b.status == "draft":
        return redirect(url_for("admin.messages"))
    c = bc.counts(b)
    return render_template("message_status.html", b=b, c=c, active=c["pending"] + c["sending"] > 0 and b.status == "queued",
                           in_hours=bc.in_send_hours(), rows=b.recipients)


@bp.post("/messages/<int:bid>/cancel")
@role_required()
def message_cancel(bid: int):
    bc.cancel(bid)
    audit(current_user().username, "message_cancel", f"broadcast {bid}")
    flash("Stopped. People not yet texted will not be texted.")
    return redirect(url_for("admin.message_status", bid=bid))
