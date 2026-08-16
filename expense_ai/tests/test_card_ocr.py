"""Tests for the local /sync screenshot OCR parsing and its guards.

The OCR line lists below are the verbatim output RapidOCR produced for
three real Uzum Bank screenshots (captured while choosing an engine), with
only the card last-4 digits swapped for placeholders. So these pin the
behavior against real data rather than invented strings -- including the
engine's quirks, which is the point: the decimal separator comes back
inconsistently as "." or ",", thousands spaces are dropped entirely, and
the spacing and character used as the card separator both vary.

Everything here exercises pure functions, so the test suite doesn't need
the ONNX models or opencv installed -- the engine call itself lives behind
run_ocr_lines() and only runs in the OCR subprocess.
"""

from __future__ import annotations

from expense_ai.card_ocr import parse_ocr_lines, verify_read

EXPECTED_CARDS = frozenset({"1111", "2222", "3333", "4444"})

SCREENSHOT_1 = [
    "Uzum",
    "8068.32sum",
    "VISA",
    "1111.UzumCard",
    "Openaflexibledeposit",
    "Withdraw atany time",
    "5081.58sum",
    "2222·Agrobank",
    "323468.58sum",
    "3333.Aloqabank",
    "1034226.06sum",
    "4444-Kapitalbank",
]

SCREENSHOT_2 = [
    "UzUm",
    "868.32sum",
    "VISA",
    "1111·Uzum Card",
    "Open a flexible deposit",
    "Withdraw at any time",
    "1316,51sum",
    "H",
    "2222·Agrobank",
    "261556,58sum",
    "3333·Aloqabank",
    "1108036.06sum",
    "4444·Kapitalbank",
]

SCREENSHOT_3 = [
    "OzUm",
    "968.32sum",
    "VISA",
    "1111.UzumCard",
    "Openaflexibledeposit",
    "Withdraw atany time",
    "15181,58sum",
    "2222·Agrobank",
    "1484109.58sum",
    "3333·Aloqabank",
    "1054826.06sum",
    "4444.Kapitalbank",
]


def test_parses_every_amount_from_real_screenshots():
    assert parse_ocr_lines(SCREENSHOT_1).amounts == [8068.32, 5081.58, 323468.58, 1034226.06]
    assert parse_ocr_lines(SCREENSHOT_2).amounts == [868.32, 1316.51, 261556.58, 1108036.06]
    assert parse_ocr_lines(SCREENSHOT_3).amounts == [968.32, 15181.58, 1484109.58, 1054826.06]


def test_totals_match_hand_computed_sums():
    assert parse_ocr_lines(SCREENSHOT_1).total == 1_370_844.54
    assert parse_ocr_lines(SCREENSHOT_2).total == 1_371_777.47
    assert parse_ocr_lines(SCREENSHOT_3).total == 2_555_085.54


def test_finds_all_card_numbers():
    for lines in (SCREENSHOT_1, SCREENSHOT_2, SCREENSHOT_3):
        assert EXPECTED_CARDS.issubset(parse_ocr_lines(lines).cards)


def test_pairs_each_amount_with_its_card():
    assert parse_ocr_lines(SCREENSHOT_1).items == [
        ("1111", 8068.32),
        ("2222", 5081.58),
        ("3333", 323468.58),
        ("4444", 1034226.06),
    ]


def test_amount_digits_are_not_mistaken_for_a_card_number():
    """"8068.32sum" must not read as card "8068" -- only a separator
    followed by a bank *name* marks a card line."""
    assert parse_ocr_lines(["8068.32sum"]).cards == frozenset()


def test_promo_and_label_text_is_ignored():
    """Anchoring on the "sum" suffix is what makes running on the whole
    uncropped screenshot safe (verified: no false positives from the promo
    carousel)."""
    read = parse_ocr_lines(["Win prizes", "3% cashback on utilities", "5.000", "10.000", "QR: new opportunities"])
    assert read.amounts == []


def test_all_real_screenshots_pass_verification():
    for lines in (SCREENSHOT_1, SCREENSHOT_2, SCREENSHOT_3):
        assert verify_read(parse_ocr_lines(lines), EXPECTED_CARDS) is True


def test_abstains_when_a_card_line_was_dropped():
    """The dangerous failure mode: a whole card missed, silently
    undercounting the total. This is what killed the Tesseract option."""
    without_aloqabank = [line for line in SCREENSHOT_1 if line not in ("323468.58sum", "3333.Aloqabank")]
    read = parse_ocr_lines(without_aloqabank)
    assert read.amounts == [8068.32, 5081.58, 1034226.06]
    assert verify_read(read, EXPECTED_CARDS) is False


def test_abstains_when_an_extra_balance_appears():
    """An unattributable extra amount (a deposit, or a new card not in the
    configured list) means the total can't be trusted -- defer to the LLM."""
    with_deposit = [*SCREENSHOT_1, "500000.00sum", "1234·SomeDeposit"]
    assert verify_read(parse_ocr_lines(with_deposit), EXPECTED_CARDS) is False


def test_abstains_when_no_cards_are_configured():
    """Local OCR is opt-in: with no card list there's nothing to verify
    against, so it must never be trusted."""
    assert verify_read(parse_ocr_lines(SCREENSHOT_1), frozenset()) is False


def test_abstains_when_nothing_was_read():
    assert verify_read(parse_ocr_lines([]), EXPECTED_CARDS) is False


# Verbatim OCR output from a real /sync that failed in production, card
# digits swapped for placeholders. The Agrobank line has only ONE decimal
# digit -- the app drops a trailing zero -- which the original
# exactly-two-digits rule rejected, so /sync abstained on every attempt.
LIVE_SCREENSHOT = [
    "14:28-",
    "UzumBank",
    "Islomjon >",
    "Privilegesare",
    "3%cashback",
    "8 268,32 sum",
    "VISA",
    "1111·UzumCard",
    "Openaflexibledeposit",
    "Withdrawatanytime",
    "32 626,7 sum",
    "2222·Agrobank",
    "200 968,58 sum",
    "3333·Aloqabank",
    "2 248 566,06 sum",
    "4444·Kapitalbank",
    "All products",
    "Main",
]


def test_reads_an_amount_with_a_single_decimal_digit():
    """Regression: "32 626,7 sum" (trailing zero dropped by the app) used
    to be skipped, leaving 3 amounts for 4 cards -> permanent abstain."""
    read = parse_ocr_lines(LIVE_SCREENSHOT)
    assert read.amounts == [8268.32, 32626.7, 200968.58, 2248566.06]
    assert read.total == 2_490_429.66
    assert verify_read(read, EXPECTED_CARDS) is True


def test_amount_is_ignored_when_the_line_holds_more_than_the_amount():
    """Only a line that is *nothing but* an amount plus "sum" counts. This
    is what makes accepting 1-2 decimals safe: on a mangled number whose
    thousands space was misread as a comma, an unanchored match would take
    the tail and silently report 34,226.06 instead of 1,034,226.06."""
    assert parse_ocr_lines(["1,034226,06sum"]).amounts == []
    assert parse_ocr_lines(["total 1034226,06 sum today"]).amounts == []


def test_abstains_when_the_decimal_separator_is_missing():
    """A dropped separator would read 1034226.06 as 103422606 -- 100x too
    large. Requiring two decimals means that becomes an abstain (and an
    LLM call) instead of a corrupted balance."""
    read = parse_ocr_lines(["103422606sum", "4444·Kapitalbank"])
    assert read.amounts == []
    assert verify_read(read, EXPECTED_CARDS) is False
