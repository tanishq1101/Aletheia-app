"""Text normalization for extracted PDF page text.

Goal (PRD Section 12): keep text ordering and paragraph structure intact while
removing artefacts of PDF layout. Deliberately conservative — it is far worse to
silently drop real content than to leave a stray artefact in place.

Not done here: tokenization or chunking (Sprint 3).
"""

import re
import unicodedata

# Ligatures PDFs commonly embed as single glyphs.
LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}

# Assorted Unicode spaces PDFs use for kerning, plus the zero-width family.
_ODD_SPACES = re.compile(r"[   -   　]")
_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")

# A word split across a line break by hyphenation: "represen-\ntation".
# Lowercase either side excludes numeric ranges and proper nouns. The trailing
# \b(?!-) distinguishes a split word from a genuine compound that broke at a
# hyphen: in "state-\nof-the-art" the continuation "of" is itself followed by a
# hyphen, so the hyphen is real and is kept. The \b matters — without it the
# quantifier backtracks to a partial word ("o" of "of") and rejoins anyway.
_HYPHEN_LINEBREAK = re.compile(r"([a-z])-\n([a-z]+)\b(?!-)")

# A single newline inside a paragraph, as opposed to a blank-line break.
_SINGLE_NEWLINE = re.compile(r"(?<!\n)\n(?!\n)")

# A hyphen the rule above deliberately kept, still sitting at a line break.
# The hyphen is real, so close the gap rather than letting the newline become a
# space ("state-\nof-the-art" -> "state-of-the-art", not "state- of-the-art").
_COMPOUND_LINEBREAK = re.compile(r"-\n(?=[a-z])")

_MANY_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES_RUN = re.compile(r"[ \t]{2,}")
# Whitespace hugging a line break. PDFs pad lines out with spaces, so a visually
# blank line arrives as "   \n   \n" rather than "\n\n" — this has to run BEFORE
# single newlines are collapsed, or the paragraph break is destroyed first.
_EDGE_WHITESPACE = re.compile(r"[ \t]*\n[ \t]*")


# Postgres text columns cannot store NUL (0x00) — an insert containing one is
# rejected outright. PDFs produce them: a glyph that fails to resolve through a
# font's ToUnicode CMap is extracted as a raw C0 control byte. Real papers hit
# this on maths — LaTeX's \big( and \big) come out as 0x00 and 0x01 — so it is
# not an exotic case, it is a normal one for a scientific corpus.
#
# `raw_text` is persisted *unnormalized* on purpose (section detection needs the
# line structure normalization collapses), so it cannot rely on the stripping
# below and needs its own guard.
_NUL = "\x00"


def sanitize_for_storage(text: str) -> str:
    """Make text storable in a Postgres text column, preserving every offset.

    NUL is replaced with a space rather than deleted, and the substitution is
    **length-preserving by design**: `paper_sections.start_offset` and the
    chunk offsets are positions into this string, and a shortening substitution
    would slide every one of them out of alignment. A space is also the honest
    replacement — the byte stands in for a glyph that failed to decode, and we
    do not know which one it was, so preserving the token boundary is the most
    that can be claimed. Guessing "(" would be inventing content.
    """
    return text.replace(_NUL, " ")


def _strip_control_chars(text: str) -> str:
    # Keep newlines and tabs; drop other control/format codepoints, which
    # appear in PDFs as extraction noise.
    return "".join(
        ch
        for ch in text
        if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf")
    )


def normalize_page_text(raw: str) -> str:
    """Normalize one page of extracted text.

    Order matters: de-hyphenate before collapsing newlines, or the line break
    that marks the split is gone before it can be used.
    """
    if not raw:
        return ""

    text = unicodedata.normalize("NFKC", raw)

    for ligature, replacement in LIGATURES.items():
        text = text.replace(ligature, replacement)

    text = _ZERO_WIDTH.sub("", text)
    text = _ODD_SPACES.sub(" ", text)
    text = _strip_control_chars(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Rejoin words broken across a line break, then close up genuine compounds
    # that merely happened to break at their hyphen.
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
    text = _COMPOUND_LINEBREAK.sub("-", text)

    # Trim whitespace around every line break first, so that lines which are
    # visually blank (but padded with spaces) become real blank lines and are
    # recognisable as paragraph breaks below.
    text = _EDGE_WHITESPACE.sub("\n", text)

    # Within a paragraph, a newline is just wrapping — make it a space. Blank
    # lines (paragraph breaks) are preserved by the negative lookarounds.
    text = _SINGLE_NEWLINE.sub(" ", text)

    text = _SPACES_RUN.sub(" ", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)

    return text.strip()
