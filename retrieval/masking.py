"""Regex-based PII masking. No third-party NLP (Presidio) -- see CLAUDE.md."""
import re

_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL_MASKED>"),
    (re.compile(r"\b\d{16}\b"), "<CARD_MASKED>"),
    (re.compile(r"\b(?:key|token|password)=\S+", re.IGNORECASE), "<TOKEN_MASKED>"),
    (re.compile(r"\b[A-Za-z0-9]{20,}\b"), "<TOKEN_MASKED>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP_MASKED>"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "<PHONE_MASKED>"),
]


def mask_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def mask_log_entry(entry):
    entry.message = mask_text(entry.message)
    entry.raw = mask_text(entry.raw)
    return entry
