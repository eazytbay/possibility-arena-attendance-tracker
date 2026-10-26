from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

ADULT_CATEGORIES = ("member", "worker", "minister", "visitor")
REGISTER_CATEGORIES = ("member", "worker", "minister", "teen", "visitor")  # who staff can register
CATEGORIES = REGISTER_CATEGORIES + ("child",)
SEXES = ("male", "female")
DEPARTMENTS = (
    "Choir", "Ushers", "Protocol", "Media", "Sanitation", "Welfare",
    "Intercessors", "Technical", "Counsellors", "Sunday School",
)
ROLES = ("owner", "admin", "media", "usher", "children")
AGE_GROUPS = ("0-2", "3-5", "6-9", "10-12")  # children; 13 and over register as teens
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Person(db.Model):
    __tablename__ = "people"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(15), unique=True, nullable=True)
    category = db.Column(db.String(12), nullable=False)
    department = db.Column(db.String(40), nullable=True)
    sex = db.Column(db.String(6), nullable=True)
    age_group = db.Column(db.String(8), nullable=True)
    notes = db.Column(db.String(300), nullable=True)
    birth_month = db.Column(db.SmallInteger, nullable=True)  # day and month only, never the year
    birth_day = db.Column(db.SmallInteger, nullable=True)
    sms_opt_in = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    has_photo = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    photo = db.deferred(db.Column(db.LargeBinary, nullable=True))  # small JPEG thumbnail, adults only
    guardian_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    guardian = db.relationship("Person", remote_side=[id], backref="children")


class Service(db.Model):
    __tablename__ = "services"
    id = db.Column(db.Integer, primary_key=True)
    service_date = db.Column(db.Date, unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    access_code = db.Column(db.String(8), nullable=True)
    registration_open = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (db.UniqueConstraint("service_id", "person_id", name="uq_service_person"),)
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=False, index=True)
    checked_in_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    checked_in_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    source = db.Column(db.String(10), nullable=False, default="usher")
    pickup_code = db.Column(db.String(4), nullable=True)
    category_at_visit = db.Column(db.String(10), nullable=True)  # category on that Sunday (survives promotion)
    released_at = db.Column(db.DateTime(timezone=True), nullable=True)
    released_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    service = db.relationship("Service")
    person = db.relationship("Person")


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    actor = db.Column(db.String(40), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(300), nullable=True)


class MessageLog(db.Model):
    """One row per greeting per person per day/month. The unique key makes sending safe to repeat."""
    __tablename__ = "message_log"
    __table_args__ = (db.UniqueConstraint("person_id", "kind", "period_key", name="uq_message_once"),)
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)          # birthday | new_month
    period_key = db.Column(db.String(10), nullable=False)    # 2026-11-05 or 2026-11
    status = db.Column(db.String(8), nullable=False)         # sent | failed
    attempts = db.Column(db.SmallInteger, nullable=False, default=0)
    provider_id = db.Column(db.String(64), nullable=True)
    error = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    person = db.relationship("Person")
