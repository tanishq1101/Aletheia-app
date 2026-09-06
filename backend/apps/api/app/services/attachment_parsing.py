"""Text extraction for non-PDF project sources using only the standard library."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from app.services.normalization import normalize_page_text, sanitize_for_storage
from app.services.providers import DocumentMetadata, ParsedDocument, ParsedPage

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml",
    ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".css",
    ".sql", ".tex", ".log", ".rtf",
}
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".odp", ".odt", ".ods"}
XML_TEXT_TAGS = {"t", "p", "h", "text", "span"}


def _page(text: str) -> ParsedPage:
    clean = normalize_page_text(sanitize_for_storage(text))
    return ParsedPage(page_number=1, raw_text=clean, cleaned_text=clean)


def _zip_text(data: bytes, suffix: str) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = sorted(
                name for name in archive.namelist()
                if name.endswith(".xml") and not name.startswith("__MACOSX/")
            )
            # Slide, document, and spreadsheet XML all store visible strings in
            # text nodes. Keeping each XML file on its own line preserves slide
            # boundaries well enough for chunking and citation locations.
            blocks: list[str] = []
            for name in names:
                if suffix == ".pptx" and not name.startswith("ppt/slides/"):
                    continue
                if suffix == ".docx" and name != "word/document.xml":
                    continue
                root = ElementTree.fromstring(archive.read(name))
                words = [
                    (node.text or "").strip()
                    for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1] in XML_TEXT_TAGS and (node.text or "").strip()
                ]
                if words:
                    blocks.append(" ".join(words))
            return "\n\n".join(blocks)
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise ValueError(f"Could not read this Office document: {exc}") from exc


def parse_attachment(*, data: bytes, filename: str) -> ParsedDocument:
    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        text = data.decode("utf-8", errors="replace")
    elif suffix in OFFICE_EXTENSIONS:
        text = _zip_text(data, suffix)
    else:
        # Unknown/binary formats remain valid project sources. A small indexed
        # notice makes the limitation explicit rather than pretending bytes are
        # searchable text.
        text = f"Attachment: {filename}\nNo text could be extracted from this file type."

    title = Path(filename).stem or filename
    return ParsedDocument(
        metadata=DocumentMetadata(page_count=1, title=title),
        pages=[_page(text)],
        sections=[],
    )
