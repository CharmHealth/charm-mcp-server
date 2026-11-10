"""Shared format validation/normalization for MCP tool inputs.

The regexes here mirror the backing charmEHR REST API's own validation
(`security-*.xml` / `RegexDefinition.properties`, per the mutation-forms
format-validation probe) — they are not new rules, just the same ones
enforced one layer earlier. The REST API itself is strict about punctuation
(e.g. phone is `[0-9+-]*` — no spaces or parens), which would otherwise
reject the most natural phrasing a user says out loud, e.g. "(555) 014-7823".
So each `normalize_*` strips the punctuation a user naturally includes but
the backend doesn't accept, and the matching `check_*` validates what's left
against the real backend pattern — rejecting only genuinely invalid content
(letters, wrong digit count), not formatting.
"""
import re
from typing import Any, Optional, Tuple

PHONE_PATTERN = re.compile(r"^[0-9+-]+$")
EMAIL_PATTERN = re.compile(r"^[\w]([\w\-.+']*)@([\w-]+\.)+[a-zA-Z]{2,22}$")
ZIP_PATTERN = re.compile(r"^\d{5}(-\d{4})?$")
ICD10_PATTERN = re.compile(r"^[A-Za-z]\d{2}(\.?[A-Za-z0-9]{1,4})?$")


def normalize_phone(value: str) -> str:
    """Strip whitespace, parens, and dots. Digits, +, and - survive."""
    return re.sub(r"[()\s.]", "", value)


def normalize_email(value: str) -> str:
    """Trim and lowercase — the backend's email match is case-insensitive."""
    return value.strip().lower()


def check_phone(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Returns (normalized_value, error_message). error_message is None when
    `value` is empty/None or passes validation after normalization."""
    if not value:
        return value, None
    cleaned = normalize_phone(value)
    digit_count = len(re.sub(r"[^0-9]", "", cleaned))
    if not PHONE_PATTERN.match(cleaned) or not (7 <= digit_count <= 15):
        return cleaned, "must be 7-15 digits, optionally with + or -"
    return cleaned, None


def check_email(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return value, None
    cleaned = normalize_email(value)
    if not EMAIL_PATTERN.match(cleaned):
        return cleaned, "must be a valid email address (local@domain.tld)"
    return cleaned, None


def check_zip_code(value: Optional[str], country: Optional[str] = "US") -> Tuple[Optional[str], Optional[str]]:
    """The backend's ZIP regex is US-only (5 digits or ZIP+4). For any other
    `country`, postal code formats vary too widely to validate here, so the
    value is passed through unchecked."""
    if not value:
        return value, None
    cleaned = value.strip()
    if country is not None and country.strip().upper() != "US":
        return cleaned, None
    if not ZIP_PATTERN.match(cleaned):
        return cleaned, "must be a 5-digit ZIP or ZIP+4 (#####-####)"
    return cleaned, None


def decode_boolean_status(value: Any) -> str:
    """Normalize a boolean-shaped status flag to "Active"/"Inactive".

    Several endpoints report status as a numeric/boolean flag rather than a
    word ("1"/"0", "true"/"false", or a real bool/int). A bare number with no
    other meaning is dropped — a number we cannot name is not a status; any
    other text passes through unchanged. Using `str(value)` rather than
    `str(value or "")` matters here: a real `False`/`0` is a valid status
    (Inactive), not an absent one, and the `or` form would coerce it to "".
    """
    raw = ("" if value is None else str(value)).strip()
    if raw in ("1", "true", "True"):
        return "Active"
    if raw in ("0", "false", "False"):
        return "Inactive"
    return "" if raw.isdigit() else raw


def check_icd10(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return value, None
    cleaned = value.strip().upper()
    if not ICD10_PATTERN.match(cleaned):
        return cleaned, "must be ICD-10 format: one letter, two digits, optionally followed by '.' and 1-4 alphanumeric characters (e.g. L23.9, S72.001A, or L239)"
    return cleaned, None
