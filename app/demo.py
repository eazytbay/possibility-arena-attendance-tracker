"""Demo mode: fake data only, reset once a day. Never enabled on the real church app."""
import random
import threading
from datetime import timedelta

from werkzeug.security import generate_password_hash

from .models import (AGE_GROUPS, DEPARTMENTS, Attendance, AuditLog, Person, Service, User, db)
from .services.attendance import (assign_pickup_code, get_or_create_service, new_access_code,
                                  today_local)

_FIRST = ["Adaeze", "Tunde", "Ngozi", "Emeka", "Folake", "Chidi", "Bisi", "Yemi", "Amaka", "Segun",
          "Kemi", "Obinna", "Funmi", "Ibrahim", "Grace", "Daniel", "Ruth", "Samuel", "Esther", "Peter"]
_LAST = ["Adeyemi", "Okafor", "Balogun", "Nwosu", "Ajayi", "Eze", "Lawal", "Okeke", "Bello", "Akande"]
_KIDS = ["Tobi", "Ife", "Chika", "Dami", "Zainab", "Kunle", "Ada", "Femi"]

_lock = threading.Lock()
_state = {"day": None}


def reset_demo() -> None:
    db.drop_all()
    db.create_all()
    rnd = random.Random(2026)
    for name, role in (("demo-owner", "owner"), ("demo-media", "media"), ("demo-children", "children")):
        db.session.add(User(username=name, role=role, password_hash=generate_password_hash("demo-password")))
    adults = []
    for i in range(36):
        cat = rnd.choices(["member", "worker", "minister", "visitor"], [18, 10, 2, 6])[0]
        dept = rnd.choice(DEPARTMENTS) if cat in ("worker", "minister") else None
        p = Person(full_name=f"{_FIRST[i % len(_FIRST)]} {_LAST[(i * 3) % len(_LAST)]}",
                   phone=f"0801000{i:04d}", category=cat, department=dept)
        db.session.add(p)
        adults.append(p)
    db.session.commit()
    kids = []
    for j, parent in enumerate(adults[:10]):
        k = Person(full_name=f"{_KIDS[j % len(_KIDS)]} {parent.full_name.split()[1]}", category="child",
                   age_group=AGE_GROUPS[j % len(AGE_GROUPS)], guardian_id=parent.id,
                   notes="Allergic to groundnuts" if j == 2 else None)
        db.session.add(k)
        kids.append(k)
    db.session.commit()
    today = today_local()
    for weeks in (3, 2, 1):
        svc = Service(service_date=today - timedelta(days=7 * weeks), name="Past service",
                      access_code=new_access_code())
        db.session.add(svc)
        db.session.commit()
        for p in rnd.sample(adults, 24):
            db.session.add(Attendance(service_id=svc.id, person_id=p.id, source="staff"))
        db.session.commit()
    svc = get_or_create_service()
    for p in adults[:14]:
        db.session.add(Attendance(service_id=svc.id, person_id=p.id, source=rnd.choice(["self", "staff"])))
    db.session.commit()
    for k in kids[:3]:
        att = Attendance(service_id=svc.id, person_id=k.id, source="staff")
        db.session.add(att)
        db.session.commit()
        assign_pickup_code(att)
    db.session.add(AuditLog(actor="demo", action="reset", detail="demo data created"))
    db.session.commit()


def install_demo(app) -> None:
    @app.before_request
    def _daily_reset():
        today = today_local()
        if _state["day"] == today:
            return
        with _lock:
            if _state["day"] != today:
                reset_demo()
                _state["day"] = today
