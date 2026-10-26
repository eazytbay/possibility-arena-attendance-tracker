from flask import Blueprint, current_app, render_template, request

from .. import limiter
from ..models import AGE_GROUPS, DEPARTMENTS, MONTHS, REGISTER_CATEGORIES, SEXES, Person
from ..services.attendance import (code_is_valid, get_or_create_service, mark_present, register_full,
                                   visitor_status)
from ..services.phone import normalize_phone
from ..services.photos import process_photo

bp = Blueprint("public", __name__)


def _page(step, form, error=None, status=200):
    demo_code = get_or_create_service().access_code if current_app.config["DEMO_MODE"] else None
    return render_template("register.html", step=step, form=form, error=error, categories=REGISTER_CATEGORIES, sexes=SEXES,
                           departments=DEPARTMENTS, age_groups=AGE_GROUPS, months=MONTHS, demo_code=demo_code), status


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("60 per minute", methods=["POST"])  # a whole congregation may share one church Wi-Fi IP
def register():
    if request.method == "GET":
        if not get_or_create_service().registration_open:
            return render_template("closed.html")
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

    try:
        photo = process_photo(request.files.get("photo"))
    except ValueError as exc:
        return _page("full", f, str(exc), 400)
    res, error = register_full(f, svc, None, "self", photo)
    if error:
        return _page("full", f, error, 400)
    person = res["person"]
    return render_template("done.html", name=person.full_name.split()[0], status=res["status"],
                           children=res["kids"], welcome_back=not res["created"])
