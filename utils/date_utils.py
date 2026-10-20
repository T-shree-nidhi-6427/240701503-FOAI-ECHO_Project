"""
Date helpers for ECHO.

Finds dates inside noisy OCR text, converts them to ``datetime.date`` objects,
and formats them for display. Day-first ordering (DD/MM/YYYY) is assumed for
numeric dates, as is standard in India, unless the numbers only make sense as
month-first (for example 03/25/2026).
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import Optional

from dateutil.relativedelta import relativedelta

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_RX = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

# Ordered from most specific to least specific. Matched spans are masked so a
# later, looser pattern cannot re-match part of an earlier date.
_PATTERNS = [
    ("ymd", re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")),
    ("d_month_y", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?" + _MONTH_RX + r"\.?,?[\s\-]+(\d{4})\b", re.I)),
    ("month_d_y", re.compile(r"\b" + _MONTH_RX + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),
    ("dmy", re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b")),
    ("month_y", re.compile(r"\b" + _MONTH_RX + r"\.?[\s,/\-]+(\d{4})\b", re.I)),
    ("m_y", re.compile(r"\b(0?[1-9]|1[0-2])[/.\-](\d{4})\b")),
]


def _year(value: str) -> int:
    y = int(value)
    return 2000 + y if y < 100 else y


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        if not (1990 <= y <= 2100):
            return None
        return date(y, m, d)
    except ValueError:
        return None


def last_day_of_month(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def find_dates(text: str) -> list[dict]:
    """Return every date found in ``text``.

    Each item: ``{"date", "raw", "start", "end", "precision"}`` where precision
    is ``"day"`` or ``"month"`` (month-only dates such as "EXP 08/2027" are
    resolved to the last day of that month, because that is how expiry
    labels are normally read).
    """
    if not text:
        return []
    masked = list(text)
    found: list[dict] = []
    for kind, rx in _PATTERNS:
        current = "".join(masked)
        for m in rx.finditer(current):
            g = m.groups()
            parsed, precision = None, "day"
            if kind == "ymd":
                parsed = _safe_date(int(g[0]), int(g[1]), int(g[2]))
            elif kind == "d_month_y":
                parsed = _safe_date(int(g[2]), MONTHS[g[1].lower()[:3]], int(g[0]))
            elif kind == "month_d_y":
                parsed = _safe_date(int(g[2]), MONTHS[g[0].lower()[:3]], int(g[1]))
            elif kind == "dmy":
                a, b, y = int(g[0]), int(g[1]), _year(g[2])
                if b > 12 and a <= 12:  # clearly month-first, e.g. 03/25/2026
                    a, b = b, a
                parsed = _safe_date(y, b, a)
            elif kind == "month_y":
                y, mo = int(g[1]), MONTHS[g[0].lower()[:3]]
                if 1990 <= y <= 2100:
                    parsed, precision = last_day_of_month(y, mo), "month"
            elif kind == "m_y":
                y, mo = int(g[1]), int(g[0])
                if 1990 <= y <= 2100:
                    parsed, precision = last_day_of_month(y, mo), "month"
            if parsed is None:
                continue
            found.append({"date": parsed, "raw": m.group(0), "start": m.start(),
                          "end": m.end(), "precision": precision})
            for i in range(m.start(), m.end()):
                masked[i] = "#"
    found.sort(key=lambda item: item["start"])
    return found


def parse_date(value) -> Optional[date]:
    """Parse a user- or API-supplied date (ISO string, date, or free text)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = str(value).strip()
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        pass
    hits = find_dates(value)
    return hits[0]["date"] if hits else None


def add_months(d: date, months: int) -> date:
    return d + relativedelta(months=months)


def to_iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def format_long(d) -> str:
    """15 March 2028"""
    d = parse_date(d)
    return f"{d.day} {d.strftime('%B %Y')}" if d else "—"


def format_short(d) -> str:
    """15 Mar 2028"""
    d = parse_date(d)
    return f"{d.day} {d.strftime('%b %Y')}" if d else "—"


def days_between(target, today: Optional[date] = None) -> Optional[int]:
    target = parse_date(target)
    if not target:
        return None
    return (target - (today or date.today())).days


def relative_phrase(days: Optional[int]) -> str:
    """Human phrase for a day offset: 'Today', 'In 12 days', '3 months ago'."""
    if days is None:
        return "No date"
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days == -1:
        return "Yesterday"
    span = abs(days)
    if span < 45:
        unit = f"{span} days"
    elif span < 365:
        months = round(span / 30.4)
        unit = f"{months} month{'s' if months != 1 else ''}"
    else:
        years = span / 365.25
        unit = f"{years:.1f} years".replace(".0 ", " ") if years < 10 else f"{round(years)} years"
    return f"In {unit}" if days > 0 else f"{unit} ago"


def duration_label(months: Optional[int]) -> str:
    if not months:
        return "—"
    if months % 12 == 0:
        years = months // 12
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{months} month{'s' if months != 1 else ''}"
