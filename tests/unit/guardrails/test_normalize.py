from hypothesis import given
from hypothesis import strategies as st

from guardrails.normalize import normalize


def test_plain_text_is_unchanged() -> None:
    view = normalize("hello world")
    assert view.text == "hello world"
    assert view.invisible_removed == 0
    assert view.original_span(0, 5) == (0, 5)


def test_empty_text() -> None:
    view = normalize("")
    assert view.text == ""
    assert view.starts == ()


def test_zero_width_characters_are_removed_and_counted() -> None:
    view = normalize("ig\u200bno\u200dre")
    assert view.text == "ignore"
    assert view.invisible_removed == 2


def test_span_covers_the_hidden_characters_in_the_original() -> None:
    original = "ig\u200bnore"
    view = normalize(original)
    start, end = view.original_span(0, 6)
    assert original[start:end] == original  # the whole thing, hidden char included
    assert view.original_span(2, 3) == (3, 4)  # the 'n' after the hidden character


def test_bidi_controls_are_removed() -> None:
    view = normalize("a\u202eb\u2066c")
    assert view.text == "abc"
    assert view.invisible_removed == 2


def test_fullwidth_letters_fold_to_ascii() -> None:
    # U+FF29 U+FF27 U+FF2E U+FF2F U+FF32 U+FF25 = full-width I G N O R E
    assert normalize("\uff29\uff27\uff2e\uff2f\uff32\uff25").text == "IGNORE"


def test_ligature_expands_and_both_letters_map_to_one_original_character() -> None:
    view = normalize("ﬁle")
    assert view.text == "file"
    assert view.original_span(0, 2) == (0, 1)  # "fi" came from the single ligature


def test_combining_accent_composes_into_one_character() -> None:
    view = normalize("e\u0301x")
    assert view.text == "\u00e9x"
    assert view.original_span(0, 1) == (0, 2)  # 'e' + accent
    assert view.original_span(1, 2) == (2, 3)  # 'x'


def test_bad_span_is_rejected() -> None:
    view = normalize("abc")
    for bad in [(-1, 2), (2, 2), (0, 9), (3, 4)]:
        try:
            view.original_span(*bad)
        except ValueError:
            continue
        raise AssertionError(f"span {bad} should have been rejected")


@given(st.text())
def test_normalizing_twice_changes_nothing(text: str) -> None:
    once = normalize(text)
    assert normalize(once.text).text == once.text


@given(st.text())
def test_offset_map_is_always_consistent(text: str) -> None:
    view = normalize(text)
    assert len(view.starts) == len(view.ends) == len(view.text)
    previous = 0
    for s, e in zip(view.starts, view.ends, strict=True):
        assert 0 <= s < e <= len(text)
        assert s >= previous  # the map never goes backwards
        previous = s
