"""
Generic body binding ``aihydro.entry/1``.

Some sealed records live inside a larger JSON object (a *row*) that also holds
a body the record does not seal: tools' run-log rows hold ``{"record": {...},
"evidence": {...}, ...}``. The writer binds the body to the seal by storing
``digest(row minus the key "record")`` in the sealed record
(``extra.entry_digest``). This module names that rule so any package can
verify a body without learning the row layout.

``entry_digest(obj)`` = :func:`aihydro_core.records.canonical.digest` of a
shallow copy of ``obj`` without its top-level ``"record"`` key. An object with
no ``record`` key is digested whole, so the same binding also covers plain
bodies such as a session's working-view claim.

Golden vectors in ``tests/data/entry_vectors.json`` pin the expected digests
for a future stdlib mirror (``replay.py``).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from aihydro_core.records.canonical import digest

ENTRY_BINDING = "aihydro.entry/1"
ENTRY_EXCLUDED_KEY = "record"


def entry_digest(obj: Mapping[str, Any]) -> str:
    """``sha256:<64 hex>`` of ``obj`` minus its ``record`` key (``aihydro.entry/1``)."""
    if not isinstance(obj, Mapping):
        raise TypeError("entry_digest needs a mapping")
    return digest({k: v for k, v in obj.items() if k != ENTRY_EXCLUDED_KEY})


def make_binding(obj: Mapping[str, Any]) -> dict:
    """The ``binding`` value a Bundle ``records[]`` entry carries for ``obj``."""
    return {"scheme": ENTRY_BINDING, "digest": entry_digest(obj)}


def verify_binding(obj: Any, binding: Optional[Mapping[str, Any]]) -> bool:
    """True iff ``binding`` names ``aihydro.entry/1`` and matches ``obj`` now."""
    if not isinstance(obj, Mapping) or not isinstance(binding, Mapping):
        return False
    if binding.get("scheme") != ENTRY_BINDING:
        return False
    try:
        return entry_digest(obj) == binding.get("digest")
    except Exception:
        return False
