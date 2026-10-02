"""
Canonical encoding and digests for scientific records (canonicalization
``aihydro.c14n/1``).

One deterministic byte encoding for any record payload, so the same content
always produces the same ``sha256:<64 hex>`` digest regardless of key order,
NumPy versus Python scalars, or process.

Unlike ``primitives.hashing.content_hash`` this encoder is **strict**: a value
it does not know how to encode raises :class:`UnencodableError` instead of
falling back to ``str(value)``. A ``str()`` fallback silently aliases distinct
objects whose repr is abbreviated (large arrays, DataFrames), which is exactly
the failure a provenance digest must not have. Callers that need a best-effort
digest use :func:`digest_or_error` and record the error.

Encoding rules (stable within ``aihydro.c14n/1``):

- dict with ``str`` (or ``int``, stringified) keys → JSON object, keys sorted.
  A key collision after stringification raises. A dict whose keys start with
  ``$`` is wrapped as ``{"$map": {...}}`` so user data can never imitate a tag.
- list / tuple → JSON array.
- ``None``, ``bool``, ``int``, ``str`` → themselves; finite ``float`` → itself.
- non-finite float → ``{"$float": "nan" | "inf" | "-inf"}``.
- NumPy-like arrays (duck-typed: ``dtype``, ``shape``, ``tobytes``; never
  imported) → ``{"$ndarray": <base64 C-order bytes>, "dtype": <dtype.str>,
  "shape": [...]}``; object arrays are encoded element-wise; 0-d arrays and
  NumPy scalars become the equivalent Python scalar.
- ``datetime`` / ``date`` / ``time`` → ``{"$datetime" | "$date" | "$time": iso}``.
- ``bytes`` / ``bytearray`` → ``{"$bytes": <base64>}``.
- ``Decimal`` → ``{"$decimal": str}``; ``Enum`` → its ``value`` (encoded).
- ``set`` / ``frozenset`` → ``{"$set": [...]}`` sorted by canonical bytes.
- dataclass instances → their field dict.
- anything else → :class:`UnencodableError`.
"""
from __future__ import annotations

import base64
import dataclasses
import datetime as _dt
import decimal
import enum
import hashlib
import json
import math
from typing import Any, Optional, Tuple

CANONICALIZATION = "aihydro.c14n/1"
DIGEST_PREFIX = "sha256:"

_TAG_KEYS = ("$float", "$ndarray", "$ndarray_object", "$datetime", "$date", "$time",
             "$bytes", "$decimal", "$set", "$map")


class UnencodableError(TypeError):
    """Raised when a value has no canonical encoding under ``aihydro.c14n/1``."""


def _is_array_like(value: Any) -> bool:
    return (
        hasattr(value, "dtype")
        and hasattr(value, "shape")
        and hasattr(value, "tobytes")
        and not isinstance(value, (bytes, bytearray, str))
    )


def _encode(value: Any, _path: str = "$") -> Any:
    # Order matters: bool before int, Enum before its mixin base (str/int).
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, enum.Enum):
        return _encode(value.value, _path)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"$float": "nan"}
        if math.isinf(value):
            return {"$float": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if isinstance(key, bool) or not isinstance(key, (str, int)):
                raise UnencodableError(
                    f"{_path}: dict key {key!r} of type {type(key).__name__} has no canonical form"
                )
            skey = key if isinstance(key, str) else str(key)
            if skey in out:
                raise UnencodableError(f"{_path}: dict keys collide after stringification: {skey!r}")
            out[skey] = _encode(item, f"{_path}.{skey}")
        if any(k.startswith("$") for k in out):
            return {"$map": out}
        return out
    if isinstance(value, (list, tuple)):
        return [_encode(item, f"{_path}[{i}]") for i, item in enumerate(value)]
    if _is_array_like(value):
        shape = tuple(int(n) for n in value.shape)
        if shape == () and hasattr(value, "item"):
            return _encode(value.item(), _path)
        dtype = value.dtype
        if getattr(dtype, "hasobject", False):
            return {"$ndarray_object": _encode(value.tolist(), _path), "shape": list(shape)}
        return {
            "$ndarray": base64.b64encode(value.tobytes()).decode("ascii"),
            "dtype": getattr(dtype, "str", str(dtype)),
            "shape": list(shape),
        }
    if hasattr(value, "dtype") and hasattr(value, "item") and not hasattr(value, "__len__"):
        # NumPy scalar types that do not expose tobytes()/shape consistently.
        return _encode(value.item(), _path)
    if isinstance(value, _dt.datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, _dt.date):
        return {"$date": value.isoformat()}
    if isinstance(value, _dt.time):
        return {"$time": value.isoformat()}
    if isinstance(value, (bytes, bytearray)):
        return {"$bytes": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, decimal.Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (set, frozenset)):
        items = [_encode(item, f"{_path}{{}}") for item in value]
        items.sort(key=_dumps)
        return {"$set": items}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _encode({f.name: getattr(value, f.name) for f in dataclasses.fields(value)}, _path)
    raise UnencodableError(
        f"{_path}: value of type {type(value).__module__}.{type(value).__qualname__} "
        f"has no canonical form under {CANONICALIZATION}"
    )


def _dumps(encoded: Any) -> str:
    return json.dumps(encoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_json(obj: Any) -> bytes:
    """Return the canonical UTF-8 JSON bytes of ``obj`` (raises UnencodableError)."""
    return _dumps(_encode(obj)).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    """``sha256:<64 hex>`` of raw bytes (e.g. a file's content)."""
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def digest(obj: Any) -> str:
    """``sha256:<64 hex>`` of the canonical encoding of ``obj``."""
    return digest_bytes(canonical_json(obj))


def digest_or_error(obj: Any) -> Tuple[Optional[str], Optional[str]]:
    """Best-effort digest for callers that must never raise.

    Returns ``(digest, None)`` on success or ``(None, error_code)`` where
    ``error_code`` is ``"unencodable: <reason>"``. Never falls back to a
    weaker encoding.
    """
    try:
        return digest(obj), None
    except UnencodableError as exc:
        return None, f"unencodable: {exc}"
    except (ValueError, RecursionError) as exc:  # e.g. circular references
        return None, f"unencodable: {type(exc).__name__}: {exc}"


def is_digest(value: Any) -> bool:
    """True if ``value`` is a well-formed ``sha256:<64 hex>`` digest string."""
    if not isinstance(value, str) or not value.startswith(DIGEST_PREFIX):
        return False
    hexpart = value[len(DIGEST_PREFIX):]
    return len(hexpart) == 64 and all(c in "0123456789abcdef" for c in hexpart)
