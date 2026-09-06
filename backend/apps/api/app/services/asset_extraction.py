"""Layout-aware extraction of figures, tables, and equation candidates.

This module is deliberately deterministic and local. It extracts what the PDF
actually contains and records uncertainty in metadata; it does not claim chart
or mathematical understanding. Vision/math interpretation belongs to a model
provider layered on top of these citable assets.
"""

from dataclasses import dataclass, field
import re
from typing import Any

import pymupdf

from app.core.logging import get_logger
from app.services.normalization import sanitize_for_storage

log = get_logger(__name__)

CAPTION_RE = {
    "figure": re.compile(r"^\s*(?:figure|fig\.)\s*\d+", re.IGNORECASE),
    "table": re.compile(r"^\s*table\s*[A-Z0-9]+", re.IGNORECASE),
}
MATH_SIGNAL = re.compile(r"[=∑∫√±×÷≤≥≈≠∂∇]|\b(?:argmax|argmin|softmax|log|exp)\b")
MAX_TABLE_COLUMNS = 12
MAX_EQUATION_TEXT_LENGTH = 140


@dataclass(frozen=True)
class ExtractedAsset:
    kind: str
    asset_index: int
    page_number: int
    bbox: tuple[float, float, float, float]
    caption: str | None = None
    content_text: str | None = None
    binary: bytes | None = None
    extension: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _text_blocks(page) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in page.get_text("blocks"):
        if len(raw) < 7 or raw[6] != 0:
            continue
        text = sanitize_for_storage(raw[4]).strip()
        if text:
            blocks.append({"bbox": tuple(float(v) for v in raw[:4]), "text": text})
    return blocks


def _caption_for(
    kind: str,
    bbox: tuple[float, float, float, float],
    blocks: list[dict[str, Any]],
) -> str | None:
    pattern = CAPTION_RE[kind]
    x0, y0, x1, y1 = bbox
    candidates: list[tuple[float, str]] = []
    for block in blocks:
        text = " ".join(block["text"].split())
        if not pattern.match(text):
            continue
        bx0, by0, bx1, by1 = block["bbox"]
        horizontal_overlap = max(0.0, min(x1, bx1) - max(x0, bx0))
        if horizontal_overlap <= 0:
            continue
        # Captions normally sit directly below figures and above/below tables.
        vertical_gap = min(abs(by0 - y1), abs(y0 - by1))
        if vertical_gap <= 120:
            candidates.append((vertical_gap, text[:1000]))
    return min(candidates, default=(0.0, None), key=lambda item: item[0])[1]


def _markdown_table(rows: list[list[str | None]]) -> str:
    cleaned = [
        [(cell or "").replace("\n", " ").replace("|", "\\|").strip() for cell in row]
        for row in rows
    ]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    padded = [row + [""] * (width - len(row)) for row in cleaned]
    header = padded[0]
    separator = ["---"] * width
    return "\n".join(
        "| " + " | ".join(row) + " |" for row in [header, separator, *padded[1:]]
    )


def _is_readable_table(rows: list[list[str | None]]) -> bool:
    """Reject layout grids that table detectors often find inside diagrams.

    Real research tables can be wide, but the 30–60 column grids produced by
    token-level attention visualisations are not useful tabular data. Keeping
    a conservative ceiling makes the reader output honest and legible.
    """
    if len(rows) < 2:
        return False
    columns = max((len(row) for row in rows), default=0)
    return 2 <= columns <= MAX_TABLE_COLUMNS


def _inside(
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
) -> bool:
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    return ix0 >= ox0 and iy0 >= oy0 and ix1 <= ox1 and iy1 <= oy1


def extract_assets(data: bytes) -> list[ExtractedAsset]:
    """Extract citable layout objects without any hosted AI dependency."""
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        log.warning("Asset extraction could not open PDF: %s", exc)
        return []

    assets: list[ExtractedAsset] = []
    counters = {"figure": 0, "table": 0, "equation": 0}
    seen_images: set[tuple[int, int, tuple[float, float, float, float]]] = set()

    try:
        for page_number, page in enumerate(document, start=1):
            blocks = _text_blocks(page)
            table_boxes: list[tuple[float, float, float, float]] = []

            # Tables first so equation heuristics can ignore table cells.
            try:
                tables = list(page.find_tables().tables)
            except Exception as exc:
                log.info("Table detection skipped on page %d: %s", page_number, exc)
                tables = []
            for table in tables:
                rows = table.extract()
                if not _is_readable_table(rows):
                    continue
                content = _markdown_table(rows)
                if not content.strip():
                    continue
                bbox = tuple(float(v) for v in table.bbox)
                table_boxes.append(bbox)
                index = counters["table"]
                counters["table"] += 1
                assets.append(
                    ExtractedAsset(
                        kind="table",
                        asset_index=index,
                        page_number=page_number,
                        bbox=bbox,
                        caption=_caption_for("table", bbox, blocks),
                        content_text=content,
                        metadata={"rows": len(rows), "columns": max(len(r) for r in rows)},
                    )
                )

            for info in page.get_image_info(xrefs=True):
                xref = int(info.get("xref") or 0)
                bbox = tuple(float(v) for v in info.get("bbox", (0, 0, 0, 0)))
                width = int(info.get("width") or 0)
                height = int(info.get("height") or 0)
                signature = (page_number, xref, bbox)
                if xref <= 0 or signature in seen_images or width < 120 or height < 80:
                    continue
                if width * height < 20_000:
                    continue
                seen_images.add(signature)
                try:
                    extracted = document.extract_image(xref)
                    binary = extracted["image"]
                    extension = str(extracted.get("ext") or "png").lower()
                except Exception as exc:
                    log.info("Image xref %d on page %d skipped: %s", xref, page_number, exc)
                    continue
                index = counters["figure"]
                counters["figure"] += 1
                assets.append(
                    ExtractedAsset(
                        kind="figure",
                        asset_index=index,
                        page_number=page_number,
                        bbox=bbox,
                        caption=_caption_for("figure", bbox, blocks),
                        binary=binary,
                        extension=extension,
                        metadata={
                            "width": width,
                            "height": height,
                            "content_type": f"image/{'jpeg' if extension in {'jpg', 'jpeg'} else extension}",
                            "xref": xref,
                        },
                    )
                )

            # Conservative text equations: short blocks with an explicit math
            # signal, excluding captions and detected table regions.
            for block in blocks:
                bbox = block["bbox"]
                text = " ".join(block["text"].split())
                if any(_inside(bbox, table_bbox) for table_bbox in table_boxes):
                    continue
                if (
                    len(text) < 3
                    or len(text) > MAX_EQUATION_TEXT_LENGTH
                    or not MATH_SIGNAL.search(text)
                ):
                    continue
                if CAPTION_RE["figure"].match(text) or CAPTION_RE["table"].match(text):
                    continue
                alpha = sum(char.isalpha() for char in text)
                math = sum(not char.isalnum() and not char.isspace() for char in text)
                if math < 1 or alpha > 220:
                    continue
                index = counters["equation"]
                counters["equation"] += 1
                assets.append(
                    ExtractedAsset(
                        kind="equation",
                        asset_index=index,
                        page_number=page_number,
                        bbox=bbox,
                        content_text=text,
                        metadata={"heuristic": True, "confidence": "candidate"},
                    )
                )
    finally:
        document.close()

    return assets
