from datetime import date, timedelta

from app.models import Attendance, Person, Service, db
from app.services.attendance import attendance_csv, filter_people, mark_present, visit_count, visitor_status


def sundays(n):
    out = []
    for i in range(n):
        s = Service(service_date=date(2026, 10, 4) + timedelta(days=7 * i), name=f"s{i}", access_code="ABCDE")
        db.session.add(s)
        out.append(s)
    db.session.commit()
    return out


def visitor(name="Vic Visitor", phone="08055555555"):
    p = Person(full_name=name, phone=phone, category="visitor")
    db.session.add(p)
    db.session.commit()
    return p


def test_visitor_becomes_member_on_fourth_sunday_but_history_stays_visitor(app):
    svcs = sundays(5)
    v = visitor()
    for s in svcs[:3]:
        mark_present(v, s)
    assert v.category == "visitor"
    mark_present(v, svcs[3])
    assert v.category == "member"
    assert visitor_status(v, svcs[3]) == "returning visitor"  # that Sunday still counted as a visitor visit
    mark_present(v, svcs[4])
    assert visit_count(v.id) == 4  # the fifth Sunday was as a member


def test_promotion_can_be_switched_off(app):
    app.config["VISITOR_PROMOTE_AFTER"] = 0
    v = visitor()
    for s in sundays(6):
        mark_present(v, s)
    assert v.category == "visitor"


def test_members_are_unaffected(app):
    m = Person(full_name="Mem Ber", phone="08066666666", category="member")
    db.session.add(m)
    db.session.commit()
    for s in sundays(5):
        mark_present(m, s)
    assert m.category == "member" and visit_count(m.id) == 0


def test_filter_visitors_who_came_on_a_given_sunday(app):
    svcs = sundays(3)
    a, b, c = visitor("A One", "08011110001"), visitor("B Two", "08011110002"), visitor("C Three", "08011110003")
    mark_present(a, svcs[0]); mark_present(b, svcs[0]); mark_present(b, svcs[1]); mark_present(c, svcs[2])
    day = svcs[0].service_date.isoformat()
    names = [p.full_name for p in filter_people({"came_on": day, "category": "visitor"}).all()]
    assert names == ["A One", "B Two"]
    names2 = [p.full_name for p in filter_people({"came_on": svcs[1].service_date.isoformat(), "category": "visitor"})]
    assert names2 == ["B Two"]


def test_promoted_person_still_listed_as_visitor_for_that_old_sunday(app):
    svcs = sundays(4)
    v = visitor()
    for s in svcs:
        mark_present(v, s)
    assert v.category == "member"
    old = svcs[0].service_date.isoformat()
    assert [p.full_name for p in filter_people({"came_on": old, "category": "visitor"})] == ["Vic Visitor"]
    assert "visitor" in attendance_csv(svcs[0], {"category": "visitor"})


def test_people_page_and_csv_show_visit_counts(client):
    from tests.conftest import login
    svcs = sundays(2)
    v = visitor()
    mark_present(v, svcs[0]); mark_present(v, svcs[1])
    login(client, "admin")
    page = client.get("/admin/people?category=visitor&came_on=" + svcs[0].service_date.isoformat())
    assert b"2 Sundays as visitor" in page.data
    csv = client.get("/admin/export/people.csv?category=visitor").data.decode()
    assert "sundays_as_visitor" in csv and ",2" in csv
