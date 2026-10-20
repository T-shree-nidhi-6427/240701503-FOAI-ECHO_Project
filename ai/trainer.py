"""
Trains ECHO's local text classifier.

Model: TF-IDF features (word 1-2 grams + character 3-5 grams, which cope well
with OCR spelling noise) feeding a multinomial Logistic Regression.
Training uses the bundled ``data/training_data.csv`` and takes a few seconds
on a normal laptop CPU. No GPU and no external API are needed.

Run manually with:  python -m ai.trainer
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import FeatureUnion, Pipeline

log = logging.getLogger("echo.trainer")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "training_data.csv"
MODEL_PATH = BASE_DIR / "models" / "echo_classifier.joblib"
LABELS = ["warranty", "food", "document", "subscription", "receipt", "medicine", "other"]


def load_dataset(path: Path = DATA_PATH) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            text, label = (row.get("text") or "").strip(), (row.get("label") or "").strip().lower()
            if text and label in LABELS:
                texts.append(text)
                labels.append(label)
    if not texts:
        raise ValueError(f"No usable rows in {path}")
    return texts, labels


def build_pipeline() -> Pipeline:
    features = FeatureUnion([
        ("words", TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1, sublinear_tf=True,
                                  token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]+\b")),
        ("chars", TfidfVectorizer(lowercase=True, analyzer="char_wb", ngram_range=(3, 5), min_df=2,
                                  sublinear_tf=True)),
    ])
    return Pipeline([
        ("features", features),
        ("clf", LogisticRegression(max_iter=3000, C=8.0, class_weight="balanced")),
    ])


def train(data_path: Path = DATA_PATH, model_path: Path = MODEL_PATH) -> dict:
    """Train, cross-validate, save to ``model_path`` and return the metadata."""
    texts, labels = load_dataset(data_path)
    pipeline = build_pipeline()

    # 5-fold cross-validation gives an honest accuracy estimate on unseen text.
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
    cv_scores = cross_val_score(build_pipeline(), texts, labels, cv=folds, scoring="accuracy")

    pipeline.fit(texts, labels)
    meta = {
        "classes": list(pipeline.classes_),
        "n_samples": len(texts),
        "cv_accuracy": round(float(cv_scores.mean()), 4),
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "model": "TF-IDF (word 1-2 grams + char 3-5 grams) + Logistic Regression",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipeline, "meta": meta}, model_path)
    log.info("Classifier trained on %d samples (5-fold CV accuracy %.1f%%)",
             meta["n_samples"], meta["cv_accuracy"] * 100)
    return meta


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    info = train()
    print(f"Trained on {info['n_samples']} samples - 5-fold CV accuracy {info['cv_accuracy']:.1%}")
    print(f"Saved to {MODEL_PATH}")
