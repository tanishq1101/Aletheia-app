"""Sprint 1 PDF validation: is this actually a PDF, and is it a sane size?

Deliberately shallow. Structural parsing, page counting, and metadata
extraction are Sprint 2 (PyMuPDF) — this only checks what can be checked
without opening the document.
"""

PDF_MAGIC = b"%PDF-"
ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


class PdfValidationError(ValueError):
    """Rejected upload. Surfaced to the client as 400, never swallowed."""


def validate_pdf(
    *, filename: str, content_type: str | None, data: bytes, max_bytes: int
) -> None:
    if not data:
        raise PdfValidationError("File is empty.")

    if len(data) > max_bytes:
        limit_mb = max_bytes / 1024 / 1024
        raise PdfValidationError(
            f"File is {len(data) / 1024 / 1024:.1f} MB, over the {limit_mb:.0f} MB limit."
        )

    if not filename.lower().endswith(".pdf"):
        raise PdfValidationError("Filename must end in .pdf")

    # Browsers occasionally send an empty or generic content type; the magic
    # byte check below is the authoritative one, so only reject a type that is
    # present AND wrong.
    if content_type:
        base_type = content_type.split(";")[0].strip().lower()
        if base_type not in ALLOWED_CONTENT_TYPES | {"application/octet-stream"}:
            raise PdfValidationError(f"Unsupported content type: {base_type}")

    if not data.startswith(PDF_MAGIC):
        raise PdfValidationError(
            "File does not start with the PDF header (%PDF-); it is not a PDF."
        )
