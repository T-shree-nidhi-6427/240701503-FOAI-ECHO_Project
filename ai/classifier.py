"""
Local ML classifier: decides what kind of item the OCR text describes.

The trained model is loaded from ``models/echo_classifier.joblib``. If it is
missing, older than the training data, or was saved by a different
scikit-learn version, it is retrained automatically (a few seconds).
"""
from __future__ import annotations

import logging
import re
import threading

import joblib
import sklearn

from .trainer import DATA_PATH, MODEL_PATH, train

log = logging.getLogger("echo.classifier")

# Below this probability ECHO does not trust its own label and files the item
# under "other" (the extracted dates are still kept).
MIN_CONFIDENCE = 0.40


class EchoClassifier:
    def __init__(self) -> None:
        self._pipeline = None
        self.meta: dict = {}
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def load_or_train(self, force: bool = False) -> dict:
        with self._lock:
            needs_training = force or not MODEL_PATH.exists()
            if not needs_training and DATA_PATH.exists() and DATA_PATH.stat().st_mtime > MODEL_PATH.stat().st_mtime:
                needs_training = True  # training data was edited
            if not needs_training:
                try:
                    bundle = joblib.load(MODEL_PATH)
                    if bundle.get("meta", {}).get("sklearn_version") != sklearn.__version__:
                        needs_training = True
                    else:
                        self._pipeline, self.meta = bundle["pipeline"], bundle["meta"]
                except Exception as exc:
                    log.warning("Saved model could not be loaded (%s); retraining.", exc.__class__.__name__)
                    needs_training = True
            if needs_training:
                self.meta = train()
                self._pipeline = joblib.load(MODEL_PATH)["pipeline"]
            return self.meta

    def predict(self, text: str) -> dict:
        """Return ``{"label", "probability", "probabilities", "low_confidence"}``."""
        if not self.ready:
            self.load_or_train()
        words = re.findall(r"[A-Za-z]{2,}", text or "")
        if len(words) < 2:
            return {"label": "other", "probability": 0.0, "probabilities": {}, "low_confidence": True,
                    "reason": "Not enough readable text to classify."}
        try:
            probs = self._pipeline.predict_proba([text])[0]
        except Exception as exc:
            log.error("Classification failed: %s", exc.__class__.__name__)
            return {"label": "other", "probability": 0.0, "probabilities": {}, "low_confidence": True,
                    "reason": "Classifier error."}
        ranked = sorted(zip(self._pipeline.classes_, probs), key=lambda kv: kv[1], reverse=True)
        top_label, top_prob = ranked[0]
        result = {
            "label": str(top_label),
            "probability": round(float(top_prob), 3),
            "probabilities": {str(label): round(float(p), 3) for label, p in ranked},
            "low_confidence": bool(top_prob < MIN_CONFIDENCE),
        }
        if result["low_confidence"]:
            result["predicted_label"] = str(top_label)
            result["label"] = "other"
        return result


classifier = EchoClassifier()
