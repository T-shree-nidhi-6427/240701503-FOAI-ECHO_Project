"""
Information extraction engine.

Turns raw OCR text into structured facts: labelled dates (expiry, best before,
purchase, renewal ...), warranty durations, quantities and dosages, amounts,
names and identifiers. Everything here is deterministic pattern matching over
the text: nothing is guessed. A fact that is not visible in the text is simply
absent from the result, so later stages can ask the user instead.
"""
from __future__ import annotations

import re
from typing import Optional

from utils.date_utils import find_dates

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18,
    "twenty four": 24, "twenty-four": 24, "thirty": 30, "thirty six": 36,
}
_NUM = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|twenty[- ]four|thirty(?: six)?)"

# Keyword families that label a date. Order matters only for readability;
# the keyword closest to the date wins.
DATE_KEYWORDS = {
    "best_before": r"best\s*before|best\s*by|\bbb\b",
    "expiry": (r"\bexp(?:iry|ires|ired|iration)?\b\.?(?:\s*date)?|use\s*by|use\s*before|valid(?:ity)?\s*(?:until|till|til|upto|up\s*to|"
               r"thru|through)|valid\s*till|expires?\s*on|date\s*of\s*expiry|validity\s*nt|subscription\s*end|end\s*date|"
               r"\bends?\s*on|policy\s*period.*?\bto\b"),
    "renewal": r"renew(?:al|s|ed)?(?:\s*(?:date|due|on|before|by))?|next\s*(?:billing|payment|renewal)(?:\s*date)?|due\s*(?:back\s*)?(?:date|on|by)|auto[- ]?renew",
    "purchase": (r"purchase(?:d)?(?:\s*(?:date|on))?|date\s*of\s*purchase|invoice\s*date|inv\.?\s*date|bill\s*date|"
                 r"order\s*date|sold\s*on|date\s*of\s*sale|bought\s*on"),
    "manufacture": r"mfg\.?|mfd\.?|manufactur(?:ed|ing|e)(?:\s*date)?|date\s*of\s*(?:mfg|manufacture)|packed\s*on|pkd\.?|date\s*of\s*packing|packing\s*date",
    "start": (r"start(?:s|ed)?(?:\s*date)?|valid\s*from|effective\s*from|issued?(?:\s*(?:date|on))?|date\s*of\s*issue|"
              r"member\s*since|activated\s*on|registered\s*on|recharge\s*date|subscription\s*start"),
    "from_generic": r"\bfrom\b",
    "generic_end": r"\b(?:to|till|until)\b",
    "plain_date": r"\bdate\b",
}
_KW_COMPILED = {k: re.compile(v, re.I) for k, v in DATE_KEYWORDS.items()}

WARRANTY_TERMS = re.compile(r"warrant|guarant", re.I)
MEDICINE_UNITS = r"tablets?|tabs?|capsules?|caps?|pills?|softgels?"
FREQUENCY = {"once": 1, "one time": 1, "twice": 2, "two times": 2, "thrice": 3, "three times": 3, "four times": 4}

KNOWN_BRANDS = [
    "Samsung", "LG", "Whirlpool", "Sony", "Dell", "HP", "Lenovo", "Asus", "Acer", "Apple", "Bosch", "Panasonic",
    "Philips", "Xiaomi", "Redmi", "OnePlus", "Realme", "Vivo", "Oppo", "Godrej", "Haier", "IFB", "Voltas", "Havells",
    "Prestige", "Bajaj", "Crompton", "Usha", "Butterfly", "Pigeon", "Kent", "Aquaguard", "Daikin", "Blue Star",
    "Hitachi", "Canon", "Epson", "Boat", "JBL", "Bose", "Mi", "Motorola", "Nokia", "Amul", "Aavin", "Nestle",
    "Britannia", "Parle", "Mother Dairy", "Heritage", "Haldirams", "Maggi", "Kelloggs", "Cadbury", "McCain",
    "Nandini", "Tata", "ITC", "Dabur", "Patanjali", "Cipla", "Sun Pharma", "Dr Reddy's", "Himalaya", "Netflix",
    "Spotify", "Amazon Prime", "Disney+ Hotstar", "YouTube Premium", "Microsoft", "Google", "Adobe", "Jio",
    "Airtel", "Vi",
]

LABEL_FIELDS = {
    "product": r"product(?:\s*name)?|item(?:\s*name)?|model\s*name|appliance|description",
    "medicine": r"medicine(?:\s*name)?|drug(?:\s*name)?|tablet\s*name|generic\s*name",
    "service": r"service(?:\s*name)?|plan(?:\s*name)?|subscription(?:\s*name)?|membership",
    "document": r"document(?:\s*name)?|certificate(?:\s*name)?|document\s*type",
    "brand": r"brand|make|manufacturer",
    "seller": r"sold\s*by|seller|store|retailer|dealer|shop|merchant|vendor",
    "store": r"store|shop|merchant|sold\s*by",
}


def _to_number(token: str) -> Optional[float]:
    token = token.strip().lower().replace("-", " ")
    if token in WORD_NUMBERS:
        return float(WORD_NUMBERS[token])
    try:
        return float(token)
    except ValueError:
        return None


def _labelled_value(text: str, label_rx: str) -> Optional[str]:
    """Value after 'Label: value' on the same line, or on the next line if empty."""
    lines = text.splitlines()
    rx = re.compile(r"^\s*(?:" + label_rx + r")\s*[:\-]\s*(.*)$", re.I)
    for i, line in enumerate(lines):
        m = rx.match(line)
        if m:
            value = m.group(1).strip()
            if not value and i + 1 < len(lines):
                value = lines[i + 1].strip()
            value = value.strip(" :-")
            if value and not find_dates(value) and len(value) <= 80:
                return value
    return None


GENERIC_TYPES = ("generic_end", "plain_date", "from_generic")


def _nearest_keyword(window: str) -> tuple[Optional[str], Optional[str]]:
    """Return (date_type, matched_text) for the keyword nearest the END of window.

    Specific keywords (expiry, purchase ...) always beat generic ones
    ("to", "from", "date"), even if the generic word sits closer to the date.
    """
    best = {True: (None, -1, None), False: (None, -1, None)}  # keyed by is_generic
    for dtype, rx in _KW_COMPILED.items():
        generic = dtype in GENERIC_TYPES
        for m in rx.finditer(window):
            if m.end() > best[generic][1]:
                best[generic] = (dtype, m.end(), m.group(0))
    chosen = best[False] if best[False][0] else best[True]
    return chosen[0], chosen[2]


def label_dates(text: str) -> list[dict]:
    """Find every date and attach the keyword that labels it."""
    dates = find_dates(text)
    labelled = []
    for idx, item in enumerate(dates):
        line_start = text.rfind("\n", 0, item["start"]) + 1
        prev_end = max((d["end"] for d in dates[:idx] if d["end"] <= item["start"]), default=0)
        window = text[max(line_start, prev_end):item["start"]]
        dtype, kw = _nearest_keyword(window)
        if dtype is None:
            # "Best Before:\n05 Oct 2026" - the label sits on the previous line
            prev_line_start = text.rfind("\n", 0, max(line_start - 1, 0)) + 1
            prev_line = text[prev_line_start:max(line_start - 1, 0)]
            if prev_line and not find_dates(prev_line):
                dtype, kw = _nearest_keyword(prev_line)
        if dtype == "generic_end":
            line = text[line_start:item["start"]]
            dtype = "expiry" if _KW_COMPILED["start"].search(line) or idx > 0 else None
        if dtype == "from_generic":
            dtype = "start"
        if dtype == "plain_date":
            dtype = "unlabelled"
        labelled.append({
            "date": item["date"], "iso": item["date"].isoformat(), "raw": item["raw"],
            "type": dtype or "unlabelled", "keyword": kw, "precision": item["precision"],
        })
    return labelled


def extract_warranty_months(text: str) -> Optional[int]:
    patterns = [
        _NUM + r"\s*[- ]?\s*(years?|yrs?|months?|mths?)\s*(?:of\s+)?(?:\w+\s+){0,2}?(?:warranty|guarantee)",
        r"(?:warranty|guarantee)(?:\s*(?:period|duration|term))?\s*[:\-]?\s*(?:of\s+|for\s+|valid\s+for\s+|is\s+)?"
        + _NUM + r"\s*[- ]?\s*(years?|yrs?|months?|mths?)",
        r"(?:guaranteed|warranted|valid)\s+for\s+" + _NUM + r"\s*[- ]?\s*(years?|yrs?|months?|mths?)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            n = _to_number(m.group(1))
            if n:
                months = n * 12 if m.group(2).lower().startswith(("y", "yr")) else n
                return int(round(months))
    return None


def extract_shelf_life(text: str) -> Optional[dict]:
    """'Best before 6 months from manufacture' -> {'months': 6}"""
    m = re.search(r"(?:best\s*before|use\s*(?:within|by)|consume\s*within|shelf\s*life)\s*[:\-]?\s*" + _NUM
                  + r"\s*(months?|days?)\s*(?:from|after|of)?\s*(?:the\s+)?(?:date\s+of\s+)?"
                  r"(?:mfg|mfd|manufactur\w*|pack\w*|pkd)?", text, re.I)
    if not m:
        return None
    n = _to_number(m.group(1))
    if not n:
        return None
    unit = m.group(2).lower()
    mentions_origin = re.search(r"mfg|mfd|manufactur|pack|pkd", m.group(0), re.I)
    return {"months": int(n)} if unit.startswith("month") else {"days": int(n), "origin": bool(mentions_origin)}


def extract_validity_period(text: str) -> Optional[dict]:
    """'Validity: 28 days', 'valid for 1 year', '1 year license', 'annual plan'."""
    m = re.search(r"validity\s*(?:period)?\s*[:\-]?\s*" + _NUM + r"\s*(days?|months?|years?)", text, re.I) or \
        re.search(r"valid\s+for\s+" + _NUM + r"\s*(days?|months?|years?)", text, re.I) or \
        re.search(_NUM + r"\s*[- ]?(day|month|year)s?\s+(?:plan|pack|license|licence|subscription|membership)", text, re.I)
    if m:
        n = _to_number(m.group(1))
        unit = m.group(2).lower()
        if n:
            if unit.startswith("day"):
                return {"days": int(n)}
            return {"months": int(n) * (12 if unit.startswith("year") else 1)}
    if re.search(r"\b(annual|yearly)\b", text, re.I):
        return {"months": 12, "inferred_from": "annual plan"}
    if re.search(r"\bquarterly\b", text, re.I):
        return {"months": 3, "inferred_from": "quarterly plan"}
    if re.search(r"\bmonthly\b", text, re.I):
        return {"months": 1, "inferred_from": "monthly plan"}
    return None


def extract_quantity(text: str) -> Optional[dict]:
    m = re.search(r"(\d+)\s*[x×]\s*(\d+)\s*(" + MEDICINE_UNITS + r")\b", text, re.I)
    if m:
        return {"count": int(m.group(1)) * int(m.group(2)), "unit": _unit_name(m.group(3)), "raw": m.group(0)}
    m = re.search(r"(?:qty|quantity|pack\s*of|strip\s*of|contains)\s*[:\-]?\s*(\d+)\b\s*(" + MEDICINE_UNITS + r")?"
                  r"(?!\s*(?:ml|l|g|kg|mg|mcg|litres?|liters?|gm)\b)", text, re.I) \
        or re.search(r"\b(\d+)\s*(" + MEDICINE_UNITS + r")\b(?!\s*(?:/|per|a|each|once|twice|thrice|three|every)\b)", text, re.I)
    if m:
        unit = _unit_name(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else "units"
        return {"count": int(m.group(1)), "unit": unit, "raw": m.group(0).strip()}
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(ml|l|litre|liter|g|kg)\b", text, re.I)
    if m:
        return {"count": float(m.group(1)), "unit": m.group(2).lower(), "raw": m.group(0), "volume": True}
    return None


def _unit_name(token: Optional[str]) -> str:
    token = (token or "").lower()
    if token.startswith("cap"):
        return "capsules"
    if token.startswith(("pill", "soft")):
        return token
    return "tablets"


def extract_dosage(text: str) -> Optional[dict]:
    """Units per day, only when explicitly printed. Returns None if unsure."""
    m = re.search(_NUM + r"\s*(" + MEDICINE_UNITS + r")?\s*(?:/|per|a|each)\s*day", text, re.I)
    if m:
        n = _to_number(m.group(1))
        if n:
            return {"per_day": n, "raw": m.group(0)}
    m = re.search(_NUM + r"\s*(?:" + MEDICINE_UNITS + r"|ml)?\s*(once|one time|twice|two times|thrice|three times|four times)"
                  r"\s*(?:a\s*|per\s*)?(?:daily|day)", text, re.I)
    if m:
        n = _to_number(m.group(1))
        if n:
            return {"per_day": n * FREQUENCY[m.group(2).lower()], "raw": m.group(0)}
    m = re.search(_NUM + r"\s*(?:" + MEDICINE_UNITS + r")\s*every\s*(\d+)\s*(?:hours|hrs|h)\b", text, re.I)
    if m:
        n, hours = _to_number(m.group(1)), int(m.group(2))
        if n and 0 < hours <= 24:
            return {"per_day": n * (24 // hours), "raw": m.group(0)}
    m = re.search(r"\b([0-3](?:\.5)?)\s*-\s*([0-3](?:\.5)?)\s*-\s*([0-3](?:\.5)?)\b", text)
    if m and re.search(r"tab|cap|dose|dosage|take|rx|mg", text, re.I):
        total = sum(float(x) for x in m.groups())
        if total > 0:
            return {"per_day": total, "raw": m.group(0) + " (morning-noon-night)"}
    return None


def extract_strength(text: str) -> Optional[str]:
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|µg|g)\b(?:\s*/\s*\d+\s*ml)?", text, re.I)
    return m.group(0) if m else None


def extract_amount(text: str) -> Optional[str]:
    rx = (r"(?:grand\s*total|net\s*(?:amount|payable)|order\s*total|total\s*(?:amount|payable)?|amount\s*(?:paid)?)"
          r"\s*[:\-]?\s*(?:rs\.?|inr|₹|\$)?\s*([\d,]+(?:\.\d{1,2})?)")
    matches = list(re.finditer(rx, text, re.I))
    if matches:
        return matches[-1].group(1)
    return None


def extract_brand(text: str) -> Optional[str]:
    labelled = _labelled_value(text, LABEL_FIELDS["brand"])
    if labelled:
        return labelled
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z])" + re.escape(brand) + r"(?![A-Za-z])", text, re.I if len(brand) > 3 else 0):
            return brand
    return None


def extract_identifier(text: str, kind: str) -> Optional[str]:
    patterns = {
        "serial": r"(?:serial\s*(?:no|number|#)?|s/n|sn)\s*[:.\-#]?\s*([A-Z0-9][A-Z0-9\-]{3,})",
        "model": r"model\s*(?:no|number|#)?\s*[:.\-#]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
        "document_number": (r"(?:licen[cs]e|policy|certificate|registration|document|passport|card|reg|dl|member(?:ship)?)"
                            r"\s*(?:no|number|num|id|#)\.?\s*[:.\-#]?\s*([A-Z0-9][A-Z0-9\-/ ]{3,}[A-Z0-9])"),
    }
    m = re.search(patterns[kind], text, re.I)
    return m.group(1).strip() if m else None


def mask_identifier(value: Optional[str]) -> Optional[str]:
    """Keep only the last 4 characters of a sensitive number."""
    if not value:
        return None
    compact = re.sub(r"\s", "", value)
    return "•••• " + compact[-4:] if len(compact) > 4 else compact


def guess_title(text: str, category: str, brand: Optional[str]) -> Optional[str]:
    if category == "receipt" and brand:
        for line in text.splitlines():
            if re.search(re.escape(brand), line, re.I) and not find_dates(line) and len(line) <= 60:
                return re.sub(r"\s+\d[\d,.]*$", "", line.strip())
    label_order = {
        "medicine": ["medicine", "product"], "subscription": ["service", "product"],
        "document": ["document"], "receipt": ["product"], "warranty": ["product"],
        "food": ["product"], "other": ["product"],
    }.get(category, ["product"])
    for key in label_order:
        value = _labelled_value(text, LABEL_FIELDS[key])
        if value:
            if brand and brand.lower() not in value.lower() and category == "warranty":
                return f"{brand} {value}"
            return value
    skip = re.compile(r"warranty\s*card|guarantee\s*card|tax\s*invoice|receipt|cash\s*memo|invoice|bill\b|"
                      r"certificate$|rx$|prescription|payment|order\s*summary|thank", re.I)
    for line in text.splitlines():
        stripped = line.strip(" :-")
        letters = re.sub(r"[^A-Za-z]", "", stripped)
        if len(letters) < 3 or len(stripped) > 60:
            continue
        if find_dates(stripped) or skip.search(stripped):
            continue
        if any(rx.search(stripped) for key, rx in _KW_COMPILED.items() if key not in GENERIC_TYPES):
            continue
        if re.match(r"^(?:qty|quantity|dosage|dose|mrp|net|batch|total|amount)\b", stripped, re.I):
            continue
        return stripped
    return None


def extract(text: str, category: str) -> dict:
    """Run every extractor and return a structured dictionary."""
    text = text or ""
    brand = extract_brand(text)
    fields: dict = {"brand": brand}
    dates = label_dates(text)
    fields["dates"] = dates
    fields["warranty_months"] = extract_warranty_months(text) if WARRANTY_TERMS.search(text) else None
    fields["shelf_life"] = extract_shelf_life(text)
    fields["validity"] = extract_validity_period(text)
    fields["quantity"] = extract_quantity(text)
    fields["dosage"] = extract_dosage(text)
    fields["strength"] = extract_strength(text) if category == "medicine" else None
    fields["amount"] = extract_amount(text)
    fields["seller"] = _labelled_value(text, LABEL_FIELDS["seller"])
    fields["serial"] = extract_identifier(text, "serial")
    fields["model"] = extract_identifier(text, "model")
    fields["document_number_masked"] = mask_identifier(extract_identifier(text, "document_number")) \
        if category == "document" else None
    m = re.search(r"return(?:s)?\s*(?:accepted\s*)?(?:within|in)\s*(\d+)\s*days", text, re.I)
    fields["return_days"] = int(m.group(1)) if m else None
    title = guess_title(text, category, brand)
    if category == "medicine" and title and fields["strength"] and fields["strength"] not in title:
        title = title  # keep the printed name as-is
    fields["title"] = title
    first_line = next((ln.strip() for ln in text.splitlines() if re.search(r"[A-Za-z]{3,}", ln)), None)
    fields["store"] = fields["seller"] or (first_line if category == "receipt" else None)
    return fields
