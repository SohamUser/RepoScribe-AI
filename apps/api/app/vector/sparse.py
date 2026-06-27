from __future__ import annotations

import hashlib
import re
from collections import Counter

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]{1,63}")


class SparseVectorizer:
    def __init__(self, dimensions: int = 4096) -> None:
        self.dimensions = dimensions

    def encode(self, text: str) -> dict[str, list[float] | list[int]]:
        tokens = [token.lower() for token in TOKEN_PATTERN.findall(text)]
        counts = Counter(tokens)
        bucketed: dict[int, float] = {}

        for token, count in counts.items():
            index = self._hash_token(token)
            bucketed[index] = bucketed.get(index, 0.0) + float(count)

        indices = sorted(bucketed)
        values = [bucketed[index] for index in indices]
        return {
            "indices": indices,
            "values": values,
        }

    def _hash_token(self, token: str) -> int:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], byteorder="big", signed=False) % self.dimensions
