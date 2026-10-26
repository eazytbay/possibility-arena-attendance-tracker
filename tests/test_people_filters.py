from app.models import Attendance, Person, db
from tests.conftest import login
from tests.test_app import code


def enrol(client, **over):
    data = {"full_name": "Ada Obi", "phone": "08012345678", "category": "member"}
    data.update(over)
    return client.post("/enrol", data=data)


def test_teen_without_phone_registers_and_is_not_duplicated(client):
    login(client, "usher")
    assert enrol(client, full_name="Tosin Bello", phone="", category="teen", sex="female").status_code == 302
    again = enrol(client, full_name="tosin bello", phone="", category="teen")
    assert again.status_code == 200 and b"already on record" in again.data  # asks, does not duplicate
    assert enrol(client, full_name="tosin bello", phone="", category="teen", confirmed="1").status_code == 302
    teens = Person.query.filter_by(category="teen").all()
    assert len(teens) == 1 and teens[0].phone is None and teens[0].sex == "female"
    assert Attendance.query.count() == 1
    assert client.get("/api/search?q=tosin").get_json()[0]["category"] == "teen"


def test_phone_still_required_for_adults(client):
    login(client, "usher")
    assert b"valid Nigerian mobile" in enrol(client, phone="").data
    assert Person.query.count() == 0


def test_children_age_groups_stop_at_twelve(client):
    from app.models import AGE_GROUPS
    assert "13-17" not in AGE_GROUPS and "10-12" in AGE_GROUPS


def test_people_page_filters_and_csv(client):
    login(client, "usher")
    enrol(client, full_name="Ada Obi", phone="08012345678", category="worker", department="Choir", sex="female",
          birth_month="3", birth_day="5")
    enrol(client, full_name="Bayo Ojo", phone="08022222222", category="member", sex="male")
    enrol(client, full_name="Tosin Bello", phone="", category="teen", sex="female")
    client.post("/logout"); login(client, "admin")
    page = client.get("/admin/people?department=Choir").data.decode()
    assert "Ada Obi" in page and "Bayo Ojo" not in page
    assert "Tosin Bello" in client.get("/admin/people?category=teen").data.decode()
    assert "Ada Obi" in client.get("/admin/people?month=3").data.decode()
    both = client.get("/admin/people?sex=female").data.decode()
    assert "Ada Obi" in both and "Tosin Bello" in both and "Bayo Ojo" not in both
    csv_ = client.get("/admin/export/people.csv?sex=male").data.decode("utf-8-sig")
    assert "Bayo Ojo" in csv_ and "Ada Obi" not in csv_ and csv_.splitlines()[0].startswith("name,phone,category,department,sex")


def test_people_page_is_admin_only(client):
    login(client, "usher")
    assert client.get("/admin/people").status_code == 403


def test_attendance_csv_filters_by_sex_and_category(client):
    from app.services.attendance import today_local
    login(client, "usher")
    enrol(client, full_name="Ada Obi", phone="08012345678", sex="female")
    enrol(client, full_name="Bayo Ojo", phone="08022222222", sex="male")
    client.post("/logout"); login(client, "admin")
    d = today_local().isoformat()
    body = client.get(f"/admin/export/attendance.csv?date={d}&sex=male").data.decode("utf-8-sig")
    assert "Bayo Ojo" in body and "Ada Obi" not in body
