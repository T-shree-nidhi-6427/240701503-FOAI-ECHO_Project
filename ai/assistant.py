"""
Ask ECHO: a small natural-language query layer over your saved memories.

This is deliberately not a large language model. It is an intent parser
(keyword matching) that turns a question into a structured filter over the
local database, then phrases the answer. It only ever reports what is stored.
"""
from __future__ import annotations

import re
from datetime import date

from .intelligence import CATEGORY_LABELS, URGENCY_ORDER

CATEGORY_WORDS = {
    "warranty": r"warrant|guarant",
    "food": r"\bfood|milk|grocer|snack|eat|fridge|best[- ]before",
    "document": r"document|licen[cs]e|passport|insurance|certificate|registration|\bid\b|policy",
    "subscription": r"subscri|membership|\bplan|streaming|netflix|spotify",
    "receipt": r"receipt|purchase|bill|invoice|bought",
    "medicine": r"medicine|medication|tablet|refill|pill|capsule|prescription",
}
SUGGESTIONS = ["What needs my attention?", "What expires soon?", "What is expiring this month?",
               "Show my warranties", "What do I need to renew?", "Show medicine reminders"]
STOPWORDS = {"what", "when", "show", "does", "about", "have", "with", "that", "this", "from", "your", "mine",
             "the", "and", "for", "are", "my", "me", "is", "any", "do", "i", "need", "to", "list", "all",
             "which", "memories", "memory", "reminders", "reminder", "please", "tell", "find", "where"}


def _card(m: dict) -> dict:
    return {
        "id": m["id"], "title": m["title"], "category": m["category"],
        "category_label": CATEGORY_LABELS.get(m["category"], "Other"),
        "phrase": m.get("event_phrase"), "relative": m.get("relative"),
        "important_date": m.get("important_date"), "urgency": m.get("urgency"),
        "status_label": m.get("status_label"), "is_demo": bool(m.get("is_demo")),
    }


def answer(question: str, memories: list[dict], today: date | None = None) -> dict:
    """``memories`` must already be enriched by ``intelligence.describe_memory``."""
    today = today or date.today()
    q = (question or "").strip().lower()
    if not q:
        return {"ok": False, "intent": "empty", "message": "Type a question, for example “What needs my attention?”",
                "cards": [], "suggestions": SUGGESTIONS}

    if re.search(r"\b(help|what can you do|how do you work|commands)\b", q):
        return {"ok": True, "intent": "help", "cards": [], "suggestions": SUGGESTIONS,
                "message": "I search the memories you've saved. Ask about what's coming up, what has expired, "
                           "or a category such as warranties, food, documents, subscriptions, receipts or medicine."}

    categories = [c for c, rx in CATEGORY_WORDS.items() if re.search(rx, q)]
    if re.search(r"\brenew", q) and not categories:
        categories = ["subscription", "document"]

    time_filter = None
    if re.search(r"overdue|expired|missed|already|past", q):
        time_filter = "overdue"
    elif re.search(r"this month", q):
        time_filter = "this_month"
    elif re.search(r"next month", q):
        time_filter = "next_month"
    elif re.search(r"this week|7 days|seven days", q):
        time_filter = "week"
    elif re.search(r"attention|urgent|priority|important|focus|asap|today", q):
        time_filter = "attention"
    elif re.search(r"soon|upcoming|coming up|next|due|expir|renew|run out|running out", q):
        time_filter = "soon"

    pool = [m for m in memories if not categories or m["category"] in categories]
    dated = [m for m in pool if m.get("days_remaining") is not None]

    if time_filter == "overdue":
        items = [m for m in dated if m["days_remaining"] < 0]
    elif time_filter == "this_month":
        items = [m for m in dated if m["days_remaining"] >= 0
                 and m["important_date"][:7] == today.strftime("%Y-%m")]
    elif time_filter == "next_month":
        nm = date(today.year + (today.month == 12), today.month % 12 + 1, 1).strftime("%Y-%m")
        items = [m for m in dated if m["important_date"][:7] == nm]
    elif time_filter == "week":
        items = [m for m in dated if 0 <= m["days_remaining"] <= 7]
    elif time_filter == "attention":
        items = [m for m in dated if m["urgency"] in ("OVERDUE", "TODAY", "URGENT", "UPCOMING")]
    elif time_filter == "soon":
        items = [m for m in dated if 0 <= m["days_remaining"] <= 30]
    elif categories or re.search(r"\b(all|everything|list|show|how many)\b", q):
        items = pool
    else:
        tokens = [t for t in re.findall(r"[a-z0-9]{3,}", q) if t not in STOPWORDS]
        items = [m for m in memories if tokens and any(t in (m["title"] or "").lower() for t in tokens)]
        if not items:
            return {"ok": True, "intent": "unknown", "cards": [], "suggestions": SUGGESTIONS,
                    "message": "I couldn't match that to anything I remember. Try one of these questions."}
        time_filter = "search"

    items.sort(key=lambda m: (URGENCY_ORDER.get(m["urgency"], 9),
                              m["days_remaining"] if m.get("days_remaining") is not None else 99999))
    n = len(items)
    cat_word = " / ".join(CATEGORY_LABELS[c].lower() for c in categories) if categories else ""
    noun = f"{cat_word} memor{'y' if n == 1 else 'ies'}" if cat_word else ("thing" if n == 1 else "things")

    if n == 0:
        empty = {
            "overdue": "Nothing has passed its date. You're all caught up.",
            "this_month": "Nothing is due this month.",
            "next_month": "Nothing is due next month.",
            "week": "Nothing is due in the next 7 days.",
            "attention": "Nothing needs your attention right now.",
            "soon": "Nothing is coming up in the next 30 days.",
        }.get(time_filter, f"You don't have any {cat_word or 'saved'} memories yet.")
        return {"ok": True, "intent": time_filter or "list", "message": empty, "cards": [], "suggestions": SUGGESTIONS}

    lead = {
        "overdue": f"{n} {noun} {'has' if n == 1 else 'have'} already passed {'its' if n == 1 else 'their'} date.",
        "this_month": f"You have {n} {noun} due this month.",
        "next_month": f"You have {n} {noun} due next month.",
        "week": f"You have {n} {noun} due in the next 7 days.",
        "attention": f"You have {n} {noun} that need{'s' if n == 1 else ''} attention.",
        "soon": f"You have {n} {noun} coming up in the next 30 days.",
        "search": f"I found {n} matching {'memory' if n == 1 else 'memories'}.",
    }.get(time_filter, f"You have {n} {noun}.")
    if categories == ["medicine"]:
        lead += " Refill dates are estimates based on the printed quantity and dosage."
    return {"ok": True, "intent": time_filter or "list", "message": lead,
            "cards": [_card(m) for m in items[:12]], "suggestions": SUGGESTIONS}
