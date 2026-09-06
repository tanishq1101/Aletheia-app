import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from app.api.assets import interpret_asset_figure
from app.core.config import get_settings
from app.db.session import get_connection
from app.services.figure_interpretation import (
    FigureInterpretationError,
    MAX_FIGURE_BYTES,
    interpret_figure,
)
from app.services.llm import LLMError
from tests.fixtures import build_multimodal_pdf


class VisionLLM:
    name = "vision-test-model"

    def __init__(self, *, delay: float = 0):
        self.calls: list[dict] = []
        self.delay = delay

    def complete_with_image(self, **kwargs) -> str:
        self.calls.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        return (
            "Visible content: an architecture diagram.\n"
            "Likely role: summarizes the model.\n"
            "Uncertainty: labels are too small to verify."
        )


class FailingVisionLLM(VisionLLM):
    def complete_with_image(self, **kwargs) -> str:
        self.calls.append(kwargs)
        raise LLMError("quota reached")


@pytest.fixture
def multimodal_assets(client, project):
    response = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("multimodal.pdf", build_multimodal_pdf(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    paper_id = response.json()["id"]
    return client.get(f"/papers/{paper_id}/assets").json()


def test_asset_listing_does_not_auto_run_vision(client, multimodal_assets, monkeypatch):
    def forbidden_provider():
        raise AssertionError("asset listing must not resolve an AI provider")

    monkeypatch.setattr("app.api.assets.get_llm_provider", forbidden_provider)
    paper_id = multimodal_assets[0]["paper_id"]

    listed = client.get(f"/papers/{paper_id}/assets")

    assert listed.status_code == 200


def test_interprets_once_then_returns_cached_without_model_call(
    client, multimodal_assets, monkeypatch
):
    figure = next(asset for asset in multimodal_assets if asset["kind"] == "figure")
    llm = VisionLLM()
    monkeypatch.setattr("app.api.assets.get_llm_provider", lambda: llm)

    created = client.post(f"/assets/{figure['id']}/interpret")

    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["asset_id"] == figure["id"]
    assert created_body["ai_generated"] is True
    assert created_body["model"] == get_settings().openrouter_model
    assert created_body["cached"] is False
    assert created_body["created_at"]
    assert len(llm.calls) == 1
    assert llm.calls[0]["media_type"] == "image/png"
    assert llm.calls[0]["image"].startswith(b"\x89PNG")
    assert llm.calls[0]["max_output_tokens"] == 500

    def forbidden_provider():
        raise AssertionError("a cache hit must not resolve an AI provider")

    monkeypatch.setattr("app.api.assets.get_llm_provider", forbidden_provider)
    cached = client.post(f"/assets/{figure['id']}/interpret")

    assert cached.status_code == 200, cached.text
    cached_body = cached.json()
    assert cached_body["cached"] is True
    assert cached_body["interpretation"] == created_body["interpretation"]
    assert cached_body["created_at"] == created_body["created_at"]
    assert len(llm.calls) == 1


def test_concurrent_first_requests_make_one_model_call(multimodal_assets, monkeypatch):
    figure = next(asset for asset in multimodal_assets if asset["kind"] == "figure")
    llm = VisionLLM(delay=0.1)
    monkeypatch.setattr("app.api.assets.get_llm_provider", lambda: llm)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                interpret_asset_figure,
                [UUID(figure["id"]), UUID(figure["id"])],
            )
        )

    assert len(llm.calls) == 1
    assert sorted(result.cached for result in results) == [False, True]
    assert results[0].interpretation == results[1].interpretation


def test_provider_failure_does_not_create_cache_row(
    client, multimodal_assets, monkeypatch
):
    figure = next(asset for asset in multimodal_assets if asset["kind"] == "figure")
    llm = FailingVisionLLM()
    monkeypatch.setattr("app.api.assets.get_llm_provider", lambda: llm)

    response = client.post(f"/assets/{figure['id']}/interpret")

    assert response.status_code == 503
    assert "quota reached" in response.json()["detail"]
    assert len(llm.calls) == 1
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS count FROM asset_interpretations WHERE asset_id = %s",
            (figure["id"],),
        )
        assert cur.fetchone()["count"] == 0


def test_reprocessing_removes_cached_interpretation(
    client, multimodal_assets, monkeypatch
):
    figure = next(asset for asset in multimodal_assets if asset["kind"] == "figure")
    paper_id = figure["paper_id"]
    llm = VisionLLM()
    monkeypatch.setattr("app.api.assets.get_llm_provider", lambda: llm)
    assert client.post(f"/assets/{figure['id']}/interpret").status_code == 200

    retried = client.post(f"/papers/{paper_id}/reprocess")

    assert retried.status_code == 200, retried.text
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS count FROM asset_interpretations WHERE asset_id = %s",
            (figure["id"],),
        )
        assert cur.fetchone()["count"] == 0


def test_non_figure_assets_are_rejected_without_model_call(
    client, multimodal_assets, monkeypatch
):
    table = next(asset for asset in multimodal_assets if asset["kind"] == "table")
    llm = VisionLLM()
    monkeypatch.setattr("app.api.assets.get_llm_provider", lambda: llm)

    response = client.post(f"/assets/{table['id']}/interpret")

    assert response.status_code == 422
    assert "Only extracted figure" in response.json()["detail"]
    assert llm.calls == []


def test_figure_service_rejects_oversized_images_before_model_call():
    llm = VisionLLM()
    with pytest.raises(FigureInterpretationError, match="too large"):
        interpret_figure(
            image=b"x" * (MAX_FIGURE_BYTES + 1),
            media_type="image/png",
            caption=None,
            page_number=1,
            page_text=None,
            llm=llm,
        )
    assert llm.calls == []
