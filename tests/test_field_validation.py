"""Tests for common.field_validation — the shared phone/email/zip/ICD-10
normalization and format checks used by managePatient and
managePatientDiagnoses (mutation-forms field-format validation fix)."""

from __future__ import annotations

from common.field_validation import check_email, check_icd10, check_phone, check_zip_code


def test_phone_with_parens_and_spaces_is_normalized_and_accepted() -> None:
    """The triggering bug: a user saying '(555) 014-7823' out loud must not
    fail just because of the punctuation the backing REST API's
    `[0-9+-]*` regex rejects."""
    cleaned, err = check_phone("(555) 014-7823")
    assert err is None
    assert cleaned == "555014-7823"


def test_phone_with_dots_is_normalized() -> None:
    cleaned, err = check_phone("555.014.7823")
    assert err is None
    assert cleaned == "5550147823"


def test_phone_with_letters_is_rejected() -> None:
    cleaned, err = check_phone("555-CALL-NOW")
    assert err is not None


def test_phone_too_short_is_rejected() -> None:
    cleaned, err = check_phone("555")
    assert err is not None


def test_phone_plus_prefix_is_accepted() -> None:
    cleaned, err = check_phone("+15550147823")
    assert err is None
    assert cleaned == "+15550147823"


def test_phone_empty_or_none_passes_through_untouched() -> None:
    assert check_phone(None) == (None, None)
    assert check_phone("") == ("", None)


def test_phone_international_with_dashes_is_accepted() -> None:
    """The 7-15 length bound is on digit count, not on the cleaned string's
    character count — '+' and '-' must not count against it."""
    cleaned, err = check_phone("+44-20-7946-0958")
    assert err is None
    assert cleaned == "+44-20-7946-0958"


def test_email_is_lowercased() -> None:
    cleaned, err = check_email("JOHN.DOE@EXAMPLE.COM")
    assert err is None
    assert cleaned == "john.doe@example.com"


def test_email_malformed_is_rejected() -> None:
    cleaned, err = check_email("not-an-email")
    assert err is not None


def test_email_with_subdomain_is_accepted() -> None:
    cleaned, err = check_email("jo@cs.stanford.edu")
    assert err is None
    assert cleaned == "jo@cs.stanford.edu"


def test_email_with_empty_domain_label_is_rejected() -> None:
    cleaned, err = check_email("a@.com")
    assert err is not None


def test_zip_code_five_digit_is_accepted() -> None:
    cleaned, err = check_zip_code("90210")
    assert err is None
    assert cleaned == "90210"


def test_zip_plus4_is_accepted() -> None:
    cleaned, err = check_zip_code("90210-1234")
    assert err is None


def test_zip_wrong_length_is_rejected() -> None:
    cleaned, err = check_zip_code("9021")
    assert err is not None


def test_icd10_valid_code_is_uppercased() -> None:
    cleaned, err = check_icd10("l23.9")
    assert err is None
    assert cleaned == "L23.9"


def test_icd10_without_decimal_is_accepted() -> None:
    cleaned, err = check_icd10("L23")
    assert err is None


def test_icd10_malformed_code_is_rejected() -> None:
    cleaned, err = check_icd10("blood pressure high")
    assert err is not None


def test_icd10_seventh_character_extension_is_accepted() -> None:
    """Injury/laterality codes carry an alphanumeric 7th character (e.g. the
    'A' = initial encounter in S72.001A), not just digits after the decimal."""
    cleaned, err = check_icd10("s72.001a")
    assert err is None
    assert cleaned == "S72.001A"


def test_icd10_without_dot_is_accepted() -> None:
    """Undotted ICD-10 codes (e.g. from claims/billing exports) are common
    and must not be rejected just because the '.' was left out."""
    cleaned, err = check_icd10("l239")
    assert err is None
    assert cleaned == "L239"


def test_zip_code_not_format_checked_for_non_us_country() -> None:
    cleaned, err = check_zip_code("K1A 0B1", country="CA")
    assert err is None
    assert cleaned == "K1A 0B1"


def test_zip_code_still_enforced_for_us_country() -> None:
    cleaned, err = check_zip_code("9021", country="US")
    assert err is not None


def test_zip_code_defaults_to_us_enforcement_when_country_omitted() -> None:
    cleaned, err = check_zip_code("9021")
    assert err is not None
