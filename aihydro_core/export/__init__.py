"""
aihydro_core.export — Bundle -> RO-Crate projection, validator and verifier (slice 5, ADR-005).

Stdlib + ``aihydro_core.records`` only (enforced by ``tests/test_layering.py``).
Names are loaded lazily so ``python -m aihydro_core.export.rocrate`` runs the
module cleanly.
"""
from __future__ import annotations

_EXPORTS = {
    "to_rocrate": "rocrate", "dumps_crate": "rocrate", "write_crate": "rocrate",
    "scan_files": "rocrate", "load_inputs": "rocrate", "record_key": "rocrate",
    "write_manifest_sha256": "rocrate", "PROFILE_NS": "rocrate", "CRATE_FILE": "rocrate",
    "BAGIT_FILE": "rocrate", "INTEGRITY_NOTICE": "rocrate",
    "validate_crate": "rocrate_validate", "validate_graph": "rocrate_validate",
    "Finding": "rocrate_validate", "RULES": "rocrate_validate",
    "verify_crate": "rocrate_verify", "VerifyResult": "rocrate_verify",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    mod = _EXPORTS.get(name)
    if mod is None:
        raise AttributeError(f"module 'aihydro_core.export' has no attribute {name!r}")
    import importlib
    value = getattr(importlib.import_module(f"aihydro_core.export.{mod}"), name)
    globals()[name] = value
    return value
