from functools import wraps

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from werkzeug.security import check_password_hash

from .. import limiter
from ..models import User, db
from ..services.attendance import audit

bp = Blueprint("auth", __name__)
_DUMMY_HASH = "scrypt:32768:8:1$x$" + "0" * 128  # constant-work path for unknown users


def current_user():
    uid = session.get("uid")
    return db.session.get(User, uid) if uid else None


def role_required(*roles):
    """Admins may access everything; other roles only what is listed."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if not user:
                return redirect(url_for("auth.login", next=request.path))
            if user.role not in ("owner", "admin") and user.role not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def owner_required(fn):
    """Only the owner may manage logins."""
    @wraps(fn)
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        if user.role != "owner":
            abort(403)
        return fn(*a, **kw)
    return wrapper


def landing_for(user) -> str:
    return url_for({"owner": "admin.dashboard", "admin": "admin.dashboard", "children": "staff.children", "media": "staff.enrol"}[user.role])


@bp.get("/")
def index():
    user = current_user()
    return redirect(landing_for(user) if user else url_for("public.register"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    error = None
    if request.method == "POST":
        ident = request.form.get("username", "").strip().lower()
        user = User.query.filter(or_(User.username == ident, User.email == ident)).first() if ident else None
        ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, request.form.get("password", ""))
        if user and ok:
            session.clear()
            session["uid"] = user.id
            audit(user.username, "login")
            return redirect(landing_for(user))
        error = "Wrong username or password."
    return render_template("login.html", error=error)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
