from app.services.asset_extraction import _is_readable_table, extract_assets
from tests.fixtures import build_multimodal_pdf


def test_extracts_figures_tables_and_equation_candidates():
    assets = extract_assets(build_multimodal_pdf())
    kinds = [asset.kind for asset in assets]
    assert "figure" in kinds
    assert "table" in kinds
    assert "equation" in kinds


def test_figure_binary_and_caption_are_linked():
    figure = next(
        asset for asset in extract_assets(build_multimodal_pdf())
        if asset.kind == "figure"
    )
    assert figure.binary is not None
    assert figure.extension == "png"
    assert figure.caption == "Figure 1. Model architecture"
    assert figure.page_number == 1


def test_table_is_structured_as_markdown():
    table = next(
        asset for asset in extract_assets(build_multimodal_pdf())
        if asset.kind == "table"
    )
    assert table.caption == "Table 1. Validation results"
    assert "| Model | Score |" in (table.content_text or "")
    assert "| Aletheia | 0.91 |" in (table.content_text or "")


def test_pathological_layout_grids_are_not_treated_as_tables():
    assert _is_readable_table([["model", "score"], ["A", "0.91"]])
    assert not _is_readable_table([["token"] * 33, ["weight"] * 33])


def test_asset_indexes_are_contiguous_per_kind():
    assets = extract_assets(build_multimodal_pdf())
    for kind in {asset.kind for asset in assets}:
        indexes = [asset.asset_index for asset in assets if asset.kind == kind]
        assert indexes == list(range(len(indexes)))


def test_ingestion_exposes_assets_and_binary_content(client, project):
    response = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("multimodal.pdf", build_multimodal_pdf(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    paper_id = response.json()["id"]

    listed = client.get(f"/papers/{paper_id}/assets")
    assert listed.status_code == 200, listed.text
    assets = listed.json()
    assert {asset["kind"] for asset in assets} >= {"figure", "table", "equation"}

    figure = next(asset for asset in assets if asset["kind"] == "figure")
    content = client.get(f"/assets/{figure['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.content.startswith(b"\x89PNG")


def test_reprocessing_replaces_assets_without_duplicates(client, project):
    uploaded = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("multimodal.pdf", build_multimodal_pdf(), "application/pdf")},
    ).json()
    paper_id = uploaded["id"]
    before = client.get(f"/papers/{paper_id}/assets").json()

    retried = client.post(f"/papers/{paper_id}/reprocess")
    assert retried.status_code == 200, retried.text
    after = client.get(f"/papers/{paper_id}/assets").json()

    assert len(after) == len(before)
    assert {(asset["kind"], asset["asset_index"]) for asset in after} == {
        (asset["kind"], asset["asset_index"]) for asset in before
    }
