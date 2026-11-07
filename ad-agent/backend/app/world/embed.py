"""Text embeddings on CPU.

Primary: fastembed (ONNX runtime, no PyTorch) with all-MiniLM-L6-v2, 384 dims. The model
(~90 MB) downloads on first use and is cached under models/fastembed.
Fallback: hashed word n-grams + a fixed random projection to 384 dims. Lexical only, but
deterministic and offline, so the app still runs on a machine that never saw the internet."""
from __future__ import annotations

import logging
import os

import numpy as np

from app.config import MODELS

log = logging.getLogger(__name__)
DIM = 384


class Embedder:
    def __init__(self, want: str | None = None) -> None:
        self.kind = "hash"
        self._model = None
        want = want or os.getenv("EMBEDDER", "auto")
        if want != "hash":
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    "sentence-transformers/all-MiniLM-L6-v2", cache_dir=str(MODELS / "fastembed")
                )
                self.kind = "minilm"
            except Exception as e:  # no network on first run, missing wheel, ...
                log.warning("fastembed unavailable (%s); using hashed fallback embeddings", type(e).__name__)
        if self._model is None:
            from sklearn.feature_extraction.text import HashingVectorizer

            self._hv = HashingVectorizer(n_features=2**16, ngram_range=(1, 2), alternate_sign=False, norm="l2")
            rng = np.random.default_rng(1234)
            self._proj = rng.standard_normal((2**16, DIM)).astype(np.float32) / np.sqrt(DIM)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), np.float32)
        if self._model is not None:
            out = np.array(list(self._model.embed(texts, batch_size=64)), dtype=np.float32)
        else:
            x = self._hv.transform(texts)
            out = np.asarray(x @ self._proj, dtype=np.float32)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-8)


_EMBEDDER: Embedder | None = None


def get_embedder(fresh: bool = False) -> Embedder:
    """Runtime embeddings must live in the same space as the world build, so use the kind
    recorded at build time. `fresh=True` (world build) picks the best available instead."""
    global _EMBEDDER
    from app import db

    if fresh:
        _EMBEDDER = Embedder()
        db.kv_set("embedder", _EMBEDDER.kind)
        return _EMBEDDER
    if _EMBEDDER is None:
        built = db.kv_get("embedder")
        _EMBEDDER = Embedder("hash" if built == "hash" else None)
        if built and _EMBEDDER.kind != built:
            raise RuntimeError(f"World was built with '{built}' embeddings but they are unavailable now; run: python run.py build-world")
    return _EMBEDDER


def creative_text(c: dict) -> str:
    parts = [c.get("hook", ""), c.get("body", ""), c.get("cta", "")]
    if c.get("offer") and c["offer"] != "none":
        parts.append(c["offer"])
    if c.get("angle"):
        parts.append(c["angle"])
    return ". ".join(p for p in parts if p)
