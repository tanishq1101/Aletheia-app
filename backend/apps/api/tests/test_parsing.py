import pytest

from app.services.parsing import PyMuPDFParser, detect_sections
from app.services.providers import ParsedPage, ParserError
from tests.fixtures import (
    build_corrupt_pdf,
    build_encrypted_pdf,
    build_pdf,
    build_single_page_pdf,
)


@pytest.fixture(scope="module")
def parsed():
    return PyMuPDFParser().parse(data=build_pdf())


def test_page_boundaries_are_preserved(parsed):
    assert parsed.metadata.page_count == 3
    assert len(parsed.pages) == 3
    assert [p.page_number for p in parsed.pages] == [1, 2, 3]


def test_text_ordering_is_preserved(parsed):
    page_one = parsed.pages[0].cleaned_text
    # Content must appear in the order it was laid out.
    assert page_one.index("Abstract") < page_one.index("1 Introduction")
    assert page_one.index("Deeper neural networks") < page_one.index("1 Introduction")

    # Content stays on the page it was written to.
    assert "2 Related Work" in parsed.pages[1].cleaned_text
    assert "2 Related Work" not in parsed.pages[0].cleaned_text
    assert "5 Conclusion" in parsed.pages[2].cleaned_text


def test_metadata_is_extracted(parsed):
    assert parsed.metadata.title == "Deep Residual Learning for Image Recognition"
    assert parsed.metadata.authors == [
        "Kaiming He",
        "Xiangyu Zhang",
        "Shaoqing Ren",
    ]
    assert parsed.metadata.abstract is not None
    assert "Deeper neural networks are more difficult to train" in (
        parsed.metadata.abstract
    )
    # The abstract must stop before the next section.
    assert "1 Introduction" not in parsed.metadata.abstract


def test_normalization_is_applied_to_page_text(parsed):
    # "break-\nthroughs" in the source must be rejoined.
    assert "breakthroughs" in parsed.pages[0].cleaned_text
    assert "break-" not in parsed.pages[0].cleaned_text
    # Raw text is kept unmodified alongside it.
    assert "break-" in parsed.pages[0].raw_text


def test_sections_are_detected_in_order(parsed):
    titles = [s.title for s in parsed.sections]
    assert titles == [
        "Abstract",
        "1 Introduction",
        "2 Related Work",
        "3 Methods",
        "3.1 Identity Mapping by Shortcuts",
        "4 Experiments",
        "5 Conclusion",
        "References",
    ]
    assert [s.section_index for s in parsed.sections] == list(range(len(titles)))


def test_section_nesting_level_and_page(parsed):
    by_title = {s.title: s for s in parsed.sections}
    assert by_title["3 Methods"].level == 1
    assert by_title["3.1 Identity Mapping by Shortcuts"].level == 2
    assert by_title["1 Introduction"].start_page == 1
    assert by_title["3 Methods"].start_page == 2
    assert by_title["4 Experiments"].start_page == 3


def test_section_offsets_point_into_cleaned_text(parsed):
    for section in parsed.sections:
        if section.start_offset is None:
            continue
        page = parsed.pages[section.start_page - 1]
        assert page.cleaned_text.startswith(section.title, section.start_offset)


def test_running_headers_are_not_repeated_sections():
    # The same heading on every page is a running header, not three sections.
    data = build_pdf([["Introduction", "body one"]] * 3, title=None, author=None)
    sections = PyMuPDFParser().parse(data=data).sections
    assert [s.title for s in sections] == ["Introduction"]


def test_prose_is_not_mistaken_for_a_heading():
    lines = [["We evaluate 3 models, as described below.", "1. First we do this."]]
    sections = PyMuPDFParser().parse(data=build_pdf(lines, title=None, author=None)).sections
    assert sections == []


def test_detect_sections_operates_on_raw_not_cleaned_text():
    # Guards the ordering bug this was written against: normalization collapses
    # the newlines that make a heading identifiable, so detection must use raw.
    page = ParsedPage(
        page_number=1,
        raw_text="1 Introduction\nSome body text follows here.",
        cleaned_text="1 Introduction Some body text follows here.",
    )
    assert [s.title for s in detect_sections([page])] == ["1 Introduction"]


def test_single_page_pdf_parses():
    parsed = PyMuPDFParser().parse(data=build_single_page_pdf("Just one page."))
    assert parsed.metadata.page_count == 1
    assert "Just one page." in parsed.pages[0].cleaned_text


def test_corrupt_pdf_raises_parser_error():
    with pytest.raises(ParserError):
        PyMuPDFParser().parse(data=build_corrupt_pdf())


def test_encrypted_pdf_raises_parser_error():
    with pytest.raises(ParserError) as excinfo:
        PyMuPDFParser().parse(data=build_encrypted_pdf())
    assert "password" in str(excinfo.value).lower()


def test_empty_bytes_raise_parser_error():
    with pytest.raises(ParserError):
        PyMuPDFParser().parse(data=b"")


def test_long_document_is_handled(parsed):
    # 60 pages should extract without special-casing.
    data = build_pdf([[f"Page {i} body text."] for i in range(1, 61)], title=None, author=None)
    result = PyMuPDFParser().parse(data=data)
    assert result.metadata.page_count == 60
    assert "Page 60 body text." in result.pages[59].cleaned_text
