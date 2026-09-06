"""Upload validation shared by papers, notes, and document attachments."""

PDF_MAGIC = b"%PDF-"
ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


class UploadValidationError(ValueError):
    """Rejected upload. Surfaced to the client as 400, never swallowed."""


def validate_upload(
    *, filename: str, content_type: str | None, data: bytes, max_bytes: int
) -> None:
    if not data:
        raise PdfValidationError("File is empty.")

    if len(data) > max_bytes:
        limit_mb = max_bytes / 1024 / 1024
        raise PdfValidationError(
            f"File is {len(data) / 1024 / 1024:.1f} MB, over the {limit_mb:.0f} MB limit."
        )

    # File type is intentionally not restricted: sources may be PDFs, plain
    # text, slide decks, Office documents, datasets, or binary attachments.
    # Parsing later determines whether text can be indexed. Do not trust a
    # browser's MIME type here; it is frequently empty or generic.
    if filename.lower().endswith(".pdf"):
        if content_type:
            base_type = content_type.split(";")[0].strip().lower()
            if base_type not in ALLOWED_CONTENT_TYPES | {"application/octet-stream"}:
                raise UploadValidationError(f"Unsupported PDF content type: {base_type}")
        if not data.startswith(PDF_MAGIC):
            raise UploadValidationError(
                "File is named .pdf but does not start with the PDF header (%PDF-)."
            )


# Backward-compatible import for integrations that still call the old helper.
PdfValidationError = UploadValidationError
validate_pdf = validate_upload
