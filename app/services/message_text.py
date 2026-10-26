"""Greeting wording. Several versions so the message is not identical every time.
{name} is the person's first name and {month} the month. The whole text must fit one 160-character SMS page
for the longest name and month (the tests check this)."""
import zlib
from pathlib import Path

MAX_NAME = 14
FOOTER = " - RCCG Possibility Arena"

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(filename: str) -> list[str]:
    lines = [ln.strip() for ln in (DATA / filename).read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        raise RuntimeError(f"{filename} has no messages")
    return lines


BIRTHDAY = _load("birthday_messages.txt")
NEW_MONTH = _load("new_month_messages.txt")

# (month, day) -> (kind stored in the message log, file of wordings). These replace the plain new-month
# message on the same day, so nobody gets two texts on 1 January or 1 October.
HOLIDAYS = {
    (12, 25): ("christmas", "christmas_messages.txt"),
    (1, 1): ("new_year", "new_year_messages.txt"),
    (10, 1): ("independence", "independence_messages.txt"),
}
HOLIDAY_TEXTS = {kind: _load(fname) for kind, fname in HOLIDAYS.values()}


def short_name(name: str) -> str:
    return name[:MAX_NAME]


def _pick(options: list[str], key: str) -> str:
    return options[zlib.crc32(key.encode()) % len(options)]


def birthday_text(first_name: str, person_id: int, year: int, override: str | None = None) -> str:
    body = override.rstrip() if override else _pick(BIRTHDAY, f"{person_id}-{year}") + FOOTER
    return body.format(name=short_name(first_name), first_name=short_name(first_name))


def new_month_text(first_name: str, month_name: str, year: int, month: int, override: str | None = None) -> str:
    # Same wording for the whole church in a given month; a different wording next month.
    body = override.rstrip() if override else NEW_MONTH[(year * 12 + month) % len(NEW_MONTH)] + FOOTER
    return body.format(name=short_name(first_name), first_name=short_name(first_name), month=month_name)


def holiday_text(kind: str, first_name: str, year: int) -> str:
    options = HOLIDAY_TEXTS[kind]
    body = options[year % len(options)] + FOOTER  # one wording for the whole church, a different one each year
    return body.format(name=short_name(first_name), first_name=short_name(first_name), year=year)
