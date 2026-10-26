from app.models import Attendance, Person
from tests.conftest import login


def enrol(client, **over):
    data = {"full_name": "Ada Obi", "phone": "08012345678", "category": "member"}
    data.update(over)
    return client.post("/enrol", data=data)


def test_second_registration_same_day_asks_and_changes_nothing(client):
    login(client, "usher")
    assert enrol(client, department="Choir").status_code == 302
    r = enrol(client, full_name="Adaora Obi", department="Media")
    assert r.status_code == 200
    assert b"already on record" in r.data and b"already marked present today" in r.data
    assert b"different from the name on record" in r.data
    p = Person.query.one()
    assert p.full_name == "Ada Obi" and p.department == "Choir"   # nothing was overwritten
    assert Attendance.query.count() == 1


def test_confirming_updates_the_details(client):
    login(client, "usher")
    enrol(client)
    r = enrol(client, full_name="Adaora Obi", confirmed="1")
    assert r.status_code == 302
    assert Person.query.one().full_name == "Adaora Obi" and Attendance.query.count() == 1


def test_registered_in_the_week_then_again_on_sunday_is_flagged_not_duplicated(client, app):
    from datetime import date, timedelta
    from app.models import Service, db
    login(client, "usher")
    enrol(client)
    # make the first registration look like it happened on an earlier day
    old = Service(service_date=date.today() - timedelta(days=4), name="midweek", access_code="ABCDE")
    db.session.add(old)
    db.session.flush()
    a = Attendance.query.one()
    a.service_id = old.id
    db.session.commit()
    r = enrol(client)  # same name, new day: no clash, just marks present
    assert r.status_code == 302
    assert Person.query.count() == 1 and Attendance.query.count() == 2


def test_same_name_not_yet_present_just_goes_through(client):
    login(client, "usher")
    from app.models import db
    db.session.add(Person(full_name="Ada Obi", phone="08012345678", category="member"))
    db.session.commit()
    assert enrol(client).status_code == 302


def test_self_registration_cannot_overwrite_someone_elses_record(client, app):
    from app.models import db
    from app.services.attendance import get_or_create_service
    svc = get_or_create_service()
    svc.registration_open = True
    db.session.add(Person(full_name="Ada Obi", phone="08012345678", category="member"))
    db.session.commit()
    r = client.post("/register", data={"code": svc.access_code, "full_name": "Someone Else", "phone": "08012345678",
                                       "category": "visitor", "step": "full"})
    assert Person.query.one().full_name == "Ada Obi"
    assert r.status_code in (200, 400, 409)


def test_children_typed_are_kept_when_the_notice_appears(client):
    login(client, "usher")
    enrol(client)
    r = enrol(client, child_name=["Tomi Obi"], child_age=["3-5"], child_notes=["peanut allergy"], confirmed="")
    assert r.status_code == 200 and b"Tomi Obi" in r.data and b"peanut allergy" in r.data


def test_adding_a_child_to_a_parent_already_on_record(client):
    login(client, "usher")
    enrol(client)
    r = enrol(client, child_name=["Tomi Obi"], child_age=["3-5"], child_notes=[""], confirmed="1")
    assert r.status_code == 302
    kid = Person.query.filter_by(category="child").one()
    assert kid.guardian.full_name == "Ada Obi" and Attendance.query.count() == 1


def test_children_page_shows_totals_and_age_filters(client):
    login(client, "usher")
    enrol(client, child_name=["Tomi Obi", "Bayo Obi"], child_age=["3-5", "6-9"], child_notes=["", ""])
    from tests.conftest import login as lg
    c2 = client.application.test_client()
    lg(c2, "kids")
    page = c2.get("/children").data.decode()
    assert "2</strong> children on record" in page and "3-5 (1)" in page and "6-9 (1)" in page


def test_pickup_code_only_for_ages_zero_to_five(client):
    login(client, "usher")
    enrol(client, child_name=["Tiny", "Mid", "Big", "Unknown"], child_age=["0-2", "3-5", "6-9", ""], child_notes=["", "", "", ""])
    login(client, "kids")
    out = {k.full_name: client.post(f"/api/children/{k.id}/checkin").get_json()
           for k in Person.query.filter_by(category="child")}
    assert len(out["Tiny"]["code"]) == 4 and len(out["Mid"]["code"]) == 4 and len(out["Unknown"]["code"]) == 4
    assert out["Big"]["code"] == "" and out["Big"]["needs_code"] is False
    a = Attendance.query.join(Person).filter(Person.full_name == "Big").one()
    assert a.pickup_code is None
    page = client.get("/children").data.decode()
    assert "no pickup code needed" in page
