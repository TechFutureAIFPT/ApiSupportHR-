from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from .contracts import PII_REDACTION_VERSION
from .text import normalize_document_text


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]
    remaining_types: list[str]
    version: str = PII_REDACTION_VERSION

    @property
    def safe_for_release(self) -> bool:
        return not self.remaining_types


_PATTERNS: list[tuple[str, Pattern[str], str]] = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[EMAIL]"),
    (
        "phone",
        re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)"),
        "[PHONE]",
    ),
    (
        "url",
        re.compile(r"\b(?:https?://|www\.)\S+|\b(?:linkedin|github)\.com/\S+", re.I),
        "[URL]",
    ),
    (
        "date_of_birth",
        re.compile(
            r"\b(?:date\s+of\s+birth|dob|ng[aà]y\s+sinh|n[aă]m\s+sinh)\s*[:\-]?\s*"
            r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4})",
            re.I,
        ),
        "[DATE_OF_BIRTH]",
    ),
    (
        "identifier",
        re.compile(
            r"\b(?:cccd|cmnd|passport|identity\s*(?:card|number)|id\s*number)"
            r"\s*[:#\-]?\s*[A-Z0-9][A-Z0-9.-]{5,}\b",
            re.I,
        ),
        "[IDENTIFIER]",
    ),
    (
        "address",
        re.compile(
            r"(?im)^(?:address|home\s+address|current\s+address|địa\s+chỉ|dia\s+chi)"
            r"\s*[:\-]\s*(?=[^\n]*[\wÀ-ỹ])[^\n]{3,180}$"
        ),
        "Address: [ADDRESS]",
    ),
    (
        "name",
        re.compile(
            r"(?im)^(?:full\s*name|name|candidate\s*name|họ\s*tên|ho\s*ten)"
            r"\s*[:\-]\s*(?=[^\n]*[\wÀ-ỹ])[^\n]{2,100}$"
        ),
        "Name: [NAME]",
    ),
    (
        "social_handle",
        re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{2,31}\b"),
        "[SOCIAL_HANDLE]",
    ),
]


def _redact_probable_header_name(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    if len(lines) < 2:
        return text, 0
    contact_window = "\n".join(lines[:5])
    if not re.search(r"@|(?:\+?\d[\d\s().-]{7,}\d)|linkedin|github", contact_window, re.I):
        return text, 0
    first = lines[0].strip()
    words = first.split()
    if not 2 <= len(words) <= 6 or len(first) > 80:
        return text, 0
    if any(char.isdigit() for char in first):
        return text, 0
    if not all(re.fullmatch(r"[\wÀ-ỹ'’-]+", word, re.UNICODE) for word in words):
        return text, 0
    lines[0] = "[NAME]"
    return "\n".join(lines), 1


def detect_pii_types(value: str) -> list[str]:
    text = re.sub(
        r"\[(?:EMAIL|PHONE|URL|DATE_OF_BIRTH|IDENTIFIER|ADDRESS|NAME|SOCIAL_HANDLE)\]",
        "",
        str(value or ""),
    )
    detected = {
        name
        for name, pattern, _ in _PATTERNS
        if name not in {"name", "address"} and pattern.search(text)
    }
    for line in text.splitlines():
        if re.match(
            r"(?i)^\s*(?:full\s*name|name|candidate\s*name|họ\s*tên|ho\s*ten)\s*[:\-]",
            line,
        ):
            remainder = re.split(r"[:\-]", line, maxsplit=1)[-1].strip()
            if re.search(r"[\wÀ-ỹ]", remainder):
                detected.add("name")
        if re.match(
            r"(?i)^\s*(?:address|home\s+address|current\s+address|địa\s+chỉ|dia\s+chi)\s*[:\-]",
            line,
        ):
            remainder = re.split(r"[:\-]", line, maxsplit=1)[-1].strip()
            if re.search(r"[\wÀ-ỹ]", remainder):
                detected.add("address")
    return sorted(detected)


def redact_pii(value: str) -> RedactionResult:
    text = normalize_document_text(value)
    counts: dict[str, int] = {}
    text, header_count = _redact_probable_header_name(text)
    if header_count:
        counts["name"] = header_count
    for name, pattern, replacement in _PATTERNS:
        text, count = pattern.subn(replacement, text)
        if count:
            counts[name] = counts.get(name, 0) + count
    text = normalize_document_text(text)
    return RedactionResult(
        text=text,
        counts=dict(sorted(counts.items())),
        remaining_types=detect_pii_types(text),
    )
