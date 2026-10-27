from datetime import date, timedelta

from app.models import Person, Service, db
from app.services.absence import absent_csv, absent_on, missed_in_a_row
from app.services.attendance import mark_present
from tests.conftest import login

FIRST = date(2026, 11, 1)  # a Sunday


def week(n):
    return FIRST + timedelta(days=7 * n)


def make_services(n):
    out = []
    for i in range(n):
        s = Service(service_date=week(i), name=f"s{i}", access_code="ABCDE")
        db.session.add(s)
        out.append(s)
    db.session.commit()
    return out


def person(name, phone, cat="member"):
    p = Person(full_name=name, phone=phone, category=cat)
    db.session.add(p)
    db.session.commit()
    return p


def test_absent_on_lists_regulars_who_missed_that_sunday(app):
    s = make_services(4)
    reg, away, steady = person("Reg Ular", "08011110001"), person("Away One", "08011110002"), person("Stea Dy", "08011110003")
    for sv in s[:3]:
        mark_present(steady, sv)
    mark_present(reg, s[0]); mark_present(away, s[1])
    mark_present(steady, s[3]); mark_present(reg, s[3])
    rows, note = absent_on(week(3))
    assert [r.person.full_name for r in rows] == ["Away One"] and not note
    assert rows[0].last_seen == week(1)


def test_children_visitors_and_never_seen_people_are_not_listed(app):
    s = make_services(3)
    kid = Person(full_name="Kid One", category="child"); vis = person("Vic Visitor", "08011110004", "visitor")
    ghost = person("Never Came", "08011110005")
    db.session.add(kid); db.session.commit()
    mark_present(kid, s[0]); mark_present(vis, s[0])
    rows, _ = absent_on(week(2))
    assert rows == []


def test_midweek_service_is_ignored(app):
    s = make_services(3)
    mid = Service(service_date=week(1) + timedelta(days=3), name="midweek", access_code="ABCDE")
    db.session.add(mid); db.session.commit()
    p = person("Ada Obi", "08011110006")
    mark_present(p, s[0]); mark_present(p, s[1])
    rows, _ = absent_on(week(2))
    assert [r.person.full_name for r in rows] == ["Ada Obi"]  # absent on the 3rd Sunday; midweek day not counted


def test_missed_three_in_a_row(app):
    s = make_services(5)
    a, b = person("Gone Away", "08011110007"), person("Back Again", "08011110008")
    mark_present(a, s[0]); mark_present(a, s[1])
    mark_present(b, s[0]); mark_present(b, s[4])
    rows, note = missed_in_a_row(week(4))
    assert [r.person.full_name for r in rows] == ["Gone Away"] and not note


def test_not_enough_sundays_gives_a_clear_note(app):
    make_services(2)
    rows, note = missed_in_a_row(week(1))
    assert rows == [] and "at least" in note
    rows2, note2 = absent_on(week(5))
    assert "No Sunday service" in note2


def test_page_and_csv_admin_only(client):
    s = make_services(3)
    p = person("Away One", "08011110002"); mark_present(p, s[0])
    login(client, "usher")
    assert client.get("/admin/absent").status_code == 403
    login(client, "admin")
    page = client.get(f"/admin/absent?date={week(2).isoformat()}")
    assert page.status_code == 200 and b"Away One" in page.data
    csv = client.get(f"/admin/export/absent.csv?date={week(2).isoformat()}").data.decode()
    assert "Away One" in csv and "last_seen" in csv
