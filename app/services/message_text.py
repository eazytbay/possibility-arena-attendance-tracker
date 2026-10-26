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
