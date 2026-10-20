"""
ECHO's reasoning layer: rule-based temporal reasoning.

Takes the classifier's category and the extractor's facts and decides:
  * which date actually matters (and whether it was read or calculated),
  * whether a reminder is useful, and when it should fire,
  * how urgent the memory is today,
  * which facts are missing and must be confirmed by the user.

It never invents a date. If the evidence is incomplete, the memory is marked
"needs confirmation" and no reminder is created until the user fills the gap.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

from utils.date_utils import (add_months, days_between, duration_label, format_long,
                              parse_date, relative_phrase)

# Days before the important date at which ECHO reminds you. Editable from the
# Settings page (stored in the database) - these are the defaults.
REMINDER_RULES = {
    "food": 3,
    "warranty": 30,
    "document": 30,
    "subscription": 7,
    "medicine": 2,
    "receipt": 30,
    "other": 7,
}

CATEGORY_LABELS = {
    "warranty": "Warranty", "food": "Food", "document": "Document", "subscription": "Subscription",
    "receipt": "Receipt", "medicine": "Medicine", "other": "Other",
}

DATE_TYPE_LABELS = {
    "warranty_expiry": "Warranty expiration",
    "expiry": "Expiry date",
    "best_before": "Best-before date",
    "renewal": "Renewal date",
    "estimated_depletion": "Estimated refill date",
    "return_deadline": "Return window closes",
    "purchase": "Purchase date",
    "important": "Important date",
}

# Fields each category needs for a confident result (used for confidence).
KEY_FIELDS = {
    "warranty": ["title", "brand", "purchase_date", "warranty_duration"],
    "food": ["title", "date"],
    "document": ["title", "date", "document_number"],
    "subscription": ["title", "date"],
    "receipt": ["store", "purchase_date", "amount"],
    "medicine": ["title", "quantity", "dosage", "date"],
    "other": ["title", "date"],
}

URGENCY_ORDER = {"OVERDUE": 0, "TODAY": 1, "URGENT": 2, "UPCOMING": 3, "LATER": 4, "NONE": 5}


def _read(found: dict) -> str:
    kw = (found.get("keyword") or "").strip()
    if found.get("type") == "generic_end" or kw.lower() in ("to", "till", "until"):
        return "Read from the text (end of the stated validity period)"
    return f"Read from the text (\"{kw}\")" if kw else "Read from the text"


def _first(dates: list[dict], *types: str) -> Optional[dict]:
    for t in types:
        for d in dates:
            if d["type"] == t:
                return d
    return None


def _latest(dates: list[dict], *types: str) -> Optional[dict]:
    hits = [d for d in dates if d["type"] in types]
    return max(hits, key=lambda d: d["date"]) if hits else None


def decide_important_date(category: str, facts: dict, capture_date: date, overrides: Optional[dict] = None) -> dict:
    """Core reasoning. Returns important date, how it was obtained, and missing fields."""
    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    dates = facts.get("dates", [])
    shown: dict = {}          # human-readable extracted facts
    missing: list[dict] = []  # facts ECHO needs the user to confirm
    result = {"important_date": None, "date_type": None, "method": None, "certainty": 0.0}

    def set_date(d: date, dtype: str, method: str, certainty: float) -> None:
        result.update(important_date=d, date_type=dtype, method=method, certainty=certainty)

    if overrides.get("important_date"):
        d = parse_date(overrides["important_date"])
        if d:
            set_date(d, overrides.get("date_type") or _default_date_type(category), "Confirmed by you", 1.0)

    if category == "warranty":
        purchase = parse_date(overrides.get("purchase_date")) or \
            (_first(dates, "purchase") or {}).get("date")
        months = overrides.get("warranty_months") or facts.get("warranty_months")
        months = int(months) if months else None
        explicit = _latest(dates, "expiry", "generic_end")
        if purchase:
            shown["Purchase date"] = format_long(purchase)
        if months:
            shown["Warranty"] = duration_label(months)
        if result["important_date"] is None:
            if explicit:
                set_date(explicit["date"], "warranty_expiry", _read(explicit), 1.0)
            elif purchase and months:
                set_date(add_months(purchase, months), "warranty_expiry",
                         f"Calculated: purchase date + {duration_label(months)} warranty", 0.9)
        if result["important_date"] is None:
            if months and not purchase:
                missing.append({"key": "purchase_date", "label": "Purchase date", "type": "date",
                                "hint": f"I found a {duration_label(months)} warranty, but I couldn't determine the purchase date."})
            elif purchase and not months:
                missing.append({"key": "warranty_months", "label": "Warranty length (months)", "type": "number",
                                "hint": "I found the purchase date, but not how long the warranty lasts."})
            else:
                missing.append({"key": "important_date", "label": "Warranty expiry date", "type": "date",
                                "hint": "I couldn't find a purchase date or warranty length in this image."})

    elif category == "food":
        mfg = (_first(dates, "manufacture") or {}).get("date")
        if mfg:
            shown["Manufactured / packed"] = format_long(mfg)
        exp = _first(dates, "expiry")
        bb = _first(dates, "best_before")
        shelf = facts.get("shelf_life")
        if result["important_date"] is None:
            if exp:
                set_date(exp["date"], "expiry", _read(exp),
                         1.0 if exp["precision"] == "day" else 0.7)
            elif bb:
                set_date(bb["date"], "best_before", _read(bb),
                         1.0 if bb["precision"] == "day" else 0.7)
            elif mfg and shelf:
                if "months" in shelf:
                    d = add_months(mfg, shelf["months"])
                    label = f"{shelf['months']} months"
                else:
                    d = mfg + timedelta(days=shelf["days"])
                    label = f"{shelf['days']} days"
                set_date(d, "best_before", f"Calculated: manufacture date + {label} shelf life", 0.85)
        qty = facts.get("quantity") or {}
        if qty.get("volume"):
            shown["Net quantity"] = f"{qty['count']:g} {qty['unit']}"
        if exp:
            shown["Expiry (as printed)"] = exp["raw"]
        if bb:
            shown["Best before (as printed)"] = bb["raw"]
        if shelf and not (exp or bb):
            shown["Shelf life"] = f"{shelf.get('months', shelf.get('days'))} {'months' if 'months' in shelf else 'days'}"
        if result["important_date"] is None:
            missing.append({"key": "important_date", "label": "Expiry / best-before date", "type": "date",
                            "hint": "I couldn't find a clearly labelled expiry or best-before date."})

    elif category == "document":
        issue = (_first(dates, "start") or {}).get("date")
        if issue:
            shown["Issued / effective"] = format_long(issue)
        if facts.get("document_number_masked"):
            shown["Document number"] = facts["document_number_masked"]
        found = _latest(dates, "expiry", "renewal", "generic_end")
        if result["important_date"] is None and found:
            dtype = "renewal" if found["type"] == "renewal" else "expiry"
            set_date(found["date"], dtype, _read(found),
                     1.0 if found["precision"] == "day" else 0.75)
        if result["important_date"] is None:
            missing.append({"key": "important_date", "label": "Expiry / renewal date", "type": "date",
                            "hint": "I couldn't find a clearly labelled expiry or renewal date on this document."})

    elif category == "subscription":
        start = (_first(dates, "start") or _first(dates, "purchase") or {}).get("date")
        validity = facts.get("validity")
        if start:
            shown["Start date"] = format_long(start)
        if validity:
            shown["Plan"] = (f"{validity['days']} days" if "days" in validity else duration_label(validity["months"]))
        found = _first(dates, "renewal") or _latest(dates, "expiry", "generic_end")
        if found:
            shown["Renews / expires (as printed)"] = found["raw"]
        if result["important_date"] is None:
            if found:
                set_date(found["date"], "renewal", _read(found), 1.0)
            elif start and validity and not validity.get("inferred_from"):
                d = start + timedelta(days=validity["days"]) if "days" in validity else add_months(start, validity["months"])
                set_date(d, "renewal", "Calculated: start date + plan validity", 0.85)
            elif start and validity:
                d = add_months(start, validity["months"])
                set_date(d, "renewal", f"Calculated: start date + {validity['inferred_from']}", 0.7)
        if result["important_date"] is None:
            missing.append({"key": "important_date", "label": "Renewal / expiry date", "type": "date",
                            "hint": "I couldn't find when this renews or expires."})

    elif category == "receipt":
        purchase = parse_date(overrides.get("purchase_date")) or \
            (_first(dates, "purchase") or _first(dates, "unlabelled") or {}).get("date")
        if purchase:
            shown["Purchase date"] = format_long(purchase)
        if facts.get("amount"):
            shown["Total amount"] = facts["amount"]
        months = overrides.get("warranty_months") or facts.get("warranty_months")
        if months:
            shown["Warranty"] = duration_label(int(months))
        if result["important_date"] is None and purchase:
            if months:
                set_date(add_months(purchase, int(months)), "warranty_expiry",
                         f"Calculated: purchase date + {duration_label(int(months))} warranty", 0.9)
            elif facts.get("return_days"):
                set_date(purchase + timedelta(days=facts["return_days"]), "return_deadline",
                         f"Calculated: purchase date + {facts['return_days']}-day return window", 0.9)
        if result["important_date"] is None and not purchase:
            missing.append({"key": "purchase_date", "label": "Purchase date", "type": "date",
                            "hint": "I couldn't find the purchase date on this receipt."})
        # A receipt with no warranty / return window is saved as a record without a reminder.

    elif category == "medicine":
        qty = facts.get("quantity") or {}
        dosage = facts.get("dosage") or {}
        count = float(overrides.get("quantity") or (qty.get("count") if not qty.get("volume") else 0) or 0)
        per_day = float(overrides.get("dosage_per_day") or dosage.get("per_day") or 0)
        if facts.get("strength"):
            shown["Strength"] = facts["strength"]
        if count:
            shown["Quantity"] = f"{int(count) if count.is_integer() else count} {qty.get('unit', 'tablets')}"
        if per_day:
            shown["Dosage (as printed)"] = dosage.get("raw", f"{per_day:g} per day") if not overrides.get("dosage_per_day") \
                else f"{per_day:g} per day (confirmed by you)"
        exp = _first(dates, "expiry")
        if exp:
            shown["Expiry"] = format_long(exp["date"])
        if count and per_day:
            supply_days = math.floor(count / per_day)
            shown["Estimated supply"] = f"{supply_days} day{'s' if supply_days != 1 else ''}"
            if result["important_date"] is None:
                set_date(capture_date + timedelta(days=supply_days), "estimated_depletion",
                         f"Estimated: {int(count)} ÷ {per_day:g} per day = {supply_days} days from the capture date", 0.8)
        else:
            if not count:
                missing.append({"key": "quantity", "label": "Quantity (number of tablets/capsules)", "type": "number",
                                "hint": "Needed only for an estimated refill reminder."})
            if not per_day:
                missing.append({"key": "dosage_per_day", "label": "Units taken per day (as prescribed)", "type": "number",
                                "hint": "Enter exactly what your prescription says. ECHO never suggests a dose."})
            if result["important_date"] is None and exp:
                set_date(exp["date"], "expiry", _read(exp), 1.0)

    else:  # other
        found = _latest(dates, "expiry", "best_before", "renewal", "generic_end")
        if result["important_date"] is None and found:
            set_date(found["date"], "expiry" if found["type"] in ("expiry", "best_before") else "important",
                     _read(found), 0.9)
        if result["important_date"] is None:
            missing.append({"key": "important_date", "label": "Important date (optional)", "type": "date",
                            "hint": "No clearly labelled date was found. Add one if you want a reminder."})

    for key, label in (("brand", "Brand"), ("seller", "Seller"), ("model", "Model"), ("serial", "Serial number")):
        if facts.get(key) and category in ("warranty", "receipt"):
            shown.setdefault(label, facts[key])
    if category == "receipt" and facts.get("store"):
        shown = {"Store": facts["store"], **shown}
    if category == "subscription" and facts.get("amount"):
        shown.setdefault("Amount", facts["amount"])

    # If the user already confirmed a date, drop the matching "missing" prompts.
    if result["important_date"] is not None and result["method"] == "Confirmed by you":
        missing = [m for m in missing if m["key"] not in ("important_date", "purchase_date", "warranty_months")]
    if category == "medicine" and result["date_type"] == "estimated_depletion":
        missing = []

    result.update(fields=shown, missing=missing)
    return result


def _default_date_type(category: str) -> str:
    return {"warranty": "warranty_expiry", "food": "expiry", "document": "expiry", "subscription": "renewal",
            "receipt": "purchase", "medicine": "estimated_depletion"}.get(category, "important")


def compute_confidence(category: str, classifier_prob: float, facts: dict, decision: dict) -> dict:
    """Confidence from real signals: classifier probability, field coverage, date certainty."""
    present = {
        "title": bool(facts.get("title")), "brand": bool(facts.get("brand")),
        "purchase_date": any(d["type"] == "purchase" or (category == "receipt" and d["type"] == "unlabelled")
                             for d in facts.get("dates", [])),
        "warranty_duration": bool(facts.get("warranty_months")),
        "date": decision.get("important_date") is not None,
        "document_number": bool(facts.get("document_number_masked")),
        "store": bool(facts.get("store")),
        "amount": bool(facts.get("amount")),
        "quantity": bool(facts.get("quantity")), "dosage": bool(facts.get("dosage")),
    }
    keys = KEY_FIELDS.get(category, KEY_FIELDS["other"])
    coverage = sum(1 for k in keys if present.get(k)) / len(keys)
    certainty = decision.get("certainty", 0.0)
    score = 0.5 * classifier_prob + 0.3 * coverage + 0.2 * certainty
    score = round(min(max(score, 0.0), 1.0), 2)
    level = "High" if score >= 0.75 else "Medium" if score >= 0.5 else "Low"
    return {"score": score, "level": level,
            "breakdown": {"classifier": round(classifier_prob, 2), "field_coverage": round(coverage, 2),
                          "date_certainty": round(certainty, 2)}}


def reminder_plan(important_date, category: str, rules: dict, today: Optional[date] = None,
                  days_before: Optional[int] = None) -> Optional[dict]:
    """When should ECHO remind? None if there is no reliable future-facing date."""
    d = parse_date(important_date)
    if d is None:
        return None
    today = today or date.today()
    lead = int(days_before if days_before is not None else rules.get(category, REMINDER_RULES.get(category, 7)))
    reminder = d - timedelta(days=lead)
    note = None
    if reminder < today <= d:
        reminder = today
        note = "The usual reminder window has already started, so the reminder is set for today."
    return {"reminder_date": reminder, "days_before": lead, "note": note}


def urgency(important_date, today: Optional[date] = None, reminder_date=None) -> str:
    """OVERDUE / TODAY / URGENT (<= 7 days) / UPCOMING (<= 30 days or reminder due) / LATER."""
    days = days_between(important_date, today)
    if days is None:
        return "NONE"
    if days < 0:
        return "OVERDUE"
    if days == 0:
        return "TODAY"
    if days <= 7:
        return "URGENT"
    rd = parse_date(reminder_date)
    if days <= 30 or (rd and rd <= (today or date.today())):
        return "UPCOMING"
    return "LATER"


STATUS_WORDS = {
    "warranty": ("Protected", "Expiring soon", "Expired"),
    "food": ("Fresh", "Use soon", "Past date"),
    "document": ("Valid", "Renew soon", "Expired"),
    "subscription": ("Active", "Renews soon", "Lapsed"),
    "medicine": ("Supply estimated", "Refill soon", "Refill due"),
    "receipt": ("Recorded", "Deadline soon", "Deadline passed"),
    "other": ("Saved", "Coming up", "Past date"),
}


def status_label(category: str, level: str) -> str:
    ok, soon, past = STATUS_WORDS.get(category, STATUS_WORDS["other"])
    if level == "NONE":
        return "Saved"
    if level in ("OVERDUE",):
        return past
    if level in ("TODAY", "URGENT"):
        return soon
    return ok


def event_phrase(category: str, date_type: Optional[str], days: Optional[int]) -> str:
    """'reaches its best-before date in 2 days', 'warranty expires in 28 days'."""
    when = relative_phrase(days).lower() if days is not None else ""
    if days is not None and days < 0:
        tail = f"{abs(days)} day{'s' if abs(days) != 1 else ''} ago" if abs(days) < 45 else when
    else:
        tail = "today" if days == 0 else ("tomorrow" if days == 1 else when)
    verbs = {
        "warranty_expiry": ("warranty expires", "warranty expired"),
        "best_before": ("reaches its best-before date", "passed its best-before date"),
        "expiry": ("expires", "expired"),
        "renewal": ("renews", "was due for renewal"),
        "estimated_depletion": ("may run out (estimated refill reminder)", "was estimated to run out"),
        "return_deadline": ("return window closes", "return window closed"),
        "purchase": ("was purchased", "was purchased"),
    }
    future, past = verbs.get(date_type or "", ("is due", "was due"))
    return f"{past} {tail}" if days is not None and days < 0 else f"{future} {tail}"


def why_it_matters(category: str, date_type: Optional[str]) -> str:
    return {
        "warranty_expiry": "Claim repairs or replacements for free before the warranty ends.",
        "best_before": "Use it while it's at its best and avoid waste.",
        "expiry": "Act before it expires." if category != "document"
        else "Renew in time to avoid penalties or last-minute rushes.",
        "renewal": "Decide whether to renew or cancel before you're charged again.",
        "estimated_depletion": "Estimated refill reminder so you can reorder in time. Based only on the printed "
                               "quantity and dosage, not your actual use.",
        "return_deadline": "Return or exchange the item before the window closes.",
        "purchase": "Keep proof of purchase for claims, returns and records.",
    }.get(date_type or "", "Saved for future reference.")


def describe_memory(memory: dict, rules: dict, today: Optional[date] = None) -> dict:
    """Add computed view fields (days remaining, urgency, phrases) to a DB row."""
    today = today or date.today()
    m = dict(memory)
    days = days_between(m.get("important_date"), today)
    level = urgency(m.get("important_date"), today, m.get("reminder_date"))
    m["days_remaining"] = days
    m["urgency"] = level
    m["relative"] = relative_phrase(days) if days is not None else "No date"
    m["status_label"] = status_label(m.get("category", "other"), level)
    m["event_phrase"] = event_phrase(m.get("category"), m.get("date_type"), days)
    m["date_label"] = DATE_TYPE_LABELS.get(m.get("date_type") or "", "Important date")
    m["category_label"] = CATEGORY_LABELS.get(m.get("category"), "Other")
    return m
