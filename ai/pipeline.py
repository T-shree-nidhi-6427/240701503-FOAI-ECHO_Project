"""
The ECHO pipeline:  text -> CLASSIFY -> EXTRACT -> REASON -> suggested memory.

Used for real OCR text and for demo text alike (the ``source`` field records
which one it was, so the UI never pretends demo text came from an image).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from utils.date_utils import days_between, format_long, relative_phrase, to_iso

from .classifier import classifier
from .extractor import extract
from .intelligence import (CATEGORY_LABELS, DATE_TYPE_LABELS, REMINDER_RULES, compute_confidence,
                           decide_important_date, reminder_plan, urgency, why_it_matters)


def analyze_text(text: str, source: str = "image", capture_date: Optional[date] = None,
                 rules: Optional[dict] = None, overrides: Optional[dict] = None,
                 category_override: Optional[str] = None) -> dict:
    """Run the full pipeline and return a JSON-serialisable suggestion."""
    capture_date = capture_date or date.today()
    rules = rules or REMINDER_RULES
    prediction = classifier.predict(text)
    category = category_override if category_override in CATEGORY_LABELS else prediction["label"]
    facts = extract(text, category)
    decision = decide_important_date(category, facts, capture_date, overrides)

    title = (overrides or {}).get("title") or facts.get("title") or CATEGORY_LABELS[category]
    if category == "warranty" and facts.get("brand") and facts["brand"].lower() not in title.lower():
        title = f"{facts['brand']} {title}"

    classifier_prob = prediction["probabilities"].get(category, prediction["probability"]) \
        if category_override else prediction["probability"]
    confidence = compute_confidence(category, classifier_prob, facts, decision)

    important = decision["important_date"]
    plan = reminder_plan(important, category, rules, today=date.today()) if important else None
    days = days_between(important) if important else None
    if plan and days is not None and days < 0:
        plan = None  # never schedule a reminder for something already in the past

    explanation = [
        f"The local classifier read this as {CATEGORY_LABELS[category].lower()} "
        f"({classifier_prob:.0%} probability)."
        + (" Its top guess was too uncertain, so it was filed under Other." if prediction.get("low_confidence")
           and not category_override else ""),
    ]
    labelled = [d for d in facts["dates"] if d["type"] != "unlabelled"]
    if labelled:
        explanation.append("Dates found: " + "; ".join(
            f"{d['raw']} ({d['type'].replace('_', ' ')})" for d in labelled[:4]) + ".")
    if decision["method"]:
        explanation.append(f"{DATE_TYPE_LABELS.get(decision['date_type'], 'Important date')}: {decision['method']}.")
    if plan:
        explanation.append(f"Reminder rule for {CATEGORY_LABELS[category].lower()}: "
                           f"{plan['days_before']} days before.")
    elif important and days is not None and days < 0:
        explanation.append("This date has already passed, so no reminder was scheduled.")
    elif not important:
        explanation.append("No reliable date was found, so no reminder was created.")

    return {
        "source": source,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "classifier": prediction,
        "title": title,
        "important_date": to_iso(important),
        "important_date_display": format_long(important) if important else None,
        "date_type": decision["date_type"],
        "date_label": DATE_TYPE_LABELS.get(decision["date_type"] or "", "Important date"),
        "date_method": decision["method"],
        "why_it_matters": why_it_matters(category, decision["date_type"]),
        "relative": relative_phrase(days) if days is not None else None,
        "urgency": urgency(important) if important else "NONE",
        "reminder": {
            "reminder_date": to_iso(plan["reminder_date"]),
            "reminder_date_display": format_long(plan["reminder_date"]),
            "days_before": plan["days_before"],
            "note": plan["note"],
        } if plan else None,
        "confidence": confidence["score"],
        "confidence_level": confidence["level"],
        "confidence_breakdown": confidence["breakdown"],
        "extracted_fields": decision["fields"],
        "needs_confirmation": decision["missing"],
        "explanation": explanation,
        "raw_facts": {
            "warranty_months": facts.get("warranty_months"),
            "quantity": facts.get("quantity"),
            "dosage": facts.get("dosage"),
            "dates": [{k: v for k, v in d.items() if k != "date"} for d in facts["dates"]],
        },
        "text": text,
    }
