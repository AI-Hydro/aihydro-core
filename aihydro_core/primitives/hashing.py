"""
Deterministic hashing for parameter keys and content fingerprints.

A single implementation shared by all blocks (jobs, features, cache, aihydro-data).
This prevents the subtle drift that happens when each tool hashes its parameters
slightly differently — same params, different hash → cache miss.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def param_hash(params: dict, *, length: int = 16) -> str:
    """
    Deterministic hex hash of a parameter dict.

    Always sorts keys, stringifies non-JSON-serialisable values, and produces
    the same output regardless of dict insertion order. Truncated to ``length``
    hex chars (default 16 = 64-bit) — collision probability negligible for
    tool-param cardinality. Callers that need a longer key (e.g. aihydro-data's
    request-payload cache filenames) pass ``length=24``.

    Use for cache keys: (product, feature_id, param_hash(params)) → result.
    """
    try:
        s = json.dumps(params, sort_keys=True, default=str)
    except Exception:
        s = str(sorted(params.items()))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]


def content_hash(obj: Any, *, length: int = 16) -> str:
    """
    Deterministic hex fingerprint of any serialisable object.

    Tolerant of non-JSON-serialisable values (falls back to str()). Use for
    content-addressable artifact identity (detect whether fetched data changed)
    and for request-payload cache keys. Truncated to ``length`` hex chars.
    """
    try:
        s = json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]
