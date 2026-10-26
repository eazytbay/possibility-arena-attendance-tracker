"""Greeting wording. Several versions so the message is not identical every time.
{name} is the person's first name and {month} the month. The whole text must fit one 160-character SMS page
for the longest name and month (the tests check this)."""
import zlib

MAX_NAME = 14
FOOTER = " - RCCG Possibility Arena"

BIRTHDAY = [
    "Happy birthday, {name}! The Lord who has kept you this far will give you many more years of joy, health and favour.",
    "Happy birthday, {name}! Your church family celebrates you today. May this new age bring you your best testimonies.",
    "Happy birthday, {name}! May God crown this new year with open doors, good health and answered prayers.",
    "Happy birthday, {name}! You are loved and prayed for. May this new age be your most fruitful yet.",
    "Today is your day, {name}! Happy birthday. May God's goodness and mercy follow you all the days of your life.",
    "Happy birthday, {name}! We thank God for your life. May He give you strength, peace and joy this year.",
]

NEW_MONTH = [
    "Happy new month, {name}! This {month} the Lord will open doors no man can shut, and your testimony will be loud.",
    "Happy new month, {name}! May {month} bring answers to your prayers and joy to your home. We love you!",
    "Happy new month, {name}! The Lord who brought you into {month} will lead you through it with favour on every side.",
    "Happy new month, {name}! Our God is faithful. May {month} be your month of peace, progress and divine help.",
    "{name}, happy new month from your church family! May {month} bring you rest, strength and fresh testimonies.",
    "Happy new month, {name}! May God's mercy follow you every day of {month}. Stay blessed and see you on Sunday!",
]


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
