# Neural relevance training — 20260907T144022Z

A locally trained NumPy MLP over real benchmark retrieval candidates. No hosted AI API was used.

## Data and configuration

- train examples: 1920 (169 positive)
- validation examples: 500 (41 positive)
- architecture: 5 → 16 → 8 → 1
- split: sha256(question_id) modulo 5
- epochs / learning rate / seed: 500 / 0.02 / 42

## Held-out results

| Metric | Cosine baseline | Neural model | Lift |
|---|---:|---:|---:|
| MRR | 0.544 | 0.717 | +0.173 |
| Recall@6 | 0.646 | 0.799 | +0.153 |

Validation log loss: 0.6248 · accuracy: 0.700
Training loss: 1.2626 → 1.0328

**Decision:** Eligible for a later blended-reranker experiment.

This is a compact feature-based neural experiment, not an end-to-end transformer fine-tune. A GPU-scale fine-tune needs a larger labelled query/passage dataset and a separately approved compute budget.
