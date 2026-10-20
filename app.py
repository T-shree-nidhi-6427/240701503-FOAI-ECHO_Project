"""
ECHO - AI-Powered Personal Memory Assistant
"Capture once. Remember automatically."

Run:  python app.py   then open http://127.0.0.1:5000
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.utils import secure_filename

from ai.assistant import SUGGESTIONS, answer
from ai.classifier import classifier
from ai.demo import DEMO_SCENARIOS
from ai.intelligence import (CATEGORY_LABELS, DATE_TYPE_LABELS, REMINDER_RULES, URGENCY_ORDER,
                             describe_memory, event_phrase, reminder_plan)
from ai.ocr import extract_text, ocr_status
from ai.pipeline import analyze_text
from database import db
from utils.date_utils import days_between, format_long, format_short, parse_date, relative_phrase

# ------------------------------------------------------------------ config
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
LOG_DIR = BASE_DIR / "logs"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_UPLOAD_MB = 10
TOKEN_RX = re.compile(r"^[a-f0-9]{32}\.(png|jpg|jpeg|webp)$")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(),
                              RotatingFileHandler(LOG_DIR / "echo.log", maxBytes=1_000_000, backupCount=2,
                                                  encoding="utf-8")])
log = logging.getLogger("echo")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.json.sort_keys = False  # keep extracted fields in reading order

DEFAULT_SETTINGS = {
    "profile_name": "",
    "notif_inapp": True,
    "notif_browser": False,
    "accent": "violet",
    "reduce_motion": False,
    "reminder_rules": dict(REMINDER_RULES),
}


# ---------------------------------------------------------------- helpers
def get_settings() -> dict:
    s = {k: db.get_setting(k, v) for k, v in DEFAULT_SETTINGS.items()}
    rules = dict(REMINDER_RULES)
    rules.update({k: int(v) for k, v in (s.get("reminder_rules") or {}).items() if k in REMINDER_RULES})
    s["reminder_rules"] = rules
    return s


def get_rules() -> dict:
    return get_settings()["reminder_rules"]


def described_memories(**filters) -> list[dict]:
    rules = get_rules()
    return [describe_memory(m, rules) for m in db.list_memories(**filters)]


def api_error(message: str, status: int = 400, code: str = "bad_request"):
    return jsonify({"ok": False, "error": message, "code": code}), status


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def reminder_message(title: str, category: str, date_type: str, important_iso: str) -> str:
    what = DATE_TYPE_LABELS.get(date_type or "", "Important date").lower()
    return f"{title}: {what} on {format_long(important_iso)}"


def schedule_reminder(memory_id: int, title: str, category: str, date_type: str, important_iso,
                      days_before=None) -> dict | None:
    """Create/replace the reminder for a memory. No reliable future date -> no reminder."""
    d = parse_date(important_iso)
    if d is None or d < date.today():
        db.delete_reminders_for(memory_id)
        return None
    plan = reminder_plan(d, category, get_rules(), days_before=days_before)
    db.upsert_reminder(memory_id, plan["reminder_date"].isoformat(), plan["days_before"],
                       reminder_message(title, category, date_type, d.isoformat()))
    return plan


def seed_demo_data() -> int:
    """Create the four DEMO DATA memories through the real pipeline (no duplicates)."""
    if db.count_demo_memories() > 0:
        return 0
    created = 0
    for scenario in DEMO_SCENARIOS.values():
        result = analyze_text(scenario["text"], source="demo_text", rules=get_rules())
        mid = db.create_memory({
            "title": result["title"], "category": result["category"],
            "description": "Demo data - created from sample text, not from a photo.",
            "extracted_text": result["text"], "extracted_fields": result["extracted_fields"],
            "important_date": result["important_date"], "date_type": result["date_type"],
            "date_method": result["date_method"], "confidence": result["confidence"],
            "source": "demo_text", "is_demo": True, "explanation": result["explanation"],
        })
        schedule_reminder(mid, result["title"], result["category"], result["date_type"], result["important_date"])
        created += 1
    db.set_setting("demo_seeded", True)
    return created


# ------------------------------------------------------------- templating
@app.template_filter("long_date")
def _long_date(value):
    return format_long(value)


@app.template_filter("short_date")
def _short_date(value):
    return format_short(value)


@app.template_filter("relative")
def _relative(value):
    return relative_phrase(days_between(value))


@app.context_processor
def inject_globals():
    return {
        "settings": get_settings(),
        "category_labels": CATEGORY_LABELS,
        "today_iso": date.today().isoformat(),
        "active_page": request.endpoint,
    }


# -------------------------------------------------------------------- pages
@app.route("/")
def index():
    memories = described_memories()
    attention = sorted([m for m in memories if m["urgency"] in ("OVERDUE", "TODAY", "URGENT", "UPCOMING")],
                       key=lambda m: (URGENCY_ORDER[m["urgency"]], m["days_remaining"]))
    stats = {
        "memories": len(memories),
        "upcoming": sum(1 for m in memories if m["urgency"] == "UPCOMING"),
        "attention": sum(1 for m in memories if m["urgency"] in ("OVERDUE", "TODAY", "URGENT")),
    }
    return render_template("index.html", memories=memories[:6], attention=attention[:4], stats=stats,
                           suggestions=SUGGESTIONS[:3])


@app.route("/scan")
def scan():
    return render_template("scan.html", ocr=ocr_status(), demos=DEMO_SCENARIOS, rules=get_rules(),
                           max_mb=MAX_UPLOAD_MB)


@app.route("/memories")
def memories_page():
    return render_template("memories.html", memories=described_memories())


@app.route("/memory/<int:memory_id>")
def memory_detail(memory_id: int):
    memory = db.get_memory(memory_id)
    if not memory:
        abort(404)
    return render_template("memory_detail.html", memory=describe_memory(memory, get_rules()),
                           date_type_labels=DATE_TYPE_LABELS)


@app.route("/reminders")
def reminders_page():
    items = [m for m in described_memories() if m.get("reminder_id")]
    for m in items:
        m["reminder_phrase"] = f"{m['title']} {event_phrase(m['category'], m['date_type'], m['days_remaining'])}."
    groups = {
        "attention": [m for m in items if m["reminder_status"] != "done" and m["urgency"] in ("OVERDUE", "TODAY", "URGENT")],
        "upcoming": [m for m in items if m["reminder_status"] != "done" and m["urgency"] == "UPCOMING"],
        "later": [m for m in items if m["reminder_status"] != "done" and m["urgency"] == "LATER"],
        "completed": [m for m in items if m["reminder_status"] == "done"],
    }
    for key in groups:
        groups[key].sort(key=lambda m: m["days_remaining"] if m["days_remaining"] is not None else 99999)
    return render_template("reminders.html", groups=groups)


@app.route("/ask")
def ask_page():
    return render_template("ask.html", suggestions=SUGGESTIONS)


@app.route("/settings")
def settings_page():
    return render_template("settings.html", demo_count=db.count_demo_memories(), classifier_meta=classifier.meta,
                           ocr=ocr_status(), scans=db.recent_scans(5))


# ---------------------------------------------------------------------- API
@app.post("/api/scan")
def api_scan():
    """Accepts either an image upload (multipart 'image') or demo text (JSON {'text'})."""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            return api_error("Paste or choose some sample text first.")
        if len(text) > 5000:
            return api_error("That text is too long for a demo (max 5,000 characters).")
        result = analyze_text(text, source="demo_text", rules=get_rules())
        db.add_scan_history(None, "demo_text", text, result["category"], result["confidence"])
        return jsonify({"ok": True, "result": result, "image_token": None})

    file = request.files.get("image")
    if file is None or not file.filename:
        return api_error("Please choose an image to scan.", code="missing_image")
    original = secure_filename(file.filename) or "capture.jpg"
    if not allowed_file(original):
        return api_error("Unsupported file type. Please upload a PNG, JPG, JPEG or WEBP image.", code="invalid_file")
    ext = original.rsplit(".", 1)[1].lower()
    token = f"{uuid.uuid4().hex}.{ext}"
    path = UPLOAD_DIR / token
    file.save(path)
    try:  # confirm it really is an image; never trust the extension alone
        with Image.open(path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        path.unlink(missing_ok=True)
        return api_error("This file isn't a readable image.", code="invalid_file")

    ocr = extract_text(path)
    if not ocr["ok"]:
        if ocr.get("code") != "ocr_unavailable":
            log.warning("OCR returned no usable text (%s)", ocr.get("code"))
        path.unlink(missing_ok=True)
        return jsonify({"ok": False, "error": ocr["error"], "code": ocr.get("code"), "demo_available": True}), 422
    result = analyze_text(ocr["text"], source="image", rules=get_rules())
    db.add_scan_history(original, "image", ocr["text"], result["category"], result["confidence"])
    return jsonify({"ok": True, "result": result, "image_token": token})


@app.post("/api/recompute")
def api_recompute():
    """Re-run reasoning after the user confirms missing fields or changes the category."""
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return api_error("Nothing to recalculate.")
    overrides = payload.get("overrides") or {}
    clean = {}
    for key in ("purchase_date", "important_date"):
        if overrides.get(key):
            d = parse_date(overrides[key])
            if not d:
                return api_error("Please enter a valid date.", code="invalid_date")
            clean[key] = d.isoformat()
    for key in ("warranty_months", "quantity", "dosage_per_day"):
        if overrides.get(key) not in (None, ""):
            try:
                value = float(overrides[key])
                if value <= 0 or value > 10000:
                    raise ValueError
                clean[key] = value
            except (TypeError, ValueError):
                return api_error("Please enter a positive number.", code="invalid_number")
    if overrides.get("title"):
        clean["title"] = str(overrides["title"])[:120]
    category = payload.get("category") if payload.get("category") in CATEGORY_LABELS else None
    result = analyze_text(text, source=payload.get("source", "image"), rules=get_rules(),
                          overrides=clean, category_override=category)
    return jsonify({"ok": True, "result": result})


@app.post("/api/save-memory")
def api_save_memory():
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()[:120]
    category = payload.get("category")
    if not title:
        return api_error("Please give this memory a title.")
    if category not in CATEGORY_LABELS:
        return api_error("Unknown category.")
    important = payload.get("important_date")
    if important:
        d = parse_date(important)
        if not d:
            return api_error("The important date isn't valid.", code="invalid_date")
        important = d.isoformat()
    image_path = None
    token = payload.get("image_token")
    if token:
        if not TOKEN_RX.match(token) or not (UPLOAD_DIR / token).exists():
            return api_error("The uploaded image could not be found. Please scan it again.")
        image_path = f"uploads/{token}"
    days_before = payload.get("days_before")
    if days_before not in (None, ""):
        try:
            days_before = int(days_before)
            if not 0 <= days_before <= 365:
                raise ValueError
        except (TypeError, ValueError):
            return api_error("Reminder lead time must be between 0 and 365 days.")
    else:
        days_before = None
    fields = payload.get("extracted_fields") if isinstance(payload.get("extracted_fields"), dict) else {}
    source = "demo_text" if payload.get("source") == "demo_text" else "image"
    try:
        memory_id = db.create_memory({
            "title": title, "category": category,
            "description": (payload.get("description") or "").strip()[:500]
            or ("Created from demo text input." if source == "demo_text" else None),
            "image_path": image_path, "extracted_text": (payload.get("text") or "")[:5000],
            "extracted_fields": {str(k)[:60]: str(v)[:200] for k, v in fields.items()},
            "important_date": important, "date_type": payload.get("date_type") if important else None,
            "date_method": (payload.get("date_method") or "")[:200] or None,
            "confidence": float(payload.get("confidence") or 0), "source": source, "is_demo": False,
            "explanation": [str(x)[:300] for x in (payload.get("explanation") or [])][:8],
        })
        plan = schedule_reminder(memory_id, title, category, payload.get("date_type"), important, days_before)
    except Exception as exc:
        log.error("Saving memory failed: %s", exc.__class__.__name__)
        return api_error("ECHO couldn't save this memory. Please try again.", 500, "db_error")
    return jsonify({"ok": True, "memory_id": memory_id, "reminder_created": bool(plan),
                    "url": url_for("memory_detail", memory_id=memory_id)})


@app.post("/api/discard")
def api_discard():
    """Remove an uploaded image the user decided not to keep."""
    token = (request.get_json(silent=True) or {}).get("image_token") or ""
    if TOKEN_RX.match(token):
        (UPLOAD_DIR / token).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.put("/api/memory/<int:memory_id>")
def api_update_memory(memory_id: int):
    memory = db.get_memory(memory_id)
    if not memory:
        return api_error("That memory no longer exists.", 404, "not_found")
    payload = request.get_json(silent=True) or {}
    updates = {}
    if "title" in payload:
        title = (payload.get("title") or "").strip()[:120]
        if not title:
            return api_error("Title can't be empty.")
        updates["title"] = title
    if "category" in payload:
        if payload["category"] not in CATEGORY_LABELS:
            return api_error("Unknown category.")
        updates["category"] = payload["category"]
    if "description" in payload:
        updates["description"] = (payload.get("description") or "").strip()[:500]
    if "important_date" in payload:
        if payload["important_date"]:
            d = parse_date(payload["important_date"])
            if not d:
                return api_error("Please enter a valid date.", code="invalid_date")
            updates["important_date"] = d.isoformat()
            updates["date_method"] = "Edited by you"
            if not memory.get("date_type"):
                updates["date_type"] = "important"
        else:
            updates["important_date"] = None
    db.update_memory(memory_id, updates)
    fresh = db.get_memory(memory_id)
    schedule_reminder(memory_id, fresh["title"], fresh["category"], fresh["date_type"], fresh["important_date"],
                      fresh.get("days_before"))
    return jsonify({"ok": True})


@app.delete("/api/memory/<int:memory_id>")
def api_delete_memory(memory_id: int):
    image = db.delete_memory(memory_id)
    if image is None:
        return api_error("That memory no longer exists.", 404, "not_found")
    if image and image.startswith("uploads/") and TOKEN_RX.match(image.split("/", 1)[1]):
        (UPLOAD_DIR / image.split("/", 1)[1]).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.post("/api/reminder")
def api_reminder():
    payload = request.get_json(silent=True) or {}
    try:
        memory_id = int(payload.get("memory_id"))
        days_before = int(payload.get("days_before"))
        if not 0 <= days_before <= 365:
            raise ValueError
    except (TypeError, ValueError):
        return api_error("Choose a reminder between 0 and 365 days before.")
    memory = db.get_memory(memory_id)
    if not memory:
        return api_error("That memory no longer exists.", 404, "not_found")
    if not memory.get("important_date"):
        return api_error("Add an important date first, then set a reminder.")
    if parse_date(memory["important_date"]) < date.today():
        return api_error("This date has already passed, so a reminder can't be scheduled.")
    plan = schedule_reminder(memory_id, memory["title"], memory["category"], memory["date_type"],
                             memory["important_date"], days_before)
    return jsonify({"ok": True, "reminder_date": plan["reminder_date"].isoformat(),
                    "reminder_date_display": format_long(plan["reminder_date"]), "note": plan["note"]})


@app.post("/api/reminder/<int:reminder_id>/status")
def api_reminder_status(reminder_id: int):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("done", "pending"):
        return api_error("Unknown status.")
    if not db.set_reminder_status(reminder_id, status):
        return api_error("Reminder not found.", 404, "not_found")
    return jsonify({"ok": True})


@app.get("/api/reminders/due")
def api_due_reminders():
    today = date.today()
    items = []
    for r in db.due_reminders(today.isoformat()):
        days = days_between(r["important_date"], today)
        items.append({"id": r["id"], "memory_id": r["memory_id"], "title": r["title"],
                      "phrase": f"{r['title']} {event_phrase(r['category'], r['date_type'], days)}."})
    return jsonify({"ok": True, "due": items})


@app.post("/api/ask")
def api_ask():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()[:300]
    if not question:
        return api_error("Type a question for ECHO first.", code="empty_query")
    return jsonify(answer(question, described_memories()))


@app.get("/api/health")
def api_health():
    status = ocr_status(refresh=True)
    return jsonify({"status": "ok", "database": db.db_ok(), "ocr": status["available"],
                    "ocr_version": status["version"], "ocr_message": status["message"],
                    "classifier": classifier.ready, "classifier_info": classifier.meta})


@app.post("/api/settings")
def api_settings():
    payload = request.get_json(silent=True) or {}
    if "profile_name" in payload:
        db.set_setting("profile_name", str(payload["profile_name"]).strip()[:40])
    for key in ("notif_inapp", "notif_browser", "reduce_motion"):
        if key in payload:
            db.set_setting(key, bool(payload[key]))
    if payload.get("accent") in ("violet", "teal"):
        db.set_setting("accent", payload["accent"])
    if isinstance(payload.get("reminder_rules"), dict):
        rules = {}
        for cat, val in payload["reminder_rules"].items():
            if cat in REMINDER_RULES:
                try:
                    v = int(val)
                except (TypeError, ValueError):
                    return api_error(f"Reminder days for {cat} must be a whole number.")
                if not 0 <= v <= 365:
                    return api_error("Reminder days must be between 0 and 365.")
                rules[cat] = v
        db.set_setting("reminder_rules", rules)
    return jsonify({"ok": True, "settings": get_settings()})


@app.post("/api/demo/load")
def api_demo_load():
    created = seed_demo_data()
    if not created:
        return jsonify({"ok": True, "created": 0, "message": "Demo data is already loaded."})
    return jsonify({"ok": True, "created": created, "message": f"Loaded {created} demo memories."})


@app.post("/api/demo/clear")
def api_demo_clear():
    removed = db.delete_demo_memories()
    return jsonify({"ok": True, "removed": removed, "message": f"Removed {removed} demo memories."})


@app.post("/api/retrain")
def api_retrain():
    try:
        meta = classifier.load_or_train(force=True)
    except Exception as exc:
        log.error("Retraining failed: %s", exc.__class__.__name__)
        return api_error("Retraining failed. Check data/training_data.csv.", 500, "train_error")
    return jsonify({"ok": True, "meta": meta})


# ----------------------------------------------------------- error handling
def _wants_json() -> bool:
    return request.path.startswith("/api/")


@app.errorhandler(RequestEntityTooLarge)
def too_large(_err):
    msg = f"That image is larger than {MAX_UPLOAD_MB} MB. Please choose a smaller one."
    return (api_error(msg, 413, "too_large") if _wants_json()
            else (render_template("error.html", code=413, message=msg), 413))


@app.errorhandler(HTTPException)
def http_error(err: HTTPException):
    messages = {404: "We couldn't find that page or memory.", 405: "That action isn't allowed here."}
    msg = messages.get(err.code, "Something went wrong with that request.")
    if _wants_json():
        return api_error(msg, err.code, "http_error")
    return render_template("error.html", code=err.code, message=msg), err.code


@app.errorhandler(Exception)
def unhandled(err: Exception):
    log.exception("Unhandled error on %s", request.path)
    msg = "Something unexpected happened. Your data is safe - please try again."
    if _wants_json():
        return api_error(msg, 500, "server_error")
    return render_template("error.html", code=500, message=msg), 500


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="images/logo.svg"))


# ----------------------------------------------------------------- startup
def bootstrap() -> None:
    is_new = db.init_db()
    meta = classifier.load_or_train()
    log.info("ECHO starting - classifier ready (%d samples, CV accuracy %.1f%%)",
             meta.get("n_samples", 0), meta.get("cv_accuracy", 0) * 100)
    status = ocr_status(refresh=True)
    log.info("OCR: %s", f"Tesseract {status['version']}" if status["available"] else status["message"])
    if is_new and not db.get_setting("demo_seeded", False):
        log.info("First run: seeded %d demo memories", seed_demo_data())


bootstrap()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
