import re


def normalize_phone(raw: str | None) -> str | None:
    """Return a Nigerian mobile number as 11 digits (0XXXXXXXXXX), or None if invalid."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00234") and len(digits) == 15:
        digits = "0" + digits[5:]
    elif digits.startswith("234") and len(digits) == 13:
        digits = "0" + digits[3:]
    elif len(digits) == 10 and digits[0] in "789":
        digits = "0" + digits
    return digits if re.fullmatch(r"0[789]\d{9}", digits) else None
