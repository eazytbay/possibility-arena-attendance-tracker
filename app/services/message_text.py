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


# Titles people are recorded with. A name that starts with one is greeted by title and surname ("Mrs Bada"),
# not by the title alone ("Mrs"). Keys are lower case without a trailing dot; values are how the title is written.
TITLES = {
    "mr": "Mr", "mrs": "Mrs", "miss": "Miss", "ms": "Ms", "mummy": "Mummy", "daddy": "Daddy", "mama": "Mama",
    "papa": "Papa", "madam": "Madam", "sir": "Sir", "elder": "Elder", "pastor": "Pastor", "pst": "Pastor",
    "deacon": "Deacon", "dcn": "Deacon", "deaconess": "Deaconess", "dcns": "Deaconess", "evang": "Evangelist",
    "evangelist": "Evangelist", "minister": "Minister", "rev": "Rev", "reverend": "Reverend", "bishop": "Bishop",
    "apostle": "Apostle", "prophet": "Prophet", "prophetess": "Prophetess", "a/p": "A/P", "dr": "Dr",
    "engr": "Engr", "prof": "Prof", "chief": "Chief", "hon": "Hon", "barr": "Barr", "sis": "Sister",
    "sister": "Sister", "bro": "Brother", "brother": "Brother", "alhaji": "Alhaji", "alhaja": "Alhaja",
    "oba": "Oba",
}


def _is_initials(word: str) -> bool:
    letters = word.replace(".", "")
    return len(letters) < 2 or (word.isupper() and "." in word)


def greeting_name(full_name: str) -> str:
    """The name used in a greeting: the first name, or title plus surname when the name starts with a title.

    "Tosin Ojuloge" -> "Tosin"; "Mrs Bada" -> "Mrs Bada"; "Mrs A.O. Shorun" -> "Mrs Shorun";
    "Mr Sunday Alaja" -> "Mr Alaja". If title plus surname is longer than MAX_NAME the surname alone is used,
    so a text never starts with a chopped-off word. A name that is only a title becomes "friend".
    """
    words = full_name.split()
    if not words:
        return "friend"
    title = TITLES.get(words[0].lower().rstrip("."))
    if title is None:
        return words[0].capitalize()
    rest = words[1:]
    if not rest:
        return "friend"
    names = [w for w in rest if not _is_initials(w)] or rest
    surname = names[-1].strip(".").title()
    if len(title) + 1 + len(surname) <= MAX_NAME:
        return f"{title} {surname}"
    return surname


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
