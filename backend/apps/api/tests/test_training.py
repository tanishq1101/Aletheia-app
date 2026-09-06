from pathlib import Path

import numpy as np

from app.services.training import (
    NeuralRelevanceModel,
    mean_reciprocal_rank,
    train_neural_relevance_model,
)


def separable_data():
    negative = np.asarray([[0.1, 0.0, 0.0, 0.0, 0.4]] * 30)
    positive = np.asarray([[0.9, 0.7, 1.0, 0.5, 0.6]] * 10)
    return np.vstack([negative, positive]), np.asarray([0] * 30 + [1] * 10)


def test_training_reduces_loss_and_separates_classes():
    features, labels = separable_data()
    model, history = train_neural_relevance_model(features, labels, epochs=250)
    probabilities = model.predict_proba(features).reshape(-1)
    assert history.final_loss < history.initial_loss
    assert probabilities[labels == 1].mean() > probabilities[labels == 0].mean()


def test_training_is_deterministic_for_a_seed():
    features, labels = separable_data()
    first, _ = train_neural_relevance_model(features, labels, epochs=80, seed=7)
    second, _ = train_neural_relevance_model(features, labels, epochs=80, seed=7)
    assert np.allclose(first.predict_proba(features), second.predict_proba(features))


def test_model_save_load_has_prediction_parity(tmp_path: Path):
    features, labels = separable_data()
    model, _ = train_neural_relevance_model(features, labels, epochs=80)
    path = tmp_path / "model.json"
    model.save(path, metadata={"purpose": "test"})
    loaded = NeuralRelevanceModel.load(path)
    assert np.allclose(model.predict_proba(features), loaded.predict_proba(features))


def test_mrr_uses_the_first_relevant_rank_per_question():
    question_ids = ["q1", "q1", "q2", "q2"]
    labels = np.asarray([0, 1, 1, 0])
    scores = np.asarray([0.9, 0.8, 0.7, 0.6])
    assert mean_reciprocal_rank(question_ids, labels, scores) == 0.75
