"""
Canonical encoding and digests for scientific records (canonicalization
``aihydro.c14n/1``).

One deterministic byte encoding for any record payload, so the same content
always produces the same ``sha256:<64 hex>`` digest regardless of key order,
NumPy versus Python scalars, process, or **implementation language**.

``aihydro.c14n/1`` = (1) a *tagging* step that maps Python values onto plain
JSON values, then (2) serialisation with the JSON Canonicalization Scheme
(RFC 8785, "JCS"): ECMAScript number formatting, object members sorted by
UTF-16 code units, minimal string escaping, no whitespace, UTF-8 output.
Because step 2 is a published standard, a TypeScript or browser client can
verify digests with any JCS implementation once it applies the same tags; the
golden vectors in ``tests/data/c14n_vectors.json`` pin the expected bytes.

Unlike ``primitives.hashing.content_hash`` this encoder is **strict**: a value
it does not know how to encode raises :class:`UnencodableError` instead of
falling back to ``str(value)``. A ``str()`` fallback silently aliases distinct
objects whose repr is abbreviated (large arrays, DataFrames), which is exactly
the failure a provenance digest must not have. Callers that need a best-effort
digest use :func:`digest_or_error` and record the error.

Tagging rules (stable within ``aihydro.c14n/1``):

- dict with ``str`` (or ``int``, stringified) keys → JSON object. A key
  collision after stringification raises. A dict whose keys start with ``$``
  is wrapped as ``{"$map": {...}}`` so user data can never imitate a tag.
- list / tuple → JSON array.
- ``None``, ``bool``, ``str`` → themselves (strings must be valid Unicode).
- ``int`` with ``|i| <= 2**53`` → JSON number; larger → ``{"$int": "<decimal>"}``
  (JCS numbers are IEEE-754 doubles; big integers must not be rounded).
- finite ``float`` → JSON number (so ``1.0`` and ``1`` encode identically, as in
  JSON); non-finite → ``{"$float": "nan" | "inf" | "-inf"}``; ``-0.0`` → ``0``.
- NumPy-like arrays (duck-typed: ``dtype``, ``shape``, ``tobytes``; never
  imported) → ``{"$ndarray": <base64 C-order bytes>, "dtype": <dtype.str>,
  "shape": [...]}`` plus ``"descr"`` for structured dtypes; object arrays are
  encoded element-wise; 0-d arrays and NumPy scalars become the equivalent
  Python scalar.
- masked arrays (duck-typed: ``mask`` + ``filled``) →
  ``{"$masked": {"data": <array>, "mask": <bool array or bool>}}`` — the mask
  is never dropped, so a missing value cannot alias a present one.
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
import math
from typing import Any, Optional, Tuple

CANONICALIZATION = "aihydro.c14n/1"
DIGEST_PREFIX = "sha256:"
_MAX_SAFE_INT = 2 ** 53


class UnencodableError(TypeError):
    """Raised when a value has no canonical encoding under ``aihydro.c14n/1``."""


# --------------------------------------------------------------------- tagging
def _is_masked(value: Any) -> bool:
    return hasattr(value, "mask") and hasattr(value, "filled") and hasattr(value, "data")


def _is_array_like(value: Any) -> bool:
    return (
        hasattr(value, "dtype")
        and hasattr(value, "shape")
        and hasattr(value, "tobytes")
        and not isinstance(value, (bytes, bytearray, str))
    )


def _encode_array(value: Any, path: str) -> Any:
    shape = tuple(int(n) for n in value.shape)
    if shape == () and hasattr(value, "item"):
        return _encode(value.item(), path)
    dtype = value.dtype
    if getattr(dtype, "hasobject", False):
        return {"$ndarray_object": _encode(value.tolist(), path), "shape": list(shape)}
    out = {
        "$ndarray": base64.b64encode(value.tobytes()).decode("ascii"),
        "dtype": getattr(dtype, "str", str(dtype)),
        "shape": list(shape),
    }
    if getattr(dtype, "names", None):
        out["descr"] = _encode(dtype.descr, path)
    return out


def _encode(value: Any, _path: str = "$") -> Any:
    # Order matters: bool before int, Enum before its mixin base (str/int),
    # masked before plain arrays.
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, enum.Enum):
        return _encode(value.value, _path)
    if isinstance(value, int):
        if -_MAX_SAFE_INT <= value <= _MAX_SAFE_INT:
            return value
        return {"$int": str(int(value))}
    if isinstance(value, float):
        if math.isnan(value):
            return {"$float": "nan"}
        if math.isinf(value):
            return {"$float": "inf" if value > 0 else "-inf"}
        return float(value)
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
    if _is_masked(value) and _is_array_like(value):
        mask = value.mask
        mask_enc = _encode_array(mask, _path + ".mask") if _is_array_like(mask) else _encode(bool(mask), _path)
        return {"$masked": {"data": _encode(value.data, _path + ".data"), "mask": mask_enc}}
    if _is_array_like(value):
        return _encode_array(value, _path)
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
        items.sort(key=_serialize)
        return {"$set": items}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _encode({f.name: getattr(value, f.name) for f in dataclasses.fields(value)}, _path)
    raise UnencodableError(
        f"{_path}: value of type {type(value).__module__}.{type(value).__qualname__} "
        f"has no canonical form under {CANONICALIZATION}"
    )


# --------------------------------------------------------- RFC 8785 serialiser
def _es_number(x: float) -> str:
    """ECMAScript Number::toString for a finite double (RFC 8785 §3.2.2.3)."""
    if x == 0:
        return "0"  # also -0
    if x < 0:
        return "-" + _es_number(-x)
    # Python's repr is the shortest round-tripping decimal, as ECMAScript requires.
    sign, digit_tuple, exp = decimal.Decimal(repr(x)).as_tuple()
    digits = "".join(map(str, digit_tuple)).rstrip("0") or "0"
    k = len(digits)
    n = len(digit_tuple) + exp  # decimal point position: value = 0.digits × 10^n
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    e = n - 1
    exp_str = ("+" if e >= 0 else "-") + str(abs(e))
    if k == 1:
        return digits + "e" + exp_str
    return digits[0] + "." + digits[1:] + "e" + exp_str


_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _es_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _utf16_key(s: str) -> bytes:
    return s.encode("utf-16-be", "surrogatepass")


def _serialize(v: Any) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _es_number(v)
    if isinstance(v, str):
        return _es_string(v)
    if isinstance(v, list):
        return "[" + ",".join(_serialize(i) for i in v) + "]"
    if isinstance(v, dict):
        items = sorted(v.items(), key=lambda kv: _utf16_key(kv[0]))
        return "{" + ",".join(_es_string(k) + ":" + _serialize(val) for k, val in items) + "}"
    raise UnencodableError(f"internal: untagged value of type {type(v).__name__}")  # pragma: no cover


# ------------------------------------------------------------------- public API
def canonical_json(obj: Any) -> bytes:
    """Return the canonical UTF-8 bytes of ``obj`` (raises UnencodableError)."""
    text = _serialize(_encode(obj))
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogates are not valid Unicode
        raise UnencodableError(f"string is not valid Unicode: {exc}") from exc


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
