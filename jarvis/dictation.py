"""Turn what speech recognition heard into what should actually be typed.

    "fourteen twenty six"                              -> "1426"
    "s u d a r s a n"                                  -> "sudarsan"
    "sudarshan shiva 1426 at the rate gmail dot com"   -> "sudarshanshiva1426@gmail.com"
"""

from __future__ import annotations

import re

UNITS = {"zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "million": 1000000}
REPEATS = {"double": 2, "triple": 3}
NUMBER_WORDS = set(UNITS) | set(TENS) | set(SCALES) | set(REPEATS) | {"and"}


def _group_to_digits(words: list[str]) -> str:
    """One run of number words -> digits. With 'hundred'/'thousand' it's arithmetic ("two hundred and five"
    -> 205); otherwise it's read like a phone number or year ("fourteen twenty six" -> 1426,
    "one one four" -> 114, "double seven" -> 77)."""
    words = [w for w in words if w != "and"] or words
    if any(w in SCALES for w in words):
        total, current = 0, 0
        for w in words:
            if w in UNITS:
                current += UNITS[w]
            elif w in TENS:
                current += TENS[w]
            elif w in SCALES:
                scale = SCALES[w]
                if scale == 100:
                    current = max(current, 1) * 100
                else:
                    total += max(current, 1) * scale
                    current = 0
        return str(total + current)
    out, i, repeat = "", 0, 1
    while i < len(words):
        w = words[i]
        if w in REPEATS:
            repeat = REPEATS[w]
        elif w in TENS:
            value = TENS[w]
            if i + 1 < len(words) and words[i + 1] in UNITS and 0 < UNITS[words[i + 1]] < 10:
                value += UNITS[words[i + 1]]
                i += 1
            out += str(value) * repeat
            repeat = 1
        elif w in UNITS:
            out += str(UNITS[w]) * repeat
            repeat = 1
        i += 1
    return out


def words_to_digits(text: str) -> str:
    """Replace every run of number words with digits, leaving other words alone."""
    tokens = re.split(r"(\s+)", text)
    out, run = [], []

    def flush():
        if not run:
            return
        words = [t for t in run if t.strip()]
        # "o"/"oh"/"and" alone aren't numbers ("oh no", "salt and pepper")
        if all(w.lower() in ("o", "oh", "and", "double", "triple") for w in words):
            out.extend(run)
        else:
            digits = _group_to_digits([w.lower() for w in words])
            trailing = run[-1] if not run[-1].strip() else ""
            out.append(digits + trailing)
        run.clear()

    for token in tokens:
        if not token.strip():
            (run if run else out).append(token)
            continue
        word = token.lower().strip(",.")
        # "and" only belongs to a number after hundred/thousand ("two hundred and five")
        joins = word != "and" or any(t.strip().lower() in SCALES for t in run)
        if word in NUMBER_WORDS and joins:
            run.append(token.strip(",."))
        else:
            flush()
            out.append(token)
    flush()
    return "".join(out)


def join_spelled_letters(text: str) -> str:
    """'s u d a r s a n' -> 'sudarsan' (three or more single letters/digits in a row)."""
    return re.sub(r"\b(?:[A-Za-z0-9]\s+){2,}[A-Za-z0-9]\b", lambda m: m.group(0).replace(" ", ""), text)


EMAIL_HINT = re.compile(r"(@|\bat the rate(?: of)?\b|\bat\b(?=.*\b(?:dot|\.)\s*\w+\s*$))", re.I)


def looks_like_email(text: str) -> bool:
    return bool(re.search(r"(@|\bat the rate\b|\bat\b)", text, re.I)) and bool(
        re.search(r"(\bdot\s*\w+|\.\w{2,})\s*$", text, re.I)) and len(text.split()) <= 12


def spoken_email(text: str) -> str:
    """'sudarshan shiva fourteen twenty six at the rate gmail dot com' -> 'sudarshanshiva1426@gmail.com'."""
    text = words_to_digits(text.strip().rstrip("."))
    text = re.sub(r"\s*\bat the rate(?: of)?\b\s*", "@", text, flags=re.I)
    text = re.sub(r"\s+\bat\b\s+", "@", text, flags=re.I)
    text = re.sub(r"\s*\bdot\b\s*", ".", text, flags=re.I)
    text = re.sub(r"\s*\bunderscore\b\s*", "_", text, flags=re.I)
    text = re.sub(r"\s*\b(?:dash|hyphen)\b\s*", "-", text, flags=re.I)
    return text.replace(" ", "").lower()


def spoken_phone(text: str) -> str:
    digits = words_to_digits(text)
    return re.sub(r"[^\d+]", "", digits)


def prepare(text: str) -> str:
    """What to type for dictated text."""
    text = text.strip()
    if looks_like_email(text):
        return spoken_email(join_spelled_letters(text))
    return join_spelled_letters(words_to_digits(text))

