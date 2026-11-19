from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.models import Broadcast, BroadcastRecipient, Person, db
from app.services import broadcast as bc
from app.services.sms import SendResult
from tests.conftest import login

LAGOS = ZoneInfo("Africa/Lagos")
DAY = datetime(2026, 11, 20, 10, 0, tzinfo=LAGOS)
NIGHT = datetime(2026, 11, 20, 22, 0, tzinfo=LAGOS)


class Fake:
    def __init__(self, results=None):
        self.sent, self.results = [], list(results or [])

    def send(self, phone, text):
        self.sent.append((phone, text))
        return self.results.pop(0) if self.results else SendResult(True, message_id=f"m{len(self.sent)}")


def mk(name, phone, cat="member", depts=(), opt=True):
    p = Person(full_name=name, phone=phone, category=cat, sms_opt_in=opt)
    db.session.add(p)
    db.session.flush()
    p.set_departments(list(depts))
    db.session.commit()
    return p


@pytest.fixture()
def people(app):
    mk("Ada Obi", "08011111111", "worker", ["Choir"])
    mk("Mrs Bada", "08022222222", "member")
    mk("Bayo Ojo", "08033333333", "worker", ["Choir", "Media"])
    mk("Tola Out", "08044444444", "member", opt=False)
    mk("Visitor One", "08055555555", "visitor")
    mk("Teen Ayo", None, "teen")
    db.session.add(Person(full_name="Kid", category="child", age_group="3-5")); db.session.commit()


def test_text_checks(app):
    assert bc.check_text("   ")[1]
    assert bc.check_text("Hi \U0001F600")[1]                       # emoji refused
    assert bc.check_text("Hi {oops}")[1]
    assert bc.check_text("Dear {name}, see you at 5pm.")[1] is None
    assert bc.check_text("x" * 470)[1]
    assert bc.check_text("It’s on")[0] == "It's on"           # curly quote cleaned
    assert (bc.pages(160), bc.pages(161), bc.pages(306), bc.pages(307)) == (1, 2, 2, 3)


def test_audiences(app, people):
    names = lambda kind, d=(): sorted(p.full_name for p in bc.audience_people(kind, list(d))[0])
    assert names("all") == ["Ada Obi", "Bayo Ojo", "Mrs Bada"]       # no visitor, no opted-out, no teen without phone, no child
    assert names("workers") == ["Ada Obi", "Bayo Ojo"]
    assert names("members") == ["Mrs Bada"]
    assert names("departments", ["Media"]) == ["Bayo Ojo"]
    assert names("departments", ["Choir", "Media"]) == ["Ada Obi", "Bayo Ojo"]   # once each
    assert bc.audience_people("members", [])[1] == 1                 # opted-out member counted as skipped


def test_send_personalises_and_finishes(app, people):
    b = bc.create_draft("admin", "workers", [], "Dear {name}, Youth Night is Friday 6pm.")
    assert b.status == "draft" and bc.confirm(b.id)
    f = Fake()
    r = bc.process(f, now=DAY)
    assert r["sent"] == 2 and not r["failed"]
    assert sorted(t for _, t in f.sent) == ["Dear Ada, Youth Night is Friday 6pm.", "Dear Bayo, Youth Night is Friday 6pm."]
    assert db.session.get(Broadcast, b.id).status == "done"
    assert bc.process(f, now=DAY)["sent"] == 0 and len(f.sent) == 2  # nothing is ever sent twice


def test_double_confirm_only_queues_once(app, people):
    b = bc.create_draft("admin", "all", [], "Service at 9am.")
    assert bc.confirm(b.id) is True and bc.confirm(b.id) is False


def test_draft_is_never_sent(app, people):
    bc.create_draft("admin", "all", [], "Service at 9am.")
    f = Fake()
    assert bc.process(f, now=DAY)["sent"] == 0 and not f.sent


def test_nothing_goes_out_at_night_then_resumes_in_the_morning(app, people):
    b = bc.create_draft("admin", "members", [], "Meeting Sunday.")
    bc.confirm(b.id)
    f = Fake()
    assert bc.process(f, now=NIGHT)["outside_hours"] and not f.sent
    assert bc.process(f, now=DAY)["sent"] == 1


def test_one_failure_does_not_stop_the_rest_but_fatal_does(app, people):
    b = bc.create_draft("admin", "workers", [], "Hello.")
    bc.confirm(b.id)
    f = Fake([SendResult(False, error="bad number"), SendResult(True, message_id="x")])
    r = bc.process(f, now=DAY)
    assert (r["sent"], r["failed"]) == (1, 1)
    b2 = bc.create_draft("admin", "workers", [], "Again.")
    bc.confirm(b2.id)
    f2 = Fake([SendResult(False, error="no credit", fatal=True)])
    r2 = bc.process(f2, now=DAY, broadcast_id=b2.id)
    assert r2["stopped"] and len(f2.sent) == 1
    assert db.session.get(Broadcast, b2.id).status == "queued"      # the rest wait; not marked done
    assert BroadcastRecipient.query.filter_by(broadcast_id=b2.id, status="pending").count() == 1


def test_person_who_opts_out_after_preview_is_skipped(app, people):
    b = bc.create_draft("admin", "workers", [], "Hello.")
    bc.confirm(b.id)
    Person.query.filter_by(full_name="Ada Obi").one().sms_opt_in = False
    db.session.commit()
    f = Fake()
    assert bc.process(f, now=DAY)["sent"] == 1 and [p for p, _ in f.sent] == ["08033333333"]


def test_cancel_stops_the_rest(app, people):
    b = bc.create_draft("admin", "all", [], "Hello.")
    bc.confirm(b.id)
    bc.cancel(b.id)
    assert bc.process(Fake(), now=DAY)["sent"] == 0
    assert db.session.get(Broadcast, b.id).status == "cancelled"


def test_stale_sending_row_is_failed_not_resent(app, people):
    from datetime import timedelta, timezone
    b = bc.create_draft("admin", "members", [], "Hello.")
    bc.confirm(b.id)
    r = b.recipients[0]
    r.status = "sending"
    db.session.commit()
    BroadcastRecipient.query.update({"updated_at": datetime.now(timezone.utc) - timedelta(hours=1)})
    db.session.commit()
    f = Fake()
    bc.process(f, now=DAY)
    assert not f.sent and BroadcastRecipient.query.one().status == "failed"


def test_too_many_people_refused(app, people):
    app.config["SMS_BROADCAST_MAX"] = 2
    with pytest.raises(ValueError):
        bc.create_draft("admin", "all", [], "Hello.")


# ---- pages ----

def test_pages_need_admin_and_flow_works(client, app, people, monkeypatch):
    assert client.get("/admin/messages").status_code == 302
    login(client, "media")
    assert client.get("/admin/messages").status_code == 403
    login(client, "admin")
    assert client.get("/admin/messages").status_code == 200
    r = client.post("/admin/messages/preview", data={"audience": "workers", "text": "Dear {name}, Friday 6pm."})
    assert r.status_code == 200 and b"Dear Ada, Friday 6pm." in r.data and b"2</b><span>people" in r.data
    b = Broadcast.query.one()
    assert b.status == "draft"
    # SMS is off in tests: confirm must not queue or send anything
    client.post(f"/admin/messages/{b.id}/send", data={"sure": "yes"})
    assert db.session.get(Broadcast, b.id).status == "draft"
    # switch SMS on with a fake provider
    fake = Fake()
    monkeypatch.setattr("app.blueprints.admin.provider_from_config", lambda cfg: fake)
    monkeypatch.setattr("app.services.sms.provider_from_config", lambda cfg: fake)
    monkeypatch.setattr(bc, "in_send_hours", lambda now=None: True)
    assert client.post(f"/admin/messages/{b.id}/send", data={}).status_code == 302   # box not ticked
    assert db.session.get(Broadcast, b.id).status == "draft"
    client.post(f"/admin/messages/{b.id}/send", data={"sure": "yes"})
    client.post(f"/admin/messages/{b.id}/send", data={"sure": "yes"})                # double tap
    assert len(fake.sent) == 2
    assert b"sent" in client.get(f"/admin/messages/{b.id}").data


def test_bad_input_is_explained_not_saved(client, app, people):
    login(client, "admin")
    r = client.post("/admin/messages/preview", data={"audience": "departments", "text": "Hi"})
    assert r.status_code == 400 and b"Tick at least one department" in r.data
    r = client.post("/admin/messages/preview", data={"audience": "all", "text": ""})
    assert r.status_code == 400 and Broadcast.query.count() == 0


def test_test_send_goes_to_one_number_only(client, app, people, monkeypatch):
    login(client, "admin")
    client.post("/admin/messages/preview", data={"audience": "all", "text": "Hello {name}"})
    b = Broadcast.query.one()
    fake = Fake()
    monkeypatch.setattr("app.blueprints.admin.provider_from_config", lambda cfg: fake)
    monkeypatch.setattr(bc, "in_send_hours", lambda now=None: True)
    client.post("/admin/messages/test", data={"id": b.id, "phone": "07033881015"})
    assert [p for p, _ in fake.sent] == ["07033881015"] and db.session.get(Broadcast, b.id).status == "draft"


def test_visitors_audience(app, people):
    assert [p.full_name for p in bc.audience_people("visitors", [])[0]] == ["Visitor One"]


def test_selection_leaves_out_unticked_people(client, app, people, monkeypatch):
    login(client, "admin")
    client.post("/admin/messages/preview", data={"audience": "workers", "text": "Hi {name}"})
    b = Broadcast.query.one()
    ada = Person.query.filter_by(full_name="Ada Obi").one()
    fake = Fake()
    monkeypatch.setattr("app.blueprints.admin.provider_from_config", lambda cfg: fake)
    monkeypatch.setattr("app.services.sms.provider_from_config", lambda cfg: fake)
    monkeypatch.setattr(bc, "in_send_hours", lambda now=None: True)
    # nobody ticked: refused, still a draft
    client.post(f"/admin/messages/{b.id}/send", data={"sure": "yes", "selection": "1"})
    assert db.session.get(Broadcast, b.id).status == "draft" and not fake.sent
    client.post(f"/admin/messages/{b.id}/send", data={"sure": "yes", "selection": "1", "person": [str(ada.id)]})
    assert [t for _, t in fake.sent] == ["Hi Ada"]


def test_people_here_today_can_be_found(app, people):
    from app.models import Attendance, Service
    from app.services.attendance import today_local
    s = Service(service_date=today_local(), name="x", access_code="ABCDE")
    db.session.add(s); db.session.commit()
    ada = Person.query.filter_by(full_name="Ada Obi").one()
    db.session.add(Attendance(person_id=ada.id, service_id=s.id)); db.session.commit()
    assert bc.present_today_ids() == {ada.id}
