"""
Environment fingerprint — which interpreter, platform and package versions a
run executed under. Stdlib only (``importlib.metadata``, ``platform``).

This records the environment of the *running* process. It is not a lockfile;
two environments with the same fingerprint may still differ in transitive
dependencies that were not named. Name the distributions that matter.
"""
from __future__ import annotations

import platform
import sys
from typing import Any, Dict, Iterable, Tuple

from aihydro_core.records.canonical import digest

try:  # Python 3.8+
    from importlib import metadata as _metadata
except ImportError:  # pragma: no cover
    _metadata = None  # type: ignore[assignment]


def _dist_version(name: str):
    if _metadata is None:  # pragma: no cover
        return None
    try:
        return _metadata.version(name)
    except Exception:
        return None


def environment_fingerprint(distributions: Iterable[str] = ()) -> Tuple[Dict[str, Any], str]:
    """Return ``(fingerprint, env_digest)`` for the current process.

    ``distributions`` are distribution names (e.g. ``"aihydro-core"``,
    ``"numpy"``); missing ones are recorded as ``None`` rather than omitted, so
    "not installed" is distinguishable from "not asked".
    """
    fingerprint: Dict[str, Any] = {
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "platform": platform.system(),
        "machine": platform.machine(),
        "distributions": {name: _dist_version(name) for name in sorted(set(distributions))},
    }
    return fingerprint, digest(fingerprint)
