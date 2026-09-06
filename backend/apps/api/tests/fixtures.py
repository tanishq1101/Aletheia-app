"""Generated PDF fixtures.

Built with PyMuPDF rather than checked in as binaries or downloaded, so the
tests are deterministic, offline, and reviewable as code.
"""

import pymupdf

# Body paragraphs are long enough to wrap, so normalization's line-rejoining
# and de-hyphenation are actually exercised rather than trivially satisfied.
PAPER_PAGES: list[list[str]] = [
    [
        "Deep Residual Learning for Image Recognition",
        "",
        "Abstract",
        "",
        "Deeper neural networks are more difficult to train. We present a residual",
        "learning framework to ease the training of networks that are substantially",
        "deeper than those used previously.",
        "",
        "1 Introduction",
        "",
        "Deep convolutional neural networks have led to a series of break-",
        "throughs for image classification. Recent evidence reveals that network",
        "depth is of crucial importance for accuracy.",
    ],
    [
        "2 Related Work",
        "",
        "Residual representations have a long history in computer vision and in",
        "numerical optimization, where they are widely used.",
        "",
        "3 Methods",
        "",
        "We adopt residual learning to every few stacked layers of the network.",
        "",
        "3.1 Identity Mapping by Shortcuts",
        "",
        "We consider a building block defined over the input and output dimen-",
        "sions of each layer.",
    ],
    [
        "4 Experiments",
        "",
        "We evaluate our method on ImageNet classification and report top-1 and",
        "top-5 error rates.",
        "",
        "5 Conclusion",
        "",
        "We presented a residual learning framework that is easier to optimize",
        "than the plain counterparts.",
        "",
        "References",
        "",
        "He et al. Deep Residual Learning for Image Recognition.",
    ],
]


def build_pdf(
    pages: list[list[str]] | None = None,
    *,
    title: str | None = "Deep Residual Learning for Image Recognition",
    author: str | None = "Kaiming He; Xiangyu Zhang; Shaoqing Ren",
) -> bytes:
    """Render lines to a PDF, one list of lines per page."""
    pages = PAPER_PAGES if pages is None else pages
    doc = pymupdf.open()

    for lines in pages:
        page = doc.new_page(width=612, height=792)
        y = 72.0
        for line in lines:
            if line:
                page.insert_text((72, y), line, fontsize=11, fontname="helv")
            y += 16
    meta = {}
    if title:
        meta["title"] = title
    if author:
        meta["author"] = author
    if meta:
        doc.set_metadata(meta)

    data = doc.tobytes()
    doc.close()
    return data


def build_single_page_pdf(text: str = "Hello world.") -> bytes:
    return build_pdf([[text]], title=None, author=None)


def build_encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "secret", fontsize=11, fontname="helv")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    return data


def build_corrupt_pdf() -> bytes:
    """Valid %PDF- header (so upload validation passes) but unparseable body."""
    return b"%PDF-1.4\n" + b"\x00\xff garbage that is not a pdf body " * 20


def build_multimodal_pdf() -> bytes:
    """One raster figure, one ruled table, and one text equation."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)

    pixmap = pymupdf.Pixmap(
        pymupdf.csRGB, pymupdf.IRect(0, 0, 240, 120), 0
    )
    pixmap.clear_with(220)
    page.insert_image(
        pymupdf.Rect(72, 80, 312, 200), stream=pixmap.tobytes("png")
    )
    page.insert_text((72, 220), "Figure 1. Model architecture", fontsize=10)

    page.insert_text((72, 275), "Table 1. Validation results", fontsize=10)
    xs = [72, 192, 312]
    ys = [290, 320, 350]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    page.insert_text((82, 310), "Model", fontsize=10)
    page.insert_text((202, 310), "Score", fontsize=10)
    page.insert_text((82, 340), "Aletheia", fontsize=10)
    page.insert_text((202, 340), "0.91", fontsize=10)

    page.insert_text((72, 410), "loss = -log p(y | x)", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data
