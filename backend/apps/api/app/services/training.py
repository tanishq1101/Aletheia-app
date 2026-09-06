"""Small, reproducible neural relevance model for the project benchmark.

This is training code, not a disguised heuristic: a 5→16→8→1 MLP is optimized
with weighted binary cross-entropy and backpropagation implemented in NumPy.
It learns over transparent candidate features so it can run on a laptop. It is
an experiment alongside the production cross-encoder, not an unmeasured swap.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

import numpy as np

from app.services.retrieval import RetrievedChunk

FEATURE_NAMES = (
    "cosine_similarity",
    "query_content_jaccard",
    "numeric_token_coverage",
    "section_query_overlap",
    "content_length_log",
)
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:\.[0-9]+)?")


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in WORD_RE.findall(value)}


def candidate_features(query: str, chunk: RetrievedChunk) -> np.ndarray:
    query_tokens = _tokens(query)
    content_tokens = _tokens(chunk.content)
    union = query_tokens | content_tokens
    jaccard = len(query_tokens & content_tokens) / len(union) if union else 0.0
    numbers = {token for token in query_tokens if any(char.isdigit() for char in token)}
    number_coverage = (
        len(numbers & content_tokens) / len(numbers) if numbers else 0.0
    )
    section_tokens = _tokens(chunk.section or "")
    section_overlap = (
        len(query_tokens & section_tokens) / len(query_tokens) if query_tokens else 0.0
    )
    length_log = math.log1p(len(content_tokens)) / 10.0
    return np.asarray(
        [chunk.similarity, jaccard, number_coverage, section_overlap, length_log],
        dtype=np.float64,
    )


def binary_log_loss(y: np.ndarray, probabilities: np.ndarray) -> float:
    clipped = np.clip(probabilities, 1e-7, 1 - 1e-7)
    return float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped)))


@dataclass
class NeuralRelevanceModel:
    mean: np.ndarray
    scale: np.ndarray
    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: np.ndarray
    w3: np.ndarray
    b3: np.ndarray

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        x = (np.asarray(features, dtype=np.float64) - self.mean) / self.scale
        h1 = np.maximum(0.0, x @ self.w1 + self.b1)
        h2 = np.maximum(0.0, h1 @ self.w2 + self.b2)
        logits = h2 @ self.w3 + self.b3
        return 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))

    def save(self, path: Path, *, metadata: dict | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "architecture": [len(self.mean), 16, 8, 1],
            "feature_names": list(FEATURE_NAMES),
            "metadata": metadata or {},
            **{
                name: getattr(self, name).tolist()
                for name in ("mean", "scale", "w1", "b1", "w2", "b2", "w3", "b3")
            },
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "NeuralRelevanceModel":
        payload = json.loads(path.read_text())
        if payload.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("Model feature contract does not match this code version.")
        return cls(
            **{
                name: np.asarray(payload[name], dtype=np.float64)
                for name in ("mean", "scale", "w1", "b1", "w2", "b2", "w3", "b3")
            }
        )


@dataclass(frozen=True)
class TrainingHistory:
    initial_loss: float
    final_loss: float
    losses: list[float]


def train_neural_relevance_model(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    epochs: int = 500,
    learning_rate: float = 0.02,
    seed: int = 42,
) -> tuple[NeuralRelevanceModel, TrainingHistory]:
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64).reshape(-1, 1)
    if x.ndim != 2 or x.shape[0] != y.shape[0] or x.shape[0] < 2:
        raise ValueError("features and labels must contain at least two aligned rows")
    if set(np.unique(y)) - {0.0, 1.0}:
        raise ValueError("labels must be binary")

    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    x = (x - mean) / scale

    rng = np.random.default_rng(seed)
    w1 = rng.normal(0, 0.15, size=(x.shape[1], 16))
    b1 = np.zeros((1, 16))
    w2 = rng.normal(0, 0.15, size=(16, 8))
    b2 = np.zeros((1, 8))
    w3 = rng.normal(0, 0.15, size=(8, 1))
    b3 = np.zeros((1, 1))

    positives = max(1.0, float(y.sum()))
    negatives = max(1.0, float(len(y) - y.sum()))
    positive_weight = negatives / positives
    losses: list[float] = []

    for epoch in range(epochs):
        z1 = x @ w1 + b1
        h1 = np.maximum(0.0, z1)
        z2 = h1 @ w2 + b2
        h2 = np.maximum(0.0, z2)
        logits = h2 @ w3 + b3
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))

        weights = np.where(y == 1.0, positive_weight, 1.0)
        clipped = np.clip(probabilities, 1e-7, 1 - 1e-7)
        loss = float(
            -np.mean(weights * (y * np.log(clipped) + (1 - y) * np.log(1 - clipped)))
        )
        if epoch == 0 or epoch == epochs - 1 or (epoch + 1) % 25 == 0:
            losses.append(loss)

        dlogits = weights * (probabilities - y) / len(y)
        dw3 = h2.T @ dlogits
        db3 = dlogits.sum(axis=0, keepdims=True)
        dh2 = dlogits @ w3.T
        dz2 = dh2 * (z2 > 0)
        dw2 = h1.T @ dz2
        db2 = dz2.sum(axis=0, keepdims=True)
        dh1 = dz2 @ w2.T
        dz1 = dh1 * (z1 > 0)
        dw1 = x.T @ dz1
        db1 = dz1.sum(axis=0, keepdims=True)

        # Gradient clipping keeps a noisy small dataset from exploding.
        for gradient in (dw1, db1, dw2, db2, dw3, db3):
            np.clip(gradient, -5.0, 5.0, out=gradient)
        w1 -= learning_rate * dw1
        b1 -= learning_rate * db1
        w2 -= learning_rate * dw2
        b2 -= learning_rate * db2
        w3 -= learning_rate * dw3
        b3 -= learning_rate * db3

    model = NeuralRelevanceModel(mean, scale, w1, b1, w2, b2, w3, b3)
    return model, TrainingHistory(
        initial_loss=losses[0],
        final_loss=losses[-1],
        losses=losses,
    )


def mean_reciprocal_rank(
    question_ids: list[str], labels: np.ndarray, scores: np.ndarray
) -> float:
    values: list[float] = []
    for question_id in dict.fromkeys(question_ids):
        indexes = [i for i, value in enumerate(question_ids) if value == question_id]
        ranked = sorted(indexes, key=lambda index: float(scores[index]), reverse=True)
        rank = next((position for position, index in enumerate(ranked, 1) if labels[index]), None)
        values.append(1.0 / rank if rank else 0.0)
    return float(np.mean(values)) if values else 0.0
