# ECHO – AI-Powered Personal Memory Assistant

> **Capture once. Remember automatically.**

ECHO is a local web app that remembers the small but important things in your life: warranty expiry dates, food best-before dates, subscription renewals, document expiries, receipts and medicine refills.

Take a photo of a warranty card, food label, receipt or renewal notice. ECHO reads the text, works out what kind of item it is, finds the date that matters, and reminds you **before** it's too late.

Everything runs **on your own computer**. It uses no paid APIs, needs no internet connection after installation, and never sends your images anywhere.

---

## Contents

1. [What ECHO is](#1-what-echo-is)
2. [Features](#2-features)
3. [Architecture](#3-architecture)
4. [Folder structure](#4-folder-structure)
5. [Requirements](#5-requirements)
6. [Create a virtual environment](#6-create-a-virtual-environment)
7. [Install the Python packages](#7-install-the-python-packages)
8. [Install Tesseract OCR on Windows](#8-install-tesseract-ocr-on-windows)
9. [Configure the Tesseract path (if needed)](#9-configure-the-tesseract-path-if-needed)
10. [Run the app](#10-run-the-app)
11. [Open it in your browser](#11-open-it-in-your-browser)
12. [Demo mode](#12-demo-mode)
13. [Test real OCR](#13-test-real-ocr)
14. [How the classifier works](#14-how-the-classifier-works)
15. [How the reminder logic works](#15-how-the-reminder-logic-works)
16. [Database structure](#16-database-structure)
17. [Troubleshooting](#17-troubleshooting)
18. [Limitations](#18-limitations)
19. [Future improvements](#19-future-improvements)

---

## 1. What ECHO is

ECHO is a prototype **external memory**. Its job is to answer one question for you:

> *"What do I need to remember, and when?"*

It combines four honest, well-understood techniques:

| Technique | What it does in ECHO |
|---|---|
| **Optical Character Recognition** (Tesseract) | Reads the printed text in your photo |
| **Local ML classifier** (scikit-learn) | Decides whether the text is a warranty, food label, document, subscription, receipt, medicine or other |
| **Intelligent information extraction** (regular expressions + keyword rules) | Finds names, dates, durations, quantities, brands and serial numbers |
| **Rule-based temporal reasoning** | Works out *the* important date and when to remind you |

ECHO **never invents facts**. If a date or quantity is not clearly printed, ECHO asks you to confirm it instead of guessing.

---

## 2. Features

- **Scan by upload, drag-and-drop or camera.** Camera capture uses your browser's `getUserMedia`, so the image never leaves your machine.
- **Demo text input.** Try the whole pipeline without a camera or Tesseract. Results are clearly labelled **DEMO TEXT INPUT**, never "OCR".
- **Seven categories:** warranty, food, document, subscription, receipt, medicine, other.
- **Explainable results.** Each result includes:
  - a confidence score, calculated from real signals
  - the method used to calculate the date (for example "purchase date + 2 years warranty")
  - a "Why ECHO decided this" panel
- **Needs confirmation.** When information is missing, ECHO shows a small form for only the missing fields and then recalculates.
- **Smart reminders.** Each category has its own lead time, and you can change these in Settings.
- **Reminders page.** Sections for Needs attention, Upcoming, Later and Completed, with Done/Undo buttons.
- **Ask ECHO.** Plain-English questions such as "What expires soon?", "Show my warranties" or "What needs my attention?".
- **Memories library.** Search, filter by category, sort, and switch between grid and list views.
- **Memory detail page.** Edit, delete, change the reminder, see the original capture and a timeline.
- **Privacy.** Document numbers are masked (`•••• 1234`), data is stored only in a local SQLite file, and images stay on your computer.
- **Resilient.** If Tesseract is missing the app still runs: image scanning shows *"Tesseract OCR is not installed or configured."* and demo mode keeps working.
- **Premium dark UI.** Responsive layout with a desktop sidebar, a mobile drawer and bottom navigation, toasts, subtle animations, keyboard focus styles and reduced-motion support.
- **Optional in-app and browser notifications** for reminders that are due, shown when you open the app.

### Medicine: an honest note

The medicine feature is an **Estimated refill reminder** only. It uses the tablet count and the daily usage you confirm to estimate when the supply will run out. For example, 10 tablets at 2 per day lasts 5 days. ECHO **never gives medical advice and never suggests or changes a dose.** If the dosage isn't printed, ECHO asks you for it.

---

## 3. Architecture

```
 CAPTURE  ──►  OCR  ──►  CLASSIFY  ──►  EXTRACT  ──►  REASON  ──►  REMEMBER  ──►  REMIND  ──►  ASK
 photo /      Tesseract   TF-IDF +       dates,        important    SQLite         reminder     keyword
 camera /     (pytess-    Logistic       durations,    date +       memories,      date per     intent
 demo text    eract)      Regression     quantities    reminder     reminders      category     parser
```

| Stage | File | Notes |
|---|---|---|
| Capture | `templates/scan.html`, `static/js/scan.js` | Upload, drag-drop, camera, demo text |
| Validate upload | `app.py` → `/api/scan` | png/jpg/jpeg/webp only, max 10 MB, `secure_filename`, random name, Pillow verification |
| OCR | `ai/ocr.py` | Grayscale, orientation fix, upscaling, auto-contrast and sharpening, then Tesseract |
| Classify | `ai/classifier.py`, `ai/trainer.py` | Trains automatically on first run |
| Extract | `ai/extractor.py`, `utils/date_utils.py` | Day-first date parsing (Indian format), labelled dates |
| Reason | `ai/intelligence.py` | `REMINDER_RULES`, per-category decision logic, confidence, urgency |
| Orchestrate | `ai/pipeline.py` | Runs every stage and builds the explanation |
| Store | `database/db.py` | SQLite, parameterised queries only |
| Ask | `ai/assistant.py` | Keyword-based intent parser, no external API |
| Web | `app.py`, `templates/`, `static/` | Flask pages and JSON APIs |

### Routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Overview dashboard |
| GET | `/scan` | Scan page |
| GET | `/memories` | Memory library |
| GET | `/memory/<id>` | Memory detail |
| GET | `/reminders` | Reminders |
| GET | `/ask` | Ask ECHO |
| GET | `/settings` | Settings |
| POST | `/api/scan` | Image upload (multipart `image`) **or** demo text (JSON `{"text": ...}`) |
| POST | `/api/recompute` | Recalculate after the user confirms missing fields |
| POST | `/api/save-memory` | Save a scanned result |
| POST | `/api/reminder` | Change a memory's reminder |
| POST | `/api/reminder/<id>/status` | Mark a reminder done or pending |
| POST | `/api/ask` | Ask ECHO a question |
| PUT | `/api/memory/<id>` | Edit a memory |
| DELETE | `/api/memory/<id>` | Delete a memory, its reminder and its image |
| GET | `/api/health` | Status of the database, OCR and classifier |
| POST | `/api/settings`, `/api/demo/load`, `/api/demo/clear`, `/api/retrain` | Settings actions |

---

## 4. Folder structure

```
ECHO/
├── app.py                     # Flask app: pages, JSON APIs, error handling, startup
├── requirements.txt
├── README.md
├── .gitignore
├── .vscode/launch.json        # "Run ECHO" configuration for VS Code (F5)
├── ai/
│   ├── ocr.py                 # Tesseract OCR + image preprocessing
│   ├── trainer.py             # Trains the classifier (python -m ai.trainer)
│   ├── classifier.py          # Loads / auto-trains the model, predicts categories
│   ├── extractor.py           # Extracts dates, durations, quantities, brands, IDs
│   ├── intelligence.py        # Reminder rules + temporal reasoning + confidence
│   ├── pipeline.py            # Runs the full pipeline for one capture
│   ├── assistant.py           # Ask ECHO intent parser
│   └── demo.py                # The four demo scenarios
├── data/
│   └── training_data.csv      # 378 labelled examples (text,label)
├── models/                    # echo_classifier.joblib is created here automatically
├── database/
│   ├── db.py                  # SQLite schema + queries
│   └── echo.db                # Created automatically on first run
├── utils/
│   └── date_utils.py          # Date finding / parsing / formatting helpers
├── templates/                 # Jinja pages (base, index, scan, memories, ...)
├── static/
│   ├── css/style.css          # Design system
│   ├── js/app.js              # Shared helpers: API, toasts, modal, drawer
│   ├── js/scan.js             # Scan flow
│   ├── js/ask.js              # Ask ECHO chat
│   ├── images/logo.svg
│   └── uploads/               # Your uploaded images (local only)
├── sample_images/             # Two test images for trying real OCR
│   ├── warranty_card.jpg
│   └── milk_label.png
└── logs/echo.log              # Created automatically
```

---

## 5. Requirements

- **Windows 10/11** (it also works on macOS and Linux)
- **Python 3.10 or newer.** Check with `python --version`.
- **Tesseract OCR 5.x.** This is only needed for real image scanning; demo mode works without it.
- A modern browser (Chrome, Edge or Firefox)

---

## 6. Create a virtual environment

Open the `ECHO` folder in VS Code, then open a terminal (**Terminal → New Terminal**):

```powershell
python -m venv .venv
.venv\Scripts\activate
```

Your prompt should now start with `(.venv)`.

> If PowerShell says *"running scripts is disabled on this system"*, run this once and then try `activate` again:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
> You can also use the Command Prompt instead: `.venv\Scripts\activate.bat`

In VS Code, press `Ctrl+Shift+P`, choose **Python: Select Interpreter**, and pick the `.venv` interpreter.

---

## 7. Install the Python packages

```powershell
pip install -r requirements.txt
```

This installs Flask, Pillow, pytesseract, scikit-learn, joblib and python-dateutil.

---

## 8. Install Tesseract OCR on Windows

> ⚠️ **Important:** `pytesseract` is only a Python **wrapper**. It does not contain the OCR engine. You must install the **Tesseract program** separately. `pip install pytesseract` alone is **not** enough.

1. Download the Windows installer from the UB Mannheim build (the version recommended by the Tesseract project): **https://github.com/UB-Mannheim/tesseract/wiki**
   Pick the latest 64-bit `tesseract-ocr-w64-setup-5.x.x.exe`.
2. Run the installer. Keep the default location: `C:\Program Files\Tesseract-OCR\`
   **English** language data is included by default.
3. *(Recommended)* Add Tesseract to your PATH:
   - Start → search **"Edit the system environment variables"** → **Environment Variables…**
   - Under *User variables*, select **Path** → **Edit** → **New** → `C:\Program Files\Tesseract-OCR`
   - Click **OK**, then **close and reopen VS Code** so the terminal picks up the new PATH.
4. Check the installation:
   ```powershell
   tesseract --version
   ```

ECHO also checks `C:\Program Files\Tesseract-OCR\tesseract.exe` automatically. If you used the default location, it will usually work even without the PATH step.

---

## 9. Configure the Tesseract path (if needed)

ECHO looks for Tesseract in this order:

1. The `TESSERACT_CMD` environment variable
2. `tesseract` on your PATH
3. `C:\Program Files\Tesseract-OCR\tesseract.exe` and `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

If you installed Tesseract somewhere else, set `TESSERACT_CMD` before starting the app:

```powershell
# PowerShell (current terminal only)
$env:TESSERACT_CMD = "D:\Tools\Tesseract-OCR\tesseract.exe"
python app.py
```

```cmd
:: Command Prompt
set TESSERACT_CMD=D:\Tools\Tesseract-OCR\tesseract.exe
python app.py
```

To check whether ECHO found Tesseract, open **Settings → System status**, or visit `http://127.0.0.1:5000/api/health`.

---

## 10. Run the app

```powershell
python app.py
```

Alternatively, press **F5** in VS Code and choose **"Run ECHO (python app.py)"**.

On the **first run** ECHO will:

1. Create the SQLite database `database/echo.db`
2. Train the classifier and save it as `models/echo_classifier.joblib` (this takes a few seconds)
3. Check for Tesseract and log the result
4. Add the four **DEMO DATA** memories so the dashboard isn't empty

The terminal output looks similar to this:

```
2026-09-28 10:00:01 INFO    echo.trainer: Classifier trained on 378 samples (5-fold CV accuracy 98.7%)
2026-09-28 10:00:01 INFO    echo: ECHO starting - classifier ready (378 samples, CV accuracy 98.7%)
2026-09-28 10:00:01 INFO    echo: OCR: Tesseract 5.x
2026-09-28 10:00:01 INFO    echo: First run: seeded 4 demo memories
 * Running on http://127.0.0.1:5000
```

Press `Ctrl+C` to stop the server.

---

## 11. Open it in your browser

**http://127.0.0.1:5000**

---

## 12. Demo mode

Demo mode lets you present ECHO without a camera or Tesseract.

**Seeded demo memories.** These are added automatically on first run and are labelled **DEMO DATA**:

| Scenario | Input | ECHO's reasoning | Reminder |
|---|---|---|---|
| Warranty | Samsung Washing Machine, purchased 15 March 2026, 2-year warranty | Expires **15 March 2028** | 30 days before → **14 Feb 2028** |
| Food | Milk, best before 5 Oct 2026 | Best-before **5 Oct 2026** | 3 days before → **2 Oct 2026** |
| Subscription | Streaming subscription, renewal 20 Oct 2026 | Renews **20 Oct 2026** | 7 days before → **13 Oct 2026** |
| Medicine | 10 tablets, 2 tablets/day (usage as written in the sample text) | Estimated to run out in **5 days** from capture | 2 days before the estimated refill date |

> 2028 is a leap year, so 30 days before 15 March 2028 is **14 February 2028**, not 13 February.

**Try the pipeline live:**

1. Go to **Scan → Demo text**.
2. Click one of the chips (Warranty, Food, Subscription, Medicine), or type your own text.
3. Click **Let ECHO understand it**.
4. The result is labelled **DEMO TEXT INPUT**, not OCR.

**Show the "Needs confirmation" flow:**

1. Type this into Demo text:
   ```
   LG Refrigerator
   Warranty: 1 year
   Serial No: RF12345
   ```
2. ECHO finds the 1-year warranty but no purchase date, so it asks for one instead of guessing.
3. Pick a date and click **Recalculate**. The expiry date and the reminder appear.

**Reset the demo:** go to **Settings → Demo data** and use **Load demo data** or **Clear demo data**. Loading never creates duplicates.

---

## 13. Test real OCR

1. Make sure **Settings → System status** shows OCR as available.
2. Go to **Scan → Image**.
3. Drag in `sample_images/warranty_card.jpg`, or use **Choose image**.
4. Click **Let ECHO understand it**.

Expected result:
- Category **Warranty**
- Title **Samsung Washing Machine**
- Warranty expiration **15 March 2028**
- Confidence **High**
- The result is labelled **REAL IMAGE OCR**.

Open **"Show the text ECHO read from the image"** to see the raw OCR output. Then try `sample_images/milk_label.png`, which is a food label with a best-before date of 5 Oct 2026.

**Tips for your own photos:** use good light, keep the text flat and in focus, and fill the frame with the label. Small or curved text (a medicine strip, for example) is hard for any OCR engine.

---

## 14. How the classifier works

ECHO uses a **local ML classifier** built with scikit-learn. It is small, fast and fully explainable.

- **Training data:** `data/training_data.csv` holds 378 labelled examples across 7 categories. You can add your own rows (`text,label`).
- **Features:** two TF-IDF vectorisers are combined:
  - word 1–2 grams (keywords such as *"warranty"*, *"best before"*, *"renewal"*)
  - character 3–5 grams (these survive OCR spelling errors such as *"Warrantv"*)
- **Model:** `LogisticRegression` with balanced class weights. It returns a **probability** for each category.
- **Evaluation:** 5-fold stratified cross-validation. The score is printed on training and shown in Settings.
- **Automatic retraining:** the model is retrained when the `.joblib` file is missing, when `training_data.csv` is newer than the model, or when your scikit-learn version differs.
- **Manual retraining:** `python -m ai.trainer`, or use **Settings → Retrain classifier**.
- **Low confidence:** if the top probability is below 40%, or there is too little readable text, the item is filed as **other** instead of being forced into a category. You can always change the category yourself.

> **Honest note on accuracy:** the cross-validation score (about 98%) is measured on the bundled examples, which were written to be clean and typical. Real-world photos with messy OCR text will score lower. Treat the number as "the model learned the training data well", not as a guarantee.

### How confidence is calculated

Confidence is **not** a made-up number. It combines three measured signals:

```
confidence = 0.5 × classifier probability
           + 0.3 × share of the key fields found for that category
           + 0.2 × date certainty (explicit printed date > calculated date > missing)
```

The levels are **High** (75% or more), **Medium** (50% or more) and **Low** (below 50%). The breakdown appears under the confidence bar.

---

## 15. How the reminder logic works

All the rules live in **`ai/intelligence.py`**:

```python
REMINDER_RULES = {
    "food": 3,           # days before best-before / expiry
    "warranty": 30,      # days before warranty expiration
    "document": 30,      # days before document expiry
    "subscription": 7,   # days before renewal
    "medicine": 2,       # days before the estimated refill date
    "receipt": 30,       # days before warranty / return deadline
    "other": 7,
}
```

You can override these values in **Settings → Reminder rules**. The overrides are stored in the database.

**How ECHO chooses the important date, by category:**

| Category | Logic |
|---|---|
| Warranty | Uses the printed expiry date if there is one; otherwise **purchase date + warranty duration**; otherwise asks for the missing piece |
| Food | Uses the expiry or best-before date; otherwise manufacture date + "best before N months" |
| Document | Uses the expiry, "valid until" or renewal date; the document number is masked |
| Subscription | Uses the renewal or next billing date; otherwise start date + validity period |
| Receipt | Records the purchase date, plus a warranty or return deadline if one is stated |
| Medicine | **floor(tablet count ÷ tablets per day)** days from the capture date gives the *estimated* refill date. It asks for the count or daily usage if they're missing, and falls back to the printed expiry date |
| Other | Any clearly labelled date (for example "due back on …") |

**Reminder date** = important date − lead days.

- If that date has already passed but the important date hasn't, the reminder moves to today and a note explains why.
- If the important date itself is in the past, **no reminder is created**. The memory shows as Expired or Overdue.

**Urgency labels:**
- **Overdue:** the date has passed
- **Today**
- **Urgent:** 7 days or less
- **Upcoming:** 30 days or less, or the reminder date has been reached
- **Later**
- **No date**

---

## 16. Database structure

SQLite file: `database/echo.db`. It is created automatically, and delete it to start fresh.

**`memories`**

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT | e.g. "Samsung Washing Machine" |
| category | TEXT | warranty / food / document / subscription / receipt / medicine / other |
| description | TEXT | Short note (editable) |
| image_path | TEXT | Local upload, or NULL for demo text |
| extracted_text | TEXT | OCR or demo text |
| extracted_fields | TEXT (JSON) | Brand, purchase date, quantity, masked number, … |
| important_date | TEXT | ISO `YYYY-MM-DD`, or NULL |
| date_type | TEXT | warranty_expiry, best_before, renewal, estimated_depletion, … |
| date_method | TEXT | How the date was obtained |
| confidence | REAL | 0–1 |
| source | TEXT | `image` or `demo_text` |
| is_demo | INTEGER | 1 for DEMO DATA |
| explanation | TEXT (JSON) | "Why ECHO decided this" lines |
| created_at, updated_at | TEXT | |
| status | TEXT | `active` |

**`reminders`**

| Column | Notes |
|---|---|
| id | |
| memory_id | References memories.id; deleting a memory deletes its reminder |
| reminder_date | ISO date |
| days_before | Lead time used |
| message | Reminder text |
| status | `pending` or `done` |
| created_at | |

**`scan_history`**

| Column | Notes |
|---|---|
| id | |
| filename | Stored upload name (demo text has none) |
| scan_type | `image` or `demo_text` |
| ocr_text | Text that was read |
| category | Predicted category |
| confidence | |
| created_at | |

**`settings`**

| Column | Notes |
|---|---|
| key | |
| value | JSON: profile name, notifications, accent, reminder rules |

To inspect the database, use the free **DB Browser for SQLite** or the VS Code extension **SQLite Viewer**.

---

## 17. Troubleshooting

| Problem | Fix |
|---|---|
| **"Tesseract OCR is not installed or configured."** | Install Tesseract (section 8). Restart VS Code after changing PATH, or set `TESSERACT_CMD` (section 9). Check **Settings → System status**. Demo text still works in the meantime. |
| `TesseractNotFoundError` in older scripts | Same as above: pytesseract is only a wrapper and needs `tesseract.exe`. |
| "ECHO couldn't read any text in this image." | Retake the photo with better light, closer, flatter and in focus. |
| `'python' is not recognized` | Install Python from python.org and tick **"Add python.exe to PATH"**, or use `py -m venv .venv`. |
| PowerShell blocks `activate` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `ModuleNotFoundError: No module named 'flask'` | The virtual environment isn't active. Run `.venv\Scripts\activate`, then `pip install -r requirements.txt`. |
| "Address already in use" / port 5000 busy | Another app is using port 5000. Close it, or change `port=5000` at the bottom of `app.py`. |
| Classifier errors after upgrading scikit-learn | Delete `models/echo_classifier.joblib`. It retrains automatically. |
| Start completely fresh | Stop the app, delete `database/echo.db`, then run `python app.py` again. The demo data is re-seeded. |
| Camera doesn't open | Allow camera access in the browser. The camera only works on `http://127.0.0.1` / `localhost` or over HTTPS. |
| File rejected | Only PNG, JPG, JPEG and WEBP files up to 10 MB are accepted. |
| Something else | Check `logs/echo.log`. The app shows friendly messages and writes the details to the log. |

---

## 18. Limitations

- OCR quality depends on the photo. Curved, glossy, handwritten or very small print is often misread.
- The classifier learned from 378 short, clean examples. Unusual layouts or other languages may be misclassified, which is why you can always change the category.
- Dates are parsed **day-first** (Indian/European style): `05/10/2026` means 5 October. US-style dates can be misread.
- Ask ECHO understands keywords and common phrasings. It is not a conversational AI.
- Reminders only appear **inside the app**, as in-app toasts and optional browser notifications when you open it. There are no email or SMS alerts.
- Medicine refill dates are **estimates** based on the numbers you confirm. They are not medical advice.
- This is a single-user local prototype with no login or encryption at rest. Don't use it for highly sensitive documents.

---

## 19. Future improvements

- Background reminder scheduler with email or desktop notifications
- Multilingual OCR (Tamil, Hindi) using Tesseract language packs
- Learning from user corrections: add confirmed scans back into the training data
- Barcode and QR reading for product and expiry data
- Export and import (CSV/ICS) and calendar integration
- Optional encryption of the local database
- Installable PWA for phones, with an on-device camera flow
- Multi-user accounts with authentication

---

**Privacy:** your uploaded memories are stored locally in this prototype. ECHO does not send images or text to any external service.
