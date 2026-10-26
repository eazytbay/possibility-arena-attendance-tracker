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
