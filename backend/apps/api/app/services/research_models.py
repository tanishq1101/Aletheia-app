"""Portable text-pair deep classifiers. NumPy inference; no pickle or remote code.

These are compact learned MLPs, not language generators. Hash features preserve
lexical evidence but not word order; stance is experimental and never a verdict.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
FEATURE_VERSION = 'hashed-pair-v1'
WIDTH = 128
INPUT_DIM = WIDTH * 4 + 4
TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")

@lru_cache(maxsize=40000)
def _bucket(token):
    value = hashlib.blake2b(token.encode(), digest_size=8).digest()
    return int.from_bytes(value[:4], 'little') % WIDTH, 1 if value[4] % 2 else -1

@lru_cache(maxsize=8192)
def _encode(text):
    tokens = frozenset(TOKEN.findall(text.lower()))
    vector = np.zeros(WIDTH, dtype=np.float32)
    for token in sorted(tokens):
        bucket, sign = _bucket(token)
        vector[bucket] += sign
    vector /= max(float(np.linalg.norm(vector)), 1e-8)
    return vector, tokens

def pair_features(pairs):
    rows = []
    for query, passage in pairs:
        q, qt = _encode(query)
        p, pt = _encode(passage)
        overlap = len(qt & pt)
        rows.append(np.concatenate([q, p, np.abs(q-p), q*p, np.array([
            overlap / max(len(qt), 1), overlap / max(len(qt | pt), 1),
            float(q @ p), min(len(pt), 2000) / 2000,
        ], dtype=np.float32)]))
    return np.asarray(rows, dtype=np.float32).reshape(-1, INPUT_DIM)

def softmax(logits):
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    return exp / exp.sum(axis=1, keepdims=True)

class PairClassifier:
    def __init__(self, weights, metadata):
        self.weights = weights
        self.metadata = metadata

    def predict(self, x):
        w = self.weights
        h = np.maximum(0, x @ w['w1'] + w['b1'])
        h = np.maximum(0, h @ w['w2'] + w['b2'])
        return softmax(h @ w['w3'] + w['b3'])

    def save(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(directory / 'weights.npz', **self.weights)
        metadata = {**self.metadata, 'feature_version': FEATURE_VERSION,
                    'weights_sha256': hashlib.sha256((directory / 'weights.npz').read_bytes()).hexdigest()}
        (directory / 'model.json').write_text(json.dumps(metadata, indent=2) + '\n')

    @classmethod
    def load(cls, directory):
        metadata = json.loads((directory / 'model.json').read_text())
        if metadata.get('feature_version') != FEATURE_VERSION:
            raise ValueError('Incompatible feature contract')
        if hashlib.sha256((directory / 'weights.npz').read_bytes()).hexdigest() != metadata['weights_sha256']:
            raise ValueError('Model checksum mismatch')
        dims = metadata['architecture']
        if len(dims) != 4 or dims[0] != INPUT_DIM or dims[-1] != 2 or any(not isinstance(n, int) or not 1 <= n <= 2048 for n in dims):
            raise ValueError('Invalid model architecture')
        with np.load(directory / 'weights.npz', allow_pickle=False) as payload:
            weights = {key: payload[key] for key in ['w1','b1','w2','b2','w3','b3']}
        for layer in range(1, 4):
            for key, shape in [(f'w{layer}', (dims[layer-1], dims[layer])), (f'b{layer}', (dims[layer],))]:
                if weights[key].shape != shape or not np.isfinite(weights[key]).all():
                    raise ValueError('Invalid model weights')
        return cls(weights, metadata)

@lru_cache(maxsize=8)
def load_classifier(directory: str):
    return PairClassifier.load(Path(directory))

def research_diagnostics(query, evidence):
    """Advisory outputs are isolated from citation validity and sufficiency."""
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.research_models_enabled or not evidence:
        return []
    directory = Path(settings.research_models_dir)
    if not directory.is_absolute():
        directory = ROOT / directory
    features = pair_features([(query, item.content) for item in evidence])
    result = []
    for task in ['relevance', 'stance']:
        try:
            model = load_classifier(str(directory / task))
            scores = model.predict(features)
            result.append({'task': task, 'status': 'experimental',
                'labels': model.metadata['labels'],
                'validation_macro_f1': model.metadata['validation']['macro_f1'],
                'note': 'Uncalibrated model scores, not factual confidence. Stance requires a declarative claim and cannot verify a question.',
                'scores': [{'evidence_id': item.evidence_id, 'values': values.tolist()} for item, values in zip(evidence, scores, strict=True)]})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            from app.core.logging import get_logger
            get_logger(__name__).warning('Research model %s unavailable: %s', task, exc)
            result.append({'task': task, 'status': 'unavailable', 'scores': [], 'labels': [], 'note': 'Model artifact is unavailable or invalid.'})
    return result
