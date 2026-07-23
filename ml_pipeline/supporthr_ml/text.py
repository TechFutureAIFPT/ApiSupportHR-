from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


_TECHNICAL_TOKENS = {
    "c#": " csharp ",
    "c++": " cpp ",
    ".net": " dotnet ",
    "node.js": " nodejs ",
    "react.js": " reactjs ",
    "vue.js": " vuejs ",
    "next.js": " nextjs ",
}


def normalize_document_text(value: Any) -> str:
    """Normalize transport noise while preserving Vietnamese and technical syntax."""
    text = html.unescape(str(value or "")).replace("\x00", " ")
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def normalize_for_model(value: Any) -> str:
    """Match the classifier runtime preprocessing contract."""
    text = normalize_document_text(value).lower()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def canonical_text_for_hash(value: Any) -> str:
    text = normalize_document_text(value).casefold()
    for source, target in _TECHNICAL_TOKENS.items():
        text = text.replace(source, target)
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def normalized_lookup(value: Any) -> str:
    text = unicodedata.normalize("NFD", normalize_document_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").casefold()
    return re.sub(r"[^a-z0-9+#.]+", " ", text).strip()
