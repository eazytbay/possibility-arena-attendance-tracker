from flask import Blueprint, render_template, request

from .. import limiter
from ..models import ADULT_CATEGORIES, AGE_GROUPS, DEPARTMENTS
from ..services.attendance import (add_child, get_or_create_service, mark_present,
                                   upsert_adult, visitor_status)
from ..services.phone import normalize_phone

bp = Blueprint("public", __name__)


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("60 per minute", methods=["POST"])  # a whole congregation may share one church Wi-Fi IP
def register():
    ctx = dict(categories=ADULT_CATEGORIES, departments=DEPARTMENTS, age_groups=AGE_GROUPS, error=None, form={})
    if request.method == "GET":
        return render_template("register.html", **ctx)

    f = request.form
    ctx["form"] = f
    if f.get("website"):  # honeypot field: real people never fill it
        return render_template("done.html", name="friend", status="", children=[], welcome_back=False)
    name = " ".join(f.get("full_name", "").split())[:120]
    phone = normalize_phone(f.get("phone"))
    category = f.get("category", "")
    department = f.get("department") or None
    if len(name) < 3:
        ctx["error"] = "Please enter your full name."
    elif not phone:
        ctx["error"] = "Enter a valid Nigerian mobile number, for example 08012345678."
    elif category not in ADULT_CATEGORIES:
        ctx["error"] = "Please choose who you are."
    elif department and department not in DEPARTMENTS:
        ctx["error"] = "Please choose a department from the list."
    if ctx["error"]:
        return render_template("register.html", **ctx), 400

    if category == "visitor":
        department = None
    person, created = upsert_adult(name, phone, category, department)
    svc = get_or_create_service()
    status = visitor_status(person, svc)
    mark_present(person, svc, source="self")

    kids = []
    names = f.getlist("child_name")
    ages = f.getlist("child_age")
    notes = f.getlist("child_notes")
    for i, cname in enumerate(names[:12]):
        cname = " ".join(cname.split())[:120]
        if not cname:
            continue
        age = ages[i] if i < len(ages) and ages[i] in AGE_GROUPS else None
        note = (notes[i] if i < len(notes) else "").strip()[:300] or None
        kids.append(add_child(person, cname, age, note))
    return render_template("done.html", name=person.full_name.split()[0], status=status,
                           children=kids, welcome_back=not created)
