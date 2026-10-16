"""CLI: ``python -m aihydro_core.export.rocrate {validate,verify} DIR``.

Exit codes: ``validate`` 0 = no errors, 1 = errors. ``verify`` 0 = ok, 1 = failed, 3 = verified but partial
(privacy-withheld records or heads, or nothing but unsealed rows: ``--json`` gives ``status`` and
``partial_reasons``), so a consumer can reject partial-by-withholding by policy.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aihydro_core.export.rocrate",
                                 description="Validate or verify an exported AI-Hydro capsule crate.")
    ap.add_argument("command", choices=("validate", "verify"))
    ap.add_argument("directory")
    ap.add_argument("--json", action="store_true", help="print machine-readable results")
    args = ap.parse_args(argv)
    if args.command == "validate":
        from aihydro_core.export.rocrate_validate import errors, validate_crate
        findings = validate_crate(args.directory)
        bad = errors(findings)
        if args.json:
            print(json.dumps([f.to_dict() for f in findings], indent=2))
        else:
            for f in findings:
                print(f"{f.severity.upper():7} {f.rule:18} {f.entity or '-'}: {f.message}")
            print(f"validate: {'FAIL' if bad else 'OK'} ({len(bad)} errors, {len(findings) - len(bad)} warnings)")
        return 1 if bad else 0
    from aihydro_core.export.rocrate_verify import verify_crate
    res = verify_crate(args.directory)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        for f in res.failures:
            print(f"FAIL {f.rule:22} {f.entity or '-'}: {f.message}")
        for n in res.notes:
            print(f"NOTE {n}")
        label = {"ok": "OK", "failed": "FAIL", "ok_partial_withheld": "OK (PARTIAL: privacy-withheld)",
                 "ok_partial_unsealed": "OK (PARTIAL: unsealed rows only)"}[res.status]
        print(f"verify: {label} ({res.records_verified}/{res.records_total} records verified)")
        if res.ok:
            print("note: integrity is not origin; this does not show who produced the capsule.")
        if res.partial:
            print("note: partial result; exit code 3 lets a consumer reject this by policy.")
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
