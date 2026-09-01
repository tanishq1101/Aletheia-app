"""PyMuPDF implementation of DocumentParser (PRD Section 6).

Only place in the codebase that imports pymupdf — everything else goes through
the DocumentParser interface so the library stays swappable.
"""

import re

import pymupdf

from app.core.logging import get_logger
from app.services.normalization import normalize_page_text, sanitize_for_storage
from app.services.providers import (
    DetectedSection,
    DocumentMetadata,
    ParsedDocument,
    ParsedPage,
    ParserError,
)

log = get_logger(__name__)

# Headings we expect in a research paper, matched case-insensitively on a line
# of its own. Covers IMRaD plus the usual extras.
CANONICAL_HEADINGS = {
    "abstract", "introduction", "background", "related work", "prior work",
    "motivation", "preliminaries", "methods", "method", "methodology",
    "approach", "model", "architecture", "experiments", "experimental setup",
    "evaluation", "results", "analysis", "ablation", "ablations",
    "discussion", "limitations", "conclusion", "conclusions",
    "future work", "acknowledgments", "acknowledgements", "references",
    "bibliography", "appendix", "supplementary material",
}

# "3 Methods", "3.1 Training setup", "IV. Results"
_NUMBERED = re.compile(
    r"^\s*(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>[A-Z][^\n]{2,80})\s*$"
)
_ROMAN = re.compile(
    r"^\s*(?P<num>[IVXLC]+)\.\s+(?P<title>[A-Z][^\n]{2,80})\s*$"
)

# A heading should not end like a sentence.
_SENTENCE_END = re.compile(r"[.;:,]$")


def _looks_like_heading(line: str) -> tuple[bool, int, str]:
    """Return (is_heading, level, cleaned_title) for a single line."""
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False, 0, ""

    bare = stripped.lower().rstrip(".")
    if bare in CANONICAL_HEADINGS:
        return True, 1, stripped.rstrip(".")

    match = _NUMBERED.match(stripped)
    if match:
        title = match.group("title").strip()
        if not _SENTENCE_END.search(title):
            # "3" -> level 1, "3.1" -> level 2, "3.1.2" -> level 3
            level = match.group("num").count(".") + 1
            return True, level, stripped
        return False, 0, ""

    match = _ROMAN.match(stripped)
    if match and not _SENTENCE_END.search(match.group("title")):
        return True, 1, stripped

    return False, 0, ""


def detect_sections(pages: list[ParsedPage]) -> list[DetectedSection]:
    """Heuristic section detection over page text.

    Detection reads RAW text, not cleaned text: a heading is a layout feature —
    a short line on its own — and normalization deliberately collapses the
    single newlines that make it identifiable. Offsets are then resolved
    against cleaned_text, because that is what Sprint 3 will chunk.

    Deliberately "basic" per PRD Sprint 2 — structural heading detection, not
    semantic understanding of the paper.
    """
    sections: list[DetectedSection] = []
    seen: set[str] = set()

    for page in pages:
        for line in page.raw_text.split("\n"):
            is_heading, level, title = _looks_like_heading(line)
            if not is_heading:
                continue

            # A repeated heading is almost always a running header, not a
            # second section.
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)

            # Locate the heading in the normalized text so Sprint 3 can map a
            # chunk back to its section. -1 (not found) is stored as None
            # rather than a wrong offset.
            found = page.cleaned_text.find(title)
            sections.append(
                DetectedSection(
                    title=title,
                    level=level,
                    section_index=len(sections),
                    start_page=page.page_number,
                    start_offset=found if found >= 0 else None,
                )
            )

    return sections


def _split_authors(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    parts = re.split(r"\s*(?:;|,| and )\s*", raw)
    return [p.strip() for p in parts if p.strip()]


ABSTRACT_MAX_CHARS = 4000


def _find_abstract(
    pages: list[ParsedPage], sections: list[DetectedSection]
) -> str | None:
    """Extract the abstract, bounded by the sections already detected.

    Derived from section boundaries rather than searched for independently:
    the headings that bound it were found against raw text, where the line
    structure still exists. Searching normalized text for a following heading
    does not work, because normalization has collapsed the newline that made
    the heading a heading.
    """
    if not pages or not sections:
        return None

    abstract_section = next(
        (s for s in sections if s.title.strip().lower().rstrip(".") == "abstract"),
        None,
    )
    if abstract_section is None or abstract_section.start_offset is None:
        return None

    page = pages[abstract_section.start_page - 1]
    start = abstract_section.start_offset + len(abstract_section.title)

    # End at the next heading on the same page, if there is one.
    following = [
        s
        for s in sections
        if s.section_index > abstract_section.section_index
        and s.start_page == abstract_section.start_page
        and s.start_offset is not None
        and s.start_offset > start
    ]
    end = following[0].start_offset if following else len(page.cleaned_text)

    abstract = page.cleaned_text[start:end].strip(" :.\n")
    return abstract[:ABSTRACT_MAX_CHARS].strip() or None


class PyMuPDFParser:
    """Implements the DocumentParser protocol."""

    def parse(self, *, data: bytes) -> ParsedDocument:
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise ParserError(f"Could not open PDF: {exc}") from exc

        try:
            if document.needs_pass:
                raise ParserError(
                    "PDF is password-protected and cannot be read."
                )

            page_count = document.page_count
            if page_count < 1:
                raise ParserError("PDF contains no pages.")

            pages: list[ParsedPage] = []
            for index in range(page_count):
                try:
                    # "text" preserves natural reading order for normal
                    # single/multi-column research papers.
                    # Sanitized at the boundary, so no consumer of ParsedPage
                    # ever sees a byte the database cannot store — and section
                    # detection reads exactly the string that gets persisted.
                    raw = sanitize_for_storage(
                        document.load_page(index).get_text("text")
                    )
                except Exception as exc:
                    # One unreadable page must not lose the other 30. Record it
                    # as empty and carry on — visible, not silent.
                    log.warning(
                        "Page %d could not be extracted (%s); stored as empty.",
                        index + 1,
                        exc,
                    )
                    raw = ""

                pages.append(
                    ParsedPage(
                        page_number=index + 1,
                        raw_text=raw,
                        cleaned_text=normalize_page_text(raw),
                    )
                )

            meta = document.metadata or {}
            title = (meta.get("title") or "").strip() or None
            authors = _split_authors(meta.get("author") or "")
            sections = detect_sections(pages)

            return ParsedDocument(
                metadata=DocumentMetadata(
                    page_count=page_count,
                    title=title,
                    authors=authors,
                    abstract=_find_abstract(pages, sections),
                ),
                pages=pages,
                sections=sections,
            )
        finally:
            document.close()


def build_parser() -> PyMuPDFParser:
    return PyMuPDFParser()
