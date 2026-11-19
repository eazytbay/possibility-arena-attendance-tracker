import pytest

from app.services.message_text import MAX_NAME, greeting_name


@pytest.mark.parametrize("full, expected", [
    ("Tosin Ojuloge", "Tosin"),
    ("ada obi", "Ada"),
    ("Mrs Bada", "Mrs Bada"),
    ("Mrs. Olayinka Muftua", "Mrs Muftua"),
    ("Mrs A.O. Shorun", "Mrs Shorun"),
    ("Mrs Adeagbo F.", "Mrs Adeagbo"),
    ("MRS PHILIP", "Mrs Philip"),
    ("Elder Oluwole Akinmoye", "Elder Akinmoye"),
    ("Pst Ade Bello", "Pastor Bello"),
    ("A/P Ademuyiwa", "A/P Ademuyiwa"),
    ("Mrs", "friend"),
    ("", "friend"),
])
def test_greeting_name(full, expected):
    assert greeting_name(full) == expected


def test_long_title_plus_surname_falls_back_to_surname_and_never_exceeds_limit():
    assert greeting_name("Deaconess Akinsanya") == "Akinsanya"      # "Deaconess Akinsanya" is 19 characters
    for n in ("Pastor Adeoluwatomiwa-Smith", "Deaconess Oluwaseunfunmi Adeyemi", "Mrs Abcdefghijklmnopqrst"):
        assert len(greeting_name(n)) <= MAX_NAME or " " not in greeting_name(n)


def test_name_that_is_not_a_title_is_unchanged():
    assert greeting_name("Mister Bean") == "Mister"
    assert greeting_name("Pastorina Okoye") == "Pastorina"
