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
from typing import Optional, Tuple

PHONE_PATTERN = re.compile(r"^[0-9+-]{7,15}$")
EMAIL_PATTERN = re.compile(r"^[\w]([\w\-.+']*)@([\w-]*)(\.[a-zA-Z]{2,22}(\.[a-zA-Z]{2}){0,2})$")
ZIP_PATTERN = re.compile(r"^\d{5}(-\d{4})?$")
ICD10_PATTERN = re.compile(r"^[A-Za-z]\d{2}(\.[A-Za-z0-9]{1,4})?$")


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
    if not PHONE_PATTERN.match(cleaned):
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
    if country and country.strip().upper() != "US":
        return cleaned, None
    if not ZIP_PATTERN.match(cleaned):
        return cleaned, "must be a 5-digit ZIP or ZIP+4 (#####-####)"
    return cleaned, None


def check_icd10(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return value, None
    cleaned = value.strip().upper()
    if not ICD10_PATTERN.match(cleaned):
        return cleaned, "must be ICD-10 format: one letter, two digits, optional '.' + 1-4 digits (e.g. L23.9)"
    return cleaned, None
