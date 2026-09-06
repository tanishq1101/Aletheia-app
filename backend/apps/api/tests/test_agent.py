import pytest

from app.api.answer import get_llm_provider
from main import app
from tests.fixtures import build_pdf


class SequenceLLM:
    name = "sequence-test-model"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return self.replies.pop(0)


@pytest.fixture
def agent_corpus(client, project):
    uploaded = client.post(
        f"/projects/{project['id']}/papers",
        files={
            "file": (
                "agent.pdf",
                build_pdf(
                    [[
                        "1 Results",
                        "Residual connections improve gradient flow in deep networks.",
                        "The evaluation reports higher accuracy on the held-out set.",
                    ]],
                    title="Agent Evidence",
                    author="Tester",
                ),
                "application/pdf",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    return project["id"]


def run_agent(client, project_id: str, llm: SequenceLLM, **payload):
    app.dependency_overrides[get_llm_provider] = lambda: llm
    try:
        return client.post(
            f"/projects/{project_id}/agent/research",
            json={"goal": "Assess the evidence", **payload},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_agent_plans_and_executes_bounded_grounded_steps(client, agent_corpus):
    llm = SequenceLLM([
        '{"questions":["How do residual connections help?","What was evaluated?"]}',
        "They improve gradient flow [E1].",
        "The work evaluates accuracy on a held-out set [E1].",
    ])

    response = run_agent(client, agent_corpus, llm, max_steps=2)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["planned_questions"]) == 2
    assert [step["status"] for step in body["steps"]] == ["succeeded", "succeeded"]
    assert all(step["answer"]["citations"] for step in body["steps"])
    assert len(llm.calls) == 3  # one plan + two grounded answers


def test_agent_caps_the_planner_output(client, agent_corpus):
    llm = SequenceLLM([
        '{"questions":["one?","two?","three?","four?"]}',
        "Answer [E1].",
        "Answer [E1].",
    ])
    body = run_agent(client, agent_corpus, llm, max_steps=2).json()
    assert body["planned_questions"] == ["one?", "two?"]
    assert len(body["steps"]) == 2


@pytest.mark.parametrize(
    "planner_reply",
    [
        '```json\n{"questions":["one?"]}\n```',
        'Here is the plan:\n{"questions":["one?"]}',
    ],
)
def test_agent_accepts_common_json_wrappers(client, agent_corpus, planner_reply):
    llm = SequenceLLM([planner_reply, "Answer [E1]."])
    body = run_agent(client, agent_corpus, llm, max_steps=2).json()
    assert body["planner_fallback_used"] is False
    assert body["planned_questions"] == ["one?"]


def test_invalid_plan_falls_back_to_the_original_goal(client, agent_corpus):
    llm = SequenceLLM(["not json", "Grounded answer [E1]."])
    body = run_agent(client, agent_corpus, llm, max_steps=3).json()
    assert body["planner_fallback_used"] is True
    assert body["planned_questions"] == ["Assess the evidence"]
    assert len(body["steps"]) == 1


def test_agent_step_still_strips_fabricated_citations(client, agent_corpus):
    llm = SequenceLLM([
        '{"questions":["How do residual connections help?"]}',
        "They improve gradient flow [E1], with a 99% gain [E99].",
    ])
    answer = run_agent(client, agent_corpus, llm).json()["steps"][0]["answer"]
    assert answer["fabricated_citations_removed"] == 1
    assert "E99" not in answer["answer"]


def test_agent_rejects_unbounded_step_counts(client, project):
    llm = SequenceLLM([])
    response = run_agent(client, project["id"], llm, max_steps=5)
    assert response.status_code == 422


def test_extended_agent_serializes_public_citations_and_models(client, agent_corpus, monkeypatch):
    monkeypatch.setattr('app.services.discovery.discover_literature', lambda query: ([{
        'title': 'Public evidence', 'url': 'https://doi.org/10.1/fixture',
        'abstract': 'Residual connections improve gradient flow.',
        'provider': 'test', 'year': '2026', 'evidence_scope': 'abstract only',
    }], []))
    llm = SequenceLLM([
        '{"questions":["How do residual connections help?"]}',
        'They improve gradient flow [E1].',
        '**Gradient flow improves** in the library [E1] and public abstract [E2].',
    ])
    response = run_agent(client, agent_corpus, llm, max_steps=1,
                         synthesize=True, discover_sources=True)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(llm.calls) == 3
    assert body['synthesis']['sufficient_evidence']
    assert body['synthesis']['citations'][1]['source_url'] == 'https://doi.org/10.1/fixture'
    assert {row['task'] for row in body['synthesis']['model_diagnostics']} == {'relevance', 'stance'}
    assert body['synthesis']['truncated'] is False
