from datetime import date

import pytest

from app.models import Attendance, Person, Service, db
from app.services import attendance as att
from tests.conftest import login

SUNDAY, WEDNESDAY = date(2026, 11, 22), date(2026, 11, 25)


@pytest.fixture()
def sundays(app, monkeypatch):
    app.config["SERVICE_WEEKDAYS"] = "6"
    day = {"d": SUNDAY}
    monkeypatch.setattr(att, "today_local", lambda: day["d"])
    return day


def reg(client, **over):
    data = {"full_name": "Ada Obi", "phone": "08012345678", "category": "member"}
    data.update(over)
    return client.post("/enrol", data=data, follow_redirects=True)


def test_helpers(app, sundays):
    assert att.is_service_day(SUNDAY) and not att.is_service_day(WEDNESDAY)
    assert att.next_service_date(WEDNESDAY) == date(2026, 11, 29)
    assert att.next_service_date(SUNDAY) == SUNDAY
    sundays["d"] = WEDNESDAY
    assert att.todays_service() is None
    sundays["d"] = SUNDAY
    assert att.todays_service().service_date == SUNDAY
    app.config["SERVICE_WEEKDAYS"] = "2,6"                       # configurable
    assert att.is_service_day(WEDNESDAY)


def test_registration_midweek_saves_person_but_no_attendance_or_service(client, sundays):
    sundays["d"] = WEDNESDAY
    login(client, "media")
    r = reg(client)
    assert b"registered" in r.data and b"Attendance is only taken on a service day" in r.data
    assert Person.query.count() == 1 and Attendance.query.count() == 0 and Service.query.count() == 0


def test_registration_on_sunday_marks_present(client, sundays):
    login(client, "media")
    assert b"is marked present" in reg(client).data
    assert Attendance.query.count() == 1 and Service.query.one().service_date == SUNDAY


def test_checkin_pages_and_api_blocked_midweek(client, sundays):
    login(client, "media")
    p = Person(full_name="Ada Obi", phone="08012345678", category="member")
    db.session.add(p); db.session.commit()
    sundays["d"] = WEDNESDAY
    assert b"No service today" in client.get("/checkin").data
    assert b"No service today" in client.get("/display").data
    r = client.post(f"/api/checkin/{p.id}")
    assert r.status_code == 400 and "service days" in r.get_json()["error"]
    assert client.get("/api/search?q=ada").get_json()[0]["present"] is False
    assert Attendance.query.count() == 0 and Service.query.count() == 0


def test_children_blocked_midweek(client, sundays):
    login(client, "kids")
    sundays["d"] = WEDNESDAY
    assert b"No service today" in client.get("/children").data
    assert client.post("/api/children/release", json={"code": "1234"}).status_code == 400


def test_public_self_checkin_closed_midweek(client, sundays):
    sundays["d"] = WEDNESDAY
    page = client.get("/register").data
    assert b"next service is Sunday 29 November" in page
    r = client.post("/register", data={"step": "attend", "phone": "08012345678", "code": "ABCDE"})
    assert r.status_code == 403 and Attendance.query.count() == 0


def test_mark_present_refuses_a_non_service_day(app, sundays):
    p = Person(full_name="Ada Obi", phone="08012345678", category="member")
    s = Service(service_date=WEDNESDAY, name="x", access_code="ABCDE")
    db.session.add_all([p, s]); db.session.commit()
    with pytest.raises(ValueError):
        att.mark_present(p, s)


def test_admin_midweek_shows_last_sunday_and_next_code(client, sundays):
    login(client, "media")
    reg(client)                                                  # Sunday: marks present
    sundays["d"] = WEDNESDAY
    login(client, "admin")
    page = client.get("/admin/").data.decode()
    assert "Latest service" in page and "Sunday 22 November 2026" in page
    assert "Service code for Sunday 29 November" in page
    client.post("/admin/service/toggle")                         # closes the COMING Sunday, not a Wednesday
    assert Service.query.filter_by(service_date=date(2026, 11, 29)).one().registration_open is False
    assert Service.query.filter_by(service_date=WEDNESDAY).count() == 0


def test_admin_dashboard_works_with_no_service_held_yet(client, sundays):
    sundays["d"] = WEDNESDAY
    login(client, "admin")
    r = client.get("/admin/")
    assert r.status_code == 200 and b"No service yet" in r.data
    assert client.get("/admin/export/attendance.csv").status_code == 302   # nothing to export, explained
