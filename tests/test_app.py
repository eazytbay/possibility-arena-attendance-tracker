from app.models import Attendance, Person, db
from app.services.attendance import _safe
from app.services.phone import normalize_phone
from tests.conftest import login


def test_phone_normalisation():
    assert normalize_phone("0801 234 5678") == "08012345678"
    assert normalize_phone("+2348012345678") == "08012345678"
    assert normalize_phone("8012345678") == "08012345678"
    assert normalize_phone("12345") is None
    assert normalize_phone("") is None


def test_csv_formula_injection_neutralised():
    assert _safe("=1+1") == "'=1+1"
    assert _safe("Ada") == "Ada"


def code():
    from app.services.attendance import get_or_create_service
    return get_or_create_service().access_code


def reg(client, **over):
    data = {"full_name": "Ada Obi", "phone": "08012345678", "category": "member", "code": code()}
    data.update(over)
    return client.post("/register", data=data)


def test_register_creates_person_and_attendance(client):
    assert reg(client).status_code == 200
    assert Person.query.count() == 1
    assert Attendance.query.count() == 1


def test_register_twice_is_idempotent(client):
    reg(client)
    reg(client, full_name="Ada Obi-Eze")
    assert Person.query.count() == 1
    assert Attendance.query.count() == 1


def test_register_rejects_bad_phone(client):
    assert reg(client, phone="123").status_code == 400
    assert Person.query.count() == 0


def test_honeypot_blocks_bots(client):
    reg(client, website="spam.example")
    assert Person.query.count() == 0


def test_known_member_not_downgraded_to_visitor(client):
    reg(client, category="worker", department="Choir")
    reg(client, category="visitor")
    assert Person.query.one().category == "worker"


def test_children_registered_under_guardian(client):
    client.post("/register", data={"full_name": "Ada Obi", "phone": "08012345678", "category": "member",
                                   "code": code(), "child_name": ["Tomi", ""], "child_age": ["3-5", ""], "child_notes": ["nuts", ""]})
    kid = Person.query.filter_by(category="child").one()
    assert kid.guardian.full_name == "Ada Obi" and kid.phone is None
    assert Attendance.query.count() == 1  # parent only; child checked in by ministry


def test_visitor_status_first_time(client):
    login(client, "usher")
    r = client.post("/api/visitor", json={"name": "Guest One", "phone": "08099999999"})
    assert r.get_json()["status"] == "first-time visitor"


def test_usher_checkin_idempotent(client):
    reg(client)
    pid = Person.query.one().id
    Attendance.query.delete(); db.session.commit()
    login(client, "usher")
    assert client.post(f"/api/checkin/{pid}").get_json()["created"] is True
    assert client.post(f"/api/checkin/{pid}").get_json()["created"] is False
    assert Attendance.query.count() == 1


def test_search_finds_by_name_and_phone(client):
    reg(client)
    login(client, "usher")
    assert client.get("/api/search?q=ada").get_json()[0]["name"] == "Ada Obi"
    assert client.get("/api/search?q=5678").get_json()[0]["phone_tail"] == "5678"


def test_children_pickup_flow(client):
    client.post("/register", data={"full_name": "Ada Obi", "phone": "08012345678", "category": "member",
                                   "code": code(), "child_name": ["Tomi"], "child_age": ["3-5"], "child_notes": [""]})
    kid = Person.query.filter_by(category="child").one()
    login(client, "kids")
    pcode = client.post(f"/api/children/{kid.id}/checkin").get_json()["code"]
    assert len(pcode) == 4
    assert client.post("/api/children/release", json={"code": "0000" if pcode != "0000" else "1111"}).status_code == 404
    ok = client.post("/api/children/release", json={"code": pcode}).get_json()
    assert ok["child"] == "Tomi" and ok["guardian"] == "Ada Obi"
    assert client.post("/api/children/release", json={"code": pcode}).status_code == 404  # cannot release twice


def test_permissions(client):
    assert client.get("/admin/").status_code == 302          # not logged in
    login(client, "usher")
    assert client.get("/admin/").status_code == 403
    assert client.get("/children").status_code == 403
    assert client.get("/checkin").status_code == 200


def test_export_csv(client):
    reg(client, full_name="=cmd|' /C calc'!A0")
    login(client, "admin")
    r = client.get("/admin/export/attendance.csv")
    body = r.data.decode("utf-8-sig")
    assert r.status_code == 200 and "'=cmd" in body and "\n=cmd" not in body


def test_login_wrong_password(client):
    r = client.post("/login", data={"username": "admin", "password": "nope"})
    assert b"Wrong username" in r.data


def test_pages_render(client):
    assert client.get("/register").status_code == 200
    assert client.get("/login").status_code == 200
    login(client, "admin")
    for url in ("/admin/", "/admin/poster", "/admin/qr.png", "/checkin", "/children", "/admin/export/people.csv"):
        assert client.get(url).status_code == 200, url


def test_wrong_code_blocks_registration(client):
    assert reg(client, code="WRONG").status_code == 400
    assert Person.query.count() == 0


def test_closed_registration_blocks_everyone(client):
    from app.services.attendance import get_or_create_service
    svc = get_or_create_service(); svc.registration_open = False; db.session.commit()
    assert reg(client).status_code == 403
    assert Person.query.count() == 0


def test_known_member_marks_attendance_with_code_and_phone(client):
    reg(client)
    Attendance.query.delete(); db.session.commit()
    r = client.post("/register", data={"step": "attend", "phone": "0801 234 5678", "code": code().lower()})
    assert r.status_code == 200 and Attendance.query.count() == 1 and Person.query.count() == 1


def test_unknown_phone_is_asked_for_details(client):
    r = client.post("/register", data={"step": "attend", "phone": "08055555555", "code": code()})
    assert b"complete your details" in r.data and Person.query.count() == 0


def test_admin_can_rotate_code_and_close(client):
    old = code()
    login(client, "admin")
    client.post("/admin/service/code")
    assert code() != old
    client.post("/admin/service/toggle")
    from app.services.attendance import get_or_create_service
    assert get_or_create_service().registration_open is False


def test_media_role_sees_code_only(client, app):
    from werkzeug.security import generate_password_hash
    from app.models import User
    db.session.add(User(username="media", role="media", password_hash=generate_password_hash("password123")))
    db.session.commit()
    login(client, "media")
    page = client.get("/display").data.decode()
    assert code() in page
    assert client.get("/admin/qr.png").status_code == 200
    for url in ("/admin/", "/admin/export/people.csv", "/checkin", "/children"):
        assert client.get(url).status_code == 403, url
