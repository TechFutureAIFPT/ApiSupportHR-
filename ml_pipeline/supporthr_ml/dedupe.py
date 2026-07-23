from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from itertools import combinations
from typing import Iterable

from .text import canonical_text_for_hash


def content_hash(value: str) -> str:
    return hashlib.sha256(canonical_text_for_hash(value).encode("utf-8")).hexdigest()


def _tokens(value: str) -> list[str]:
    return re.findall(r"[\w+#.]{2,}", canonical_text_for_hash(value), flags=re.UNICODE)


def simhash64(value: str) -> int:
    tokens = _tokens(value)
    shingles = ["\x1f".join(tokens[index:index + 3]) for index in range(max(1, len(tokens) - 2))]
    if not shingles:
        shingles = tokens or [""]
    weights = [0] * 64
    for shingle in shingles:
        hashed = int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if hashed & (1 << bit) else -1
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        canonical = min(left_root, right_root)
        other = right_root if canonical == left_root else left_root
        self.parent[other] = canonical


def assign_near_duplicate_groups(
    records: list[dict[str, object]],
    *,
    id_key: str = "documentId",
    text_key: str = "cleanText",
    max_hamming_distance: int = 3,
    max_bucket_size: int = 200,
) -> tuple[dict[str, str], int]:
    ids = [str(record[id_key]) for record in records]
    union = _UnionFind(ids)
    signatures = {
        str(record[id_key]): simhash64(str(record.get(text_key) or ""))
        for record in records
    }
    buckets: dict[tuple[int, int], list[str]] = defaultdict(list)
    for record_id, signature in signatures.items():
        for chunk in range(4):
            buckets[(chunk, (signature >> (chunk * 16)) & 0xFFFF)].append(record_id)

    checked: set[tuple[str, str]] = set()
    near_pairs = 0
    for bucket_ids in buckets.values():
        if len(bucket_ids) > max_bucket_size:
            continue
        for left, right in combinations(sorted(bucket_ids), 2):
            pair = (left, right)
            if pair in checked:
                continue
            checked.add(pair)
            if hamming_distance(signatures[left], signatures[right]) <= max_hamming_distance:
                union.union(left, right)
                near_pairs += 1

    return {record_id: union.find(record_id) for record_id in ids}, near_pairs
