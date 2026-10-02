"""
Deterministic hashing for parameter keys and content fingerprints.

A single implementation shared by all blocks (jobs, features, cache, aihydro-data).
This prevents the subtle drift that happens when each tool hashes its parameters
slightly differently — same params, different hash → cache miss.
"""
from __future__ import annotations

import hashlib
import json
import base64
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

    Tolerant of non-JSON-serialisable values. Numeric NumPy arrays are encoded
    with their full content, shape, and dtype instead of their abbreviated repr.
    Use for
    content-addressable artifact identity (detect whether fetched data changed)
    and for request-payload cache keys. Truncated to ``length`` hex chars.
    """
    def _encode(value: Any) -> Any:
        # Import no domain or numerical library into the stdlib-only core.
        # NumPy's default str() abbreviates large arrays, so unequal arrays
        # with the same displayed edge values previously shared a fingerprint.
        if type(value).__module__.startswith("numpy") and hasattr(value, "dtype"):
            dtype = value.dtype
            if getattr(dtype, "hasobject", False):
                return {"__ndarray_object__": value.tolist(),
                        "shape": tuple(value.shape), "dtype": str(dtype)}
            return {"__ndarray__": base64.b64encode(value.tobytes()).decode("ascii"),
                    "shape": tuple(value.shape), "dtype": str(dtype)}
        return str(value)

    try:
        s = json.dumps(obj, sort_keys=True, default=_encode)
    except Exception:
        s = str(obj)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]
