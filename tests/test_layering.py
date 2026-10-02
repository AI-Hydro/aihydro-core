"""
Layering contract test — core depends on NOBODY above it.

aihydro-core is the bottom robustness substrate. It must never import a domain
package (``ai_hydro``) or a sibling data package (``aihydro_data``). If it did,
core could rot whenever those packages change, and the three-layer architecture
would have a backward edge.

This test parses every source file in ``aihydro_core`` with the ``ast`` module
and asserts no forbidden import appears — including lazy imports inside
functions, which a top-level ``grep`` of import statements could miss but a
plain text scan would over-report (docstrings). Parsing the AST is exact.

It runs offline with zero extra dependencies, so the boundary is enforced on
every CI run. ``import-linter`` (configured in pyproject.toml) provides the same
guarantee for anyone who installs it; this test is the always-on floor.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CORE_ROOT = Path(__file__).resolve().parent.parent / "aihydro_core"
_FORBIDDEN_TOP_LEVEL = {"ai_hydro", "aihydro_data"}


def _python_files() -> list[Path]:
    return sorted(_CORE_ROOT.rglob("*.py"))


def _forbidden_imports(tree: ast.AST) -> list[str]:
    """Return forbidden module names imported anywhere in the AST."""
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_TOP_LEVEL:
                    bad.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # node.module is None for `from . import x` (always allowed)
            if node.module:
                top = node.module.split(".")[0]
                if top in _FORBIDDEN_TOP_LEVEL:
                    bad.append(node.module)
    return bad


def test_core_imports_no_domain_package():
    """No file under aihydro_core may import ai_hydro or aihydro_data."""
    offenders: dict[str, list[str]] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        bad = _forbidden_imports(tree)
        if bad:
            offenders[str(path.relative_to(_CORE_ROOT))] = bad

    assert not offenders, (
        "aihydro-core must depend on NOBODY above it, but found upward imports:\n"
        + "\n".join(f"  {f}: {mods}" for f, mods in offenders.items())
    )


def test_guard_covers_all_modules():
    """Sanity: the scan actually walked the core package (not zero files)."""
    files = _python_files()
    assert len(files) >= 8, f"Expected to scan the core package, found {len(files)} files"


# --------------------------------------------------------------------------- #
# aihydro_core.export — stdlib + aihydro_core.records only (slice 5, ADR-005).
# The crate verifier must be reproducible by anyone, so it may not grow a
# dependency beyond the standard library and the record contract it verifies.
# --------------------------------------------------------------------------- #
_STDLIB_FALLBACK = {
    "__future__", "argparse", "base64", "collections", "copy", "dataclasses", "datetime", "decimal",
    "enum", "hashlib", "json", "math", "os", "pathlib", "re", "sys", "typing", "urllib",
}


def _is_stdlib(top: str) -> bool:
    names = getattr(__import__("sys"), "stdlib_module_names", None)
    return top in (names if names is not None else _STDLIB_FALLBACK)


def _export_import_offenders(tree: ast.AST) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import: stays inside aihydro_core.export
                continue
            mods = [node.module or ""]
        else:
            continue
        for mod in mods:
            top = mod.split(".")[0]
            if top == "aihydro_core":
                if mod != "aihydro_core.records" and not mod.startswith("aihydro_core.records.") \
                        and not mod.startswith("aihydro_core.export"):
                    bad.append(mod)
            elif not _is_stdlib(top):
                bad.append(mod)
    return bad


def test_export_imports_only_stdlib_and_records():
    export_root = _CORE_ROOT / "export"
    files = sorted(export_root.rglob("*.py")) if export_root.exists() else []
    offenders = {}
    for path in files:
        bad = _export_import_offenders(ast.parse(path.read_text(), filename=str(path)))
        if bad:
            offenders[str(path.relative_to(_CORE_ROOT))] = bad
    assert not offenders, f"aihydro_core.export may import only stdlib and aihydro_core.records: {offenders}"


def test_records_bundle_and_entry_are_stdlib_only():
    for name in ("bundle.py", "entry.py"):
        path = _CORE_ROOT / "records" / name
        bad = [m for m in _export_import_offenders(ast.parse(path.read_text()))]
        assert not bad, f"records/{name} imports beyond stdlib/records: {bad}"


def test_export_layering_guard_detects_violations():
    tree = ast.parse("import numpy\nfrom aihydro_core.store import x\nimport json\nfrom aihydro_core.records import digest")
    assert _export_import_offenders(tree) == ["numpy", "aihydro_core.store"]
