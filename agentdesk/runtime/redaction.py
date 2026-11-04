"""Redact PII from free text before any model sees it.

Field-name redaction in tracing.py covers structured data. Customers also type
PII into the chat box, so the planner and reply writers receive this redacted
copy of the message instead of the raw text.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")
_STREET = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way|Court|Ct|Place|Pl)\b\.?"
)


def redact_free_text(text: str) -> str:
    """Replace emails, phone numbers and street addresses with placeholders."""
    text = _EMAIL.sub("[EMAIL]", text)
    text = _STREET.sub("[ADDRESS]", text)
    return _PHONE.sub("[PHONE]", text)
