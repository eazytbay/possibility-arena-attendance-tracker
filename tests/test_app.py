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
    login(client, "media")
    r = client.post("/api/visitor", json={"name": "Guest One", "phone": "08099999999"})
    assert r.get_json()["status"] == "first-time visitor"


def test_staff_checkin_idempotent(client):
    reg(client)
    pid = Person.query.one().id
    Attendance.query.delete(); db.session.commit()
    login(client, "media")
    assert client.post(f"/api/checkin/{pid}").get_json()["created"] is True
    assert client.post(f"/api/checkin/{pid}").get_json()["created"] is False
    assert Attendance.query.count() == 1


def test_search_finds_by_name_and_phone(client):
    reg(client)
    login(client, "media")
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
    login(client, "media")
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
    login(client, "media")
    page = client.get("/display").data.decode()
    assert code() in page
    assert client.get("/admin/qr.png").status_code == 200
    for url in ("/admin/", "/admin/export/people.csv", "/children"):
        assert client.get(url).status_code == 403, url
    assert client.get("/checkin").status_code == 200


def test_staff_enrol_registers_and_marks_present(client):
    login(client, "media")
    r = client.post("/enrol", data={"full_name": "Chidi Eze", "phone": "07011112222", "category": "visitor",
                                    "child_name": ["Ife"], "child_age": ["6-9"], "child_notes": [""]})
    assert r.status_code == 302
    p = Person.query.filter_by(phone="07011112222").one()
    att = Attendance.query.filter_by(person_id=p.id).one()
    assert att.source == "staff" and att.checked_in_by is not None
    assert Person.query.filter_by(category="child").one().guardian_id == p.id


def test_staff_enrol_rejects_bad_input(client):
    login(client, "media")
    assert b"valid Nigerian mobile" in client.post("/enrol", data={"full_name": "Chidi Eze", "phone": "1",
                                                                    "category": "member"}).data


def test_enrol_requires_login(client):
    assert client.get("/enrol").status_code == 302


def test_closed_public_page_hides_form(client):
    from app.services.attendance import get_or_create_service
    svc = get_or_create_service(); svc.registration_open = False; db.session.commit()
    assert b"welcome team" in client.get("/register").data


def test_login_with_email_and_no_user_creation_route(client):
    from werkzeug.security import generate_password_hash
    from app.models import User
    db.session.add(User(username="grace", email="grace@example.com", role="media",
                        password_hash=generate_password_hash("password123")))
    db.session.commit()
    r = client.post("/login", data={"username": "Grace@Example.com", "password": "password123"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/enrol")
    login(client, "admin")
    assert client.post("/admin/users", data={"username": "x", "role": "admin", "password": "password123"}).status_code in (404, 405)
    page = client.get("/admin/").data.decode()
    assert "Staff logins" not in page and "Register a person" in page


def _mk(role, name):
    from werkzeug.security import generate_password_hash
    from app.models import User
    db.session.add(User(username=name, role=role, password_hash=generate_password_hash("password123")))
    db.session.commit()


def test_only_owner_can_manage_team(client):
    _mk("owner", "boss")
    login(client, "admin")                       # a normal admin
    assert client.get("/admin/team").status_code == 403
    assert client.post("/admin/team", data={"username": "sneaky", "role": "admin", "password": "password123"}).status_code == 403
    client.post("/logout")
    login(client, "boss")
    assert client.get("/admin/team").status_code == 200
    client.post("/admin/team", data={"username": "newmedia", "email": "n@x.org", "role": "media", "password": "password123"})
    from app.models import User
    assert User.query.filter_by(username="newmedia").one().role == "media"


def test_owner_cannot_create_second_owner_or_be_deleted(client):
    from app.models import User
    _mk("owner", "boss")
    login(client, "boss")
    client.post("/admin/team", data={"username": "rival", "role": "owner", "password": "password123"})
    assert User.query.filter_by(username="rival").count() == 0
    boss = User.query.filter_by(username="boss").one()
    client.post(f"/admin/team/{boss.id}/delete")
    assert User.query.filter_by(username="boss").count() == 1


def test_demo_seed_and_isolation(tmp_path):
    from app import create_app
    from app.demo import reset_demo
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "WTF_CSRF_ENABLED": False, "DEMO_MODE": False,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/d.db", "RATELIMIT_ENABLED": False})
    with app.app_context():
        reset_demo()
        assert Person.query.count() > 40 and Attendance.query.count() > 50
        c = app.test_client()
        r = c.post("/login", data={"username": "demo-owner", "password": "demo-password"})
        assert r.status_code == 302
        assert c.get("/admin/export/attendance.csv").status_code == 200


def test_export_by_date_and_all(client):
    reg(client)
    login(client, "admin")
    from app.services.attendance import today_local
    d = today_local().isoformat()
    body = client.get(f"/admin/export/attendance.csv?date={d}").data.decode("utf-8-sig")
    assert "Ada Obi" in body
    allcsv = client.get("/admin/export/all-attendance.csv").data.decode("utf-8-sig")
    assert allcsv.splitlines()[0].startswith("service_date") and "Ada Obi" in allcsv
    r = client.get("/admin/export/attendance.csv?date=2020-01-05", follow_redirects=True)
    assert b"No attendance was recorded" in r.data


def test_birthday_saved_validated_and_exported(client):
    login(client, "media")
    base = {"full_name": "Chidi Eze", "phone": "07011112222", "category": "member"}
    bad = client.post("/enrol", data={**base, "birth_month": "2", "birth_day": "30"})
    assert b"not a valid date" in bad.data and Person.query.count() == 0
    half = client.post("/enrol", data={**base, "birth_month": "5"})
    assert b"both the month and the day" in half.data
    assert client.post("/enrol", data={**base, "birth_month": "2", "birth_day": "29"}).status_code == 302
    p = Person.query.one()
    assert (p.birth_month, p.birth_day) == (2, 29)
    client.post("/logout"); login(client, "admin")
    assert "29 Feb" in client.get("/admin/export/people.csv").data.decode("utf-8-sig")
    # re-registering without a birthday must not erase it
    client.post("/enrol", data=base)
    assert Person.query.one().birth_month == 2


def _jpeg(w=2000, h=1500):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.effect_noise((w, h), 40).convert("RGB").save(buf, "JPEG", quality=95)
    buf.seek(0)
    return buf


def test_photo_shrunk_stored_and_protected(client):
    import io
    from PIL import Image
    login(client, "media")
    r = client.post("/enrol", data={"full_name": "Chidi Eze", "phone": "07011112222", "category": "member",
                                    "photo": (_jpeg(), "big.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 302
    p = Person.query.one()
    assert p.has_photo and len(p.photo) < 40_000
    img = Image.open(io.BytesIO(p.photo))
    assert img.size == (240, 240) and img.format == "JPEG"
    assert client.get(f"/photo/{p.id}.jpg").mimetype == "image/jpeg"
    assert client.get(f"/api/search?q=chidi").get_json()[0]["photo"] is True
    client.post("/logout")
    assert client.get(f"/photo/{p.id}.jpg").status_code == 302       # not logged in


def test_bad_photo_rejected_and_nothing_saved(client):
    import io
    login(client, "media")
    r = client.post("/enrol", data={"full_name": "Chidi Eze", "phone": "07011112222", "category": "member",
                                    "photo": (io.BytesIO(b"not an image"), "x.jpg")},
                    content_type="multipart/form-data")
    assert b"not a valid photo" in r.data and Person.query.count() == 0


def test_children_never_have_photo_served(client):
    login(client, "media")
    client.post("/enrol", data={"full_name": "Ada Obi", "phone": "08012345678", "category": "member",
                                "child_name": ["Tomi"], "child_age": ["3-5"], "child_notes": [""]})
    kid = Person.query.filter_by(category="child").one()
    kid.photo, kid.has_photo = b"x", True; db.session.commit()
    assert client.get(f"/photo/{kid.id}.jpg").status_code == 404


def test_photo_data_from_camera_page_is_stored(client):
    import base64, io
    from PIL import Image
    login(client, "media")
    buf = io.BytesIO(); Image.new("RGB", (240, 240), (120, 60, 20)).save(buf, "JPEG", quality=70)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    r = client.post("/enrol", data={"full_name": "Ada Obi", "phone": "07022223333", "category": "member",
                                    "photo_data": url})
    assert r.status_code == 302
    p = Person.query.filter_by(full_name="Ada Obi").one()
    assert p.has_photo and Image.open(io.BytesIO(p.photo)).size == (240, 240)


def test_bad_photo_data_rejected_and_nothing_saved(client):
    login(client, "media")
    r = client.post("/enrol", data={"full_name": "Ada Obi", "phone": "07022223333", "category": "member",
                                    "photo_data": "data:image/jpeg;base64,@@@notbase64@@@"})
    assert b"not a valid photo" in r.data and Person.query.count() == 0


def test_forms_show_camera_and_gallery_buttons(client):
    login(client, "media")
    html = client.get("/enrol").get_data(as_text=True)
    assert "Take photo" in html and "Choose from gallery" in html and 'capture="environment"' in html
    assert 'type="file" accept="image/*">' not in html.replace('hidden', '').replace('id="photo-in-pick" ', '')
