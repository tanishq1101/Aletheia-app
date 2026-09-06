from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.answer import get_llm_provider
from app.core.config import get_settings
from app.db.session import get_connection
from app.schemas.models import FigureInterpretationResponse, PaperAsset
from app.services.figure_interpretation import (
    FIGURE_PROMPT_VERSION,
    FigureInterpretationError,
    interpret_figure,
)
from app.services.llm import LLMError
from app.services.storage import StorageError, build_storage

router = APIRouter(tags=["assets"])


@router.get("/papers/{paper_id}/assets", response_model=list[PaperAsset])
def list_paper_assets(paper_id: UUID) -> list[PaperAsset]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM papers WHERE id = %s", (str(paper_id),))
        if cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No paper {paper_id}")
        cur.execute(
            """
            SELECT a.id, a.paper_id, a.page_id, p.page_number, a.kind,
                   a.asset_index, a.caption, a.content_text,
                   (a.storage_path IS NOT NULL) AS has_binary,
                   a.bbox, a.metadata, a.created_at
            FROM paper_assets a
            JOIN paper_pages p ON p.id = a.page_id
            WHERE a.paper_id = %s
            ORDER BY p.page_number, a.kind, a.asset_index
            """,
            (str(paper_id),),
        )
        return [PaperAsset(**row) for row in cur.fetchall()]


@router.get("/assets/{asset_id}/content")
def get_asset_content(asset_id: UUID) -> Response:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT storage_path, metadata FROM paper_assets WHERE id = %s",
            (str(asset_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No asset {asset_id}")
    if not row["storage_path"]:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This asset has no binary content."
        )
    try:
        content = build_storage(get_settings()).read(key=row["storage_path"])
    except StorageError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Asset content is unavailable: {exc}",
        ) from exc
    media_type = (row["metadata"] or {}).get("content_type", "application/octet-stream")
    return Response(content=content, media_type=media_type)


@router.post(
    "/assets/{asset_id}/interpret",
    response_model=FigureInterpretationResponse,
)
def interpret_asset_figure(
    asset_id: UUID,
) -> FigureInterpretationResponse:
    """Interpret one figure, caching the first successful bounded result."""
    settings = get_settings()
    cache_model = settings.openrouter_model
    cache_key = f"{asset_id}:{cache_model}:{FIGURE_PROMPT_VERSION}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.paper_id, a.kind, a.caption, a.storage_path, a.metadata,
                       p.page_number, p.cleaned_text
                FROM paper_assets a
                JOIN paper_pages p ON p.id = a.page_id
                WHERE a.id = %s
                """,
                (str(asset_id),),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No asset {asset_id}")
        if row["kind"] != "figure":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Only extracted figure assets can be interpreted in this slice.",
            )
        if not row["storage_path"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This figure has no binary content to interpret.",
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT interpretation, created_at
                FROM asset_interpretations
                WHERE asset_id = %s AND model = %s AND prompt_version = %s
                """,
                (str(asset_id), cache_model, FIGURE_PROMPT_VERSION),
            )
            cached = cur.fetchone()
        if cached is not None:
            return _interpretation_response(row, cached, cache_model, cached=True)

        # Serialize concurrent first requests for this exact cache key. The
        # second request rechecks after the lock and avoids a duplicate paid call.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (cache_key,),
            )
            cur.execute(
                """
                SELECT interpretation, created_at
                FROM asset_interpretations
                WHERE asset_id = %s AND model = %s AND prompt_version = %s
                """,
                (str(asset_id), cache_model, FIGURE_PROMPT_VERSION),
            )
            cached = cur.fetchone()
        if cached is not None:
            return _interpretation_response(row, cached, cache_model, cached=True)

        try:
            content = build_storage(settings).read(key=row["storage_path"])
        except StorageError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Figure content is unavailable: {exc}",
            ) from exc

        media_type = (row["metadata"] or {}).get(
            "content_type", "application/octet-stream"
        )
        try:
            result = interpret_figure(
                image=content,
                media_type=media_type,
                caption=row["caption"],
                page_number=row["page_number"],
                page_text=row["cleaned_text"],
                llm=get_llm_provider(),
            )
        except FigureInterpretationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)
            ) from exc
        except LLMError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Could not interpret the figure: {exc}",
            ) from exc

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_interpretations
                    (asset_id, model, prompt_version, interpretation)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (asset_id, model, prompt_version) DO UPDATE
                SET interpretation = asset_interpretations.interpretation
                RETURNING interpretation, created_at
                """,
                (
                    str(asset_id),
                    cache_model,
                    FIGURE_PROMPT_VERSION,
                    result.text,
                ),
            )
            saved = cur.fetchone()
        conn.commit()
        return _interpretation_response(row, saved, cache_model, cached=False)


def _interpretation_response(
    asset: dict, interpretation: dict, model: str, *, cached: bool
) -> FigureInterpretationResponse:
    return FigureInterpretationResponse(
        asset_id=asset["id"],
        paper_id=asset["paper_id"],
        page_number=asset["page_number"],
        caption=asset["caption"],
        interpretation=interpretation["interpretation"],
        model=model,
        cached=cached,
        created_at=interpretation["created_at"],
    )
