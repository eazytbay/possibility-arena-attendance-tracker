from flask import Blueprint, render_template, request

from .. import limiter
from ..models import ADULT_CATEGORIES, AGE_GROUPS, DEPARTMENTS, Person
from ..services.attendance import (add_child, code_is_valid, get_or_create_service, mark_present,
                                   upsert_adult, visitor_status)
from ..services.phone import normalize_phone

bp = Blueprint("public", __name__)


def _page(step, form, error=None, status=200):
    return render_template("register.html", step=step, form=form, error=error, categories=ADULT_CATEGORIES,
                           departments=DEPARTMENTS, age_groups=AGE_GROUPS), status


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("60 per minute", methods=["POST"])  # a whole congregation may share one church Wi-Fi IP
def register():
    if request.method == "GET":
        return _page("attend", {})

    f = request.form
    if f.get("website"):  # honeypot field: real people never fill it
        return render_template("done.html", name="friend", status="", children=[], welcome_back=False)

    step = f.get("step", "full")
    svc = get_or_create_service()
    if not svc.registration_open:
        return _page("attend", f, "Attendance is closed for today. Please see an usher.", 403)
    if not code_is_valid(svc, f.get("code", "")):
        return _page("attend", f, "That service code is not correct. Ask an usher for today's code.", 400)

    phone = normalize_phone(f.get("phone"))
    if not phone:
        return _page(step, f, "Enter a valid Nigerian mobile number, for example 08012345678.", 400)

    if step == "attend":
        person = Person.query.filter_by(phone=phone).first()
        if person and person.category != "child":
            _, _created = mark_present(person, svc, source="self")
            return render_template("done.html", name=person.full_name.split()[0],
                                   status=visitor_status(person, svc),
                                   children=list(person.children), welcome_back=True)
        return _page("full", f, "We do not have this number yet. Please complete your details once.")

    name = " ".join(f.get("full_name", "").split())[:120]
    category = f.get("category", "")
    department = f.get("department") or None
    error = None
    if len(name) < 3:
        error = "Please enter your full name."
    elif category not in ADULT_CATEGORIES:
        error = "Please choose who you are."
    elif department and department not in DEPARTMENTS:
        error = "Please choose a department from the list."
    if error:
        return _page("full", f, error, 400)

    if category == "visitor":
        department = None
    person, created = upsert_adult(name, phone, category, department)
    status = visitor_status(person, svc)
    mark_present(person, svc, source="self")

    kids = []
    names, ages, notes = f.getlist("child_name"), f.getlist("child_age"), f.getlist("child_notes")
    for i, cname in enumerate(names[:12]):
        cname = " ".join(cname.split())[:120]
        if not cname:
            continue
        age = ages[i] if i < len(ages) and ages[i] in AGE_GROUPS else None
        note = (notes[i] if i < len(notes) else "").strip()[:300] or None
        kids.append(add_child(person, cname, age, note))
    return render_template("done.html", name=person.full_name.split()[0], status=status,
                           children=kids or list(person.children), welcome_back=not created)
