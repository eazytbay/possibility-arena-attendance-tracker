import sqlalchemy as sa

from app.models import DEPARTMENTS, Person, db
from tests.conftest import login
from tests.test_edit_person import post
from tests.test_people_filters import enrol


def two_dept_worker(client, **over):
    login(client, "media")
    data = {"category": "worker", "department": ["Media", "Choir"]}
    data.update(over)
    assert enrol(client, **data).status_code == 302
    return Person.query.filter_by(phone="08012345678").one()


def test_worker_can_belong_to_two_departments_in_church_order(client):
    p = two_dept_worker(client)
    assert p.departments == [d for d in DEPARTMENTS if d in ("Media", "Choir")]
    assert p.department == ", ".join(p.departments)


def test_unknown_department_is_rejected_and_nothing_saved(client):
    login(client, "media")
    r = enrol(client, category="worker", department=["Choir", "Nonsense"])
    assert r.status_code == 200 and Person.query.count() == 0


def test_edit_replaces_the_whole_set(client):
    p = two_dept_worker(client)
    login(client, "admin")
    assert post(client, p, category="worker", department=["Ushers"]).status_code == 302
    db.session.refresh(p)
    assert p.departments == ["Ushers"]
    assert post(client, p, category="worker", department=["Choir", "Ushers"]).status_code == 302
    db.session.refresh(p)
    assert set(p.departments) == {"Choir", "Ushers"}


def test_filter_finds_person_under_each_department(client):
    two_dept_worker(client)
    login(client, "admin")
    for d in ("Media", "Choir"):
        assert b"Ada Obi" in client.get(f"/admin/people?department={d}").data
    assert b"Ada Obi" not in client.get("/admin/people?department=Ushers").data


def test_csv_lists_both_departments(client):
    p = two_dept_worker(client)
    login(client, "admin")
    csv_ = client.get("/admin/export/people.csv").data.decode()
    assert p.department in csv_


def test_dashboard_counts_person_in_each_department(client):
    p = two_dept_worker(client)
    login(client, "admin")
    assert b"counted in both" in client.get("/admin/").data


def test_deleting_person_removes_department_rows(app):
    p = Person(full_name="Ada Obi", phone="08012345678", category="worker")
    db.session.add(p)
    db.session.commit()
    p.set_departments(["Choir", "Media"])
    db.session.commit()
    db.session.delete(p)
    db.session.commit()
    assert db.session.execute(sa.text("select count(*) from person_departments")).scalar() == 0


def test_set_departments_ignores_unknown_and_duplicates(app):
    p = Person(full_name="Ada Obi", phone="08012345678", category="worker")
    db.session.add(p)
    p.set_departments(["Choir", "Choir", "Nope"])
    db.session.commit()
    assert p.departments == ["Choir"]
