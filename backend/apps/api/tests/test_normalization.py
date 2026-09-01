from app.services.normalization import (
    normalize_page_text,
    sanitize_for_storage,
)


def test_rejoins_hyphenated_line_breaks():
    assert normalize_page_text("represen-\ntation") == "representation"


def test_leaves_real_compounds_alone():
    # Not a hyphenation artefact — the hyphen belongs to the term.
    out = normalize_page_text("state-\nof-the-art results")
    assert "state-of-the-art" in out


def test_single_newlines_become_spaces_but_paragraphs_survive():
    out = normalize_page_text("first line\nsame paragraph\n\nnew paragraph")
    assert out == "first line same paragraph\n\nnew paragraph"


def test_whitespace_padded_blank_lines_still_break_paragraphs():
    """PDFs pad lines with spaces, so a 'blank' line is not actually empty.

    Sprint 3's paragraph-aware chunker depends on these breaks surviving.
    """
    raw = "First paragraph text.   \n   \nSecond paragraph text."
    assert normalize_page_text(raw) == "First paragraph text.\n\nSecond paragraph text."


def test_collapses_excess_blank_lines_and_spaces():
    assert normalize_page_text("a\n\n\n\nb") == "a\n\nb"
    assert normalize_page_text("too    many     spaces") == "too many spaces"


def test_expands_ligatures():
    assert normalize_page_text("eﬃcient classiﬁcation") == "efficient classification"


def test_strips_zero_width_and_control_characters():
    assert normalize_page_text("clean​text\x07here") == "cleantexthere"


def test_normalizes_odd_unicode_spaces():
    assert normalize_page_text("a b c") == "a b c"


def test_empty_input_is_safe():
    assert normalize_page_text("") == ""
    assert normalize_page_text("   \n\n  ") == ""


# --- NUL sanitization (found by the Sprint 6 corpus, not by review) ----------
# Four of the ten real arXiv papers failed to ingest with "PostgreSQL text
# fields cannot contain NUL (0x00) bytes". The generated fixture corpus could
# never have produced one.


def test_sanitize_removes_nul_bytes():
    assert "\x00" not in sanitize_for_storage("exp\x00d(z)q(x)\x01")


def test_sanitize_is_length_preserving():
    """The property that keeps section and chunk offsets valid.

    `paper_sections.start_offset` indexes into this string. A substitution that
    changed its length would slide every offset downstream of the NUL, and the
    damage would show up as citations pointing at the wrong section rather than
    as an error.
    """
    raw = "alpha\x00beta\x00\x00gamma"
    assert len(sanitize_for_storage(raw)) == len(raw)


def test_sanitize_preserves_offsets_of_later_text():
    raw = "intro\x00\n\n2 Methods\n\nbody"
    cleaned = sanitize_for_storage(raw)
    assert cleaned.index("2 Methods") == raw.index("2 Methods")


def test_sanitize_keeps_line_structure_intact():
    """raw_text is stored unnormalized because section detection needs its
    newlines. Sanitizing must not disturb them."""
    raw = "1 Introduction\n\nsome \x00 text\nwrapped"
    assert sanitize_for_storage(raw).count("\n") == raw.count("\n")


def test_sanitize_leaves_clean_text_untouched():
    text = "1 Introduction\n\nNothing to sanitize here.\n"
    assert sanitize_for_storage(text) == text


def test_nul_becomes_a_boundary_not_a_join():
    """The byte stands in for a glyph that failed to decode. Deleting it would
    glue two tokens together ("exp(d" -> "expd"); a space keeps them apart."""
    assert "expd" not in sanitize_for_storage("exp\x00d(z)")
