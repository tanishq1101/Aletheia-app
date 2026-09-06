"""On-demand interpretation for one already-extracted figure.

This slice is intentionally not a batch pipeline: callers supply one resolved
asset, and the API makes at most one bounded multimodal provider call before
reusing the saved result for the same figure, model, and prompt version.
"""

from dataclasses import dataclass

from app.services.providers import LLMProvider

MAX_FIGURE_BYTES = 5 * 1024 * 1024
MAX_PAGE_CONTEXT_CHARS = 2500
MAX_VISION_OUTPUT_TOKENS = 500
FIGURE_PROMPT_VERSION = "figure-v1"
SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

FIGURE_SYSTEM = """You interpret scientific-paper figures using only the supplied image,
caption, and page excerpt. Be precise and conservative. Return three short sections:
Visible content, Likely role in the paper, and Uncertainty. Do not invent unreadable labels,
numerical values, experimental results, or claims not supported by the supplied material."""


class FigureInterpretationError(ValueError):
    """The selected asset cannot safely be sent for figure interpretation."""


@dataclass(frozen=True)
class FigureInterpretation:
    text: str
    model: str


def interpret_figure(
    *,
    image: bytes,
    media_type: str,
    caption: str | None,
    page_number: int,
    page_text: str | None,
    llm: LLMProvider,
) -> FigureInterpretation:
    if media_type not in SUPPORTED_IMAGE_TYPES:
        raise FigureInterpretationError(f"Unsupported figure media type: {media_type}")
    if not image:
        raise FigureInterpretationError("The figure image is empty.")
    if len(image) > MAX_FIGURE_BYTES:
        raise FigureInterpretationError(
            f"The figure is too large for interpretation ({len(image)} bytes; "
            f"limit {MAX_FIGURE_BYTES})."
        )

    context = (page_text or "").strip()[:MAX_PAGE_CONTEXT_CHARS]
    prompt = "\n".join(
        [
            f"PDF page: {page_number}",
            f"Caption: {caption or 'No caption detected.'}",
            f"Page excerpt: {context or 'No page text available.'}",
            "Interpret this single figure. Clearly distinguish visible evidence from inference.",
        ]
    )
    text = llm.complete_with_image(
        system=FIGURE_SYSTEM,
        prompt=prompt,
        image=image,
        media_type=media_type,
        max_output_tokens=MAX_VISION_OUTPUT_TOKENS,
    )
    return FigureInterpretation(
        text=text,
        model=getattr(llm, "name", type(llm).__name__),
    )
