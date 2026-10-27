import io

from PIL import Image

from app.models import Person, db
from tests.conftest import login


def make(name="Ada Obi", phone="08012345678", **kw):
    p = Person(full_name=name, phone=phone, category=kw.pop("category", "member"), **kw)
    db.session.add(p)
    db.session.commit()
    return p


def jpeg():
    b = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(b, "JPEG")
    b.seek(0)
    return b


def post(client, p, **over):
    data = {"full_name": p.full_name, "phone": p.phone or "", "category": p.category}
    data.update(over)
    return client.post(f"/admin/person/{p.id}/edit", data=data, content_type="multipart/form-data")


def test_edit_requires_login_and_role(client):
    p = make()
    assert client.get(f"/admin/person/{p.id}/edit").status_code == 302
    login(client, "usher")
    assert client.get(f"/admin/person/{p.id}/edit").status_code == 403


def test_page_renders_for_adult_and_child(client):
    adult = make()
    kid = Person(full_name="Tomi Obi", category="child", guardian_id=adult.id, age_group="3-5")
    db.session.add(kid); db.session.commit()
    login(client, "admin")
    assert b"Ada Obi" in client.get(f"/admin/person/{adult.id}/edit").data
    assert b"Age group" in client.get(f"/admin/person/{kid.id}/edit").data


def test_update_details_and_add_photo_later(client):
    p = make()
    login(client, "admin")
    r = post(client, p, department="Choir", sex="female", birth_month="3", birth_day="9", sms_opt_in="1",
             photo=(jpeg(), "me.jpg"))
    assert r.status_code == 302
    p = db.session.get(Person, p.id)
    assert (p.department, p.sex, p.birth_month, p.birth_day) == ("Choir", "female", 3, 9)
    assert p.has_photo and p.photo
    assert client.get(f"/photo/{p.id}.jpg").status_code == 200


def test_remove_photo_and_stop_greetings(client):
    p = make(has_photo=True, photo=b"x")
    login(client, "admin")
    post(client, p, remove_photo="1")  # sms_opt_in box left unticked
    p = db.session.get(Person, p.id)
    assert not p.has_photo and p.photo is None and p.sms_opt_in is False


def test_phone_cannot_be_taken_by_someone_else(client):
    a, b = make(), make("Bola Ade", "08022222222")
    login(client, "admin")
    r = post(client, b, phone="0801 234 5678")
    assert r.status_code == 200 and b"already belongs to Ada Obi" in r.data
    assert db.session.get(Person, b.id).phone == "08022222222"


def test_validation_errors_keep_record_unchanged(client):
    p = make()
    login(client, "admin")
    assert b"valid Nigerian mobile" in post(client, p, phone="123").data
    assert b"not a valid date" in post(client, p, birth_month="2", birth_day="30").data
    assert db.session.get(Person, p.id).phone == "08012345678"


def test_teen_without_phone_ok_adult_without_phone_not(client):
    teen = make("Tosin Bello", None, category="teen")
    login(client, "admin")
    assert post(client, teen, sex="female").status_code == 302
    adult = make()
    assert b"valid Nigerian mobile" in post(client, adult, phone="").data


def test_edit_child(client):
    adult = make()
    kid = Person(full_name="Tomi Obi", category="child", guardian_id=adult.id, age_group="3-5")
    db.session.add(kid); db.session.commit()
    login(client, "admin")
    r = client.post(f"/admin/person/{kid.id}/edit", data={"full_name": "Tomiwa Obi", "age_group": "6-9", "notes": "nuts"})
    kid = db.session.get(Person, kid.id)
    assert r.status_code == 302 and (kid.full_name, kid.age_group, kid.notes) == ("Tomiwa Obi", "6-9", "nuts")
    assert kid.guardian_id == adult.id
