from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import MessageLog, Person, db
from app.services.greetings import run_greetings
from app.services.sms import SendResult, to_international

LAGOS = ZoneInfo("Africa/Lagos")


class FakeProvider:
    def __init__(self, results=None):
        self.sent = []
        self.results = list(results or [])

    def send(self, phone, text):
        self.sent.append((phone, text))
        return self.results.pop(0) if self.results else SendResult(True, message_id=f"m{len(self.sent)}")


def mk(name, phone, cat="member", month=None, day=None, opt=True):
    p = Person(full_name=name, phone=phone, category=cat, birth_month=month, birth_day=day, sms_opt_in=opt)
    db.session.add(p)
    db.session.commit()
    return p


def at(y, m, d, h=9):
    return datetime(y, m, d, h, 0, tzinfo=LAGOS)


def test_phone_conversion():
    assert to_international("08012345678") == "2348012345678"


def test_birthday_only_for_matching_day_and_never_children(app):
    mk("ada obi", "08011111111", month=11, day=5)
    mk("tom kid", "08022222222", cat="child", month=11, day=5)
    mk("no phone", None, cat="teen", month=11, day=5)
    mk("opted out", "08033333333", month=11, day=5, opt=False)
    mk("other day", "08044444444", month=11, day=6)
    prov = FakeProvider()
    r = run_greetings(prov, now=at(2026, 11, 5))
    assert r.sent == 1 and prov.sent[0][0] == "08011111111"
    assert "Ada" in prov.sent[0][1]


def test_new_month_on_first_only(app):
    mk("ada obi", "08011111111")
    assert run_greetings(FakeProvider(), now=at(2026, 11, 2)).sent == 0
    prov = FakeProvider()
    assert run_greetings(prov, now=at(2026, 11, 1)).sent == 1
    assert "November" in prov.sent[0][1]


def test_both_messages_when_birthday_on_the_first(app):
    mk("ada obi", "08011111111", month=12, day=1)
    assert run_greetings(FakeProvider(), now=at(2026, 12, 1)).sent == 2


def test_no_double_send_when_run_twice(app):
    mk("ada obi", "08011111111", month=11, day=5)
    prov = FakeProvider()
    run_greetings(prov, now=at(2026, 11, 5))
    r = run_greetings(prov, now=at(2026, 11, 5, 15))
    assert r.sent == 0 and r.skipped_done == 1 and len(prov.sent) == 1


def test_failed_is_retried_up_to_three_times(app):
    mk("ada obi", "08011111111", month=11, day=5)
    prov = FakeProvider([SendResult(False, error="x")] * 5)
    for h in (9, 10, 11, 12, 13):
        run_greetings(prov, now=at(2026, 11, 5, h))
    assert len(prov.sent) == 3
    assert MessageLog.query.one().status == "failed"


def test_fatal_error_stops_run(app):
    mk("a one", "08011111111", month=11, day=5)
    mk("b two", "08022222222", month=11, day=5)
    prov = FakeProvider([SendResult(False, code="BSNG-3001", error="no funds", fatal=True)])
    r = run_greetings(prov, now=at(2026, 11, 5))
    assert r.stopped_early and len(prov.sent) == 1


def test_outside_send_hours_sends_nothing(app):
    mk("ada obi", "08011111111", month=11, day=5)
    prov = FakeProvider()
    assert run_greetings(prov, now=at(2026, 11, 5, 21)).outside_hours
    assert not prov.sent


def test_dry_run_sends_and_logs_nothing(app):
    mk("ada obi", "08011111111", month=11, day=5)
    r = run_greetings(None, now=at(2026, 11, 5), dry_run=True)
    assert len(r.dry_lines) == 1 and MessageLog.query.count() == 0


def test_leap_day_greeted_on_28_feb_in_common_year(app):
    mk("leap one", "08011111111", month=2, day=29)
    assert run_greetings(FakeProvider(), now=at(2027, 2, 28)).sent == 1


def test_messages_fit_one_sms_page(app):
    mk("Maximilian Oluwaseun", "08011111111", month=9, day=1)
    prov = FakeProvider()
    run_greetings(prov, now=at(2026, 9, 1))
    assert all(len(t) <= 160 for _, t in prov.sent), [len(t) for _, t in prov.sent]


def test_every_wording_fits_one_page_with_longest_name():
    import calendar
    from app.services.message_text import BIRTHDAY, NEW_MONTH, FOOTER, MAX_NAME, birthday_text, new_month_text
    name = "W" * 40  # gets shortened to MAX_NAME
    longest_month = max(calendar.month_name[1:], key=len)
    for i in range(len(BIRTHDAY)):
        assert len(birthday_text(name, i, 2026)) <= 160
    for m in range(1, 13):
        for y in (2026, 2027, 2028):
            assert len(new_month_text(name, calendar.month_name[m], y, m)) <= 160
    assert all(len((t + FOOTER).format(name="W" * MAX_NAME, month=longest_month)) <= 160 for t in BIRTHDAY + NEW_MONTH)


def test_new_month_wording_changes_between_months_but_is_same_within_a_month(app):
    from app.services.message_text import new_month_text
    a = new_month_text("Ada", "November", 2026, 11)
    assert a == new_month_text("Bola", "November", 2026, 11).replace("Bola", "Ada")
    assert a.split("{")[0] != new_month_text("Ada", "December", 2026, 12)


def test_no_opt_out_text_and_names_are_personal(app):
    mk("Ada Obi", "08011111111", month=11, day=5)
    mk("Bola Ade", "08022222222", month=11, day=5)
    prov = FakeProvider()
    run_greetings(prov, now=at(2026, 11, 5))
    assert "opt out" not in " ".join(t for _, t in prov.sent).lower()
    assert any("Ada" in t for _, t in prov.sent) and any("Bola" in t for _, t in prov.sent)
