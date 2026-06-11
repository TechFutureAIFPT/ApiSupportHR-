from __future__ import annotations

import re
from typing import Any


_MOJIBAKE_PATTERN = re.compile(
    r"(?:\u00c2|\u00c3|\u00c4|\u00c6|\u00d0|\u00f0|\u00e1\u00ba|\u00e1\u00bb|\u00e2\u20ac|T\u00e1\u00bb|\ufffd)"
)
_DAMAGED_MOJIBAKE_PATTERN = re.compile(r"(?:\u00e1\u00ba\?|\u00e1\u00bb\?|\u00c3\?|\u00c4\?)")
_VIETNAMESE_MARK_PATTERN = re.compile(r"[\u00c0-\u1ef9\u0110\u0111]")
_COMMON_DAMAGED_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Ti\u00e1\u00ba(?:\u00bf|\?)p t\u00e1\u00bb(?:\u00a5|\u00a3|\?)c"), "Tiếp tục"),
    (re.compile(r"ti\u00e1\u00ba(?:\u00bf|\?)p t\u00e1\u00bb(?:\u00a5|\u00a3|\?)c"), "tiếp tục"),
    (re.compile(r"D\u00c3\u00b9ng th\u00e1\u00bb\u00ad mi\u00e1\u00bb\u2026n ph\u00c3\u00ad"), "Dùng thử miễn phí"),
    (re.compile(r"D\u00c3\u00b9ng th\u00e1\u00bb\u00ad"), "Dùng thử"),
    (re.compile(r"Nh\u00e1\u00ba\u00adn t\u00c6\u00b0 v\u00e1\u00ba\u00a5n"), "Nhận tư vấn"),
    (re.compile(r"T\u00e1\u00ba\u00a3i file"), "Tải file"),
    (re.compile(r"T\u00e1\u00ba\u00a3i l\u00c3\u00aan"), "Tải lên"),
    (re.compile(r"T\u00c3\u00a0i li\u00e1\u00bb\u2021u"), "Tài liệu"),
    (re.compile(r"M\u00e1\u00ba\u00abu JD"), "Mẫu JD"),
    (re.compile(r"Th\u00c6\u00b0 vi\u00e1\u00bb\u2021n CV"), "Thư viện CV"),
    (re.compile(r"Chu\u00e1\u00ba\u00a9n h\u00c3\u00b3a JD"), "Chuẩn hóa JD"),
    (re.compile(r"\u00c4\u0090ang t\u00e1\u00ba\u00a3i"), "Đang tải"),
    (re.compile(r"Ch\u00c6\u00b0a c\u00c3\u00b3"), "Chưa có"),
    (re.compile(r"Kh\u00c3\u00b4ng c\u00c3\u00b3"), "Không có"),
)


def _score_display_text(value: str) -> int:
    return (
        len(_MOJIBAKE_PATTERN.findall(value)) * -8
        + len(_VIETNAMESE_MARK_PATTERN.findall(value)) * 2
        - (20 if "\ufffd" in value else 0)
    )


def _decode_mojibake(value: str, encoding: str) -> str | None:
    try:
        return value.encode(encoding).decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None


def _repair_damaged_mojibake(value: str) -> str:
    for pattern, replacement in _COMMON_DAMAGED_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    return value


def normalize_display_text(value: Any) -> str:
    if value is None:
        return ""

    text = _repair_damaged_mojibake(str(value))
    for _ in range(4):
        if not _MOJIBAKE_PATTERN.search(text) and not _DAMAGED_MOJIBAKE_PATTERN.search(text):
            return text

        candidates = [
            candidate
            for candidate in (
                _decode_mojibake(text, "latin1"),
                _decode_mojibake(text, "cp1252"),
            )
            if candidate and "\ufffd" not in candidate
        ]
        if not candidates:
            return text

        decoded = max(candidates, key=_score_display_text)
        if _score_display_text(decoded) <= _score_display_text(text):
            return text
        text = _repair_damaged_mojibake(decoded)
    return text


def normalize_payload_text(payload: Any) -> Any:
    if isinstance(payload, str):
        return normalize_display_text(payload)

    if isinstance(payload, list):
        return [normalize_payload_text(item) for item in payload]

    if isinstance(payload, tuple):
        return tuple(normalize_payload_text(item) for item in payload)

    if isinstance(payload, dict):
        return {
            normalize_display_text(key): normalize_payload_text(value)
            for key, value in payload.items()
        }

    return payload
