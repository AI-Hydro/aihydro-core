"""Optional: run the external ``rocrate-validator`` on the golden crate.

Set ``AIHYDRO_ROCRATE_VALIDATOR`` to the binary (for example in a scratch
venv with ``roc-validator`` 0.12.1). Skipped otherwise; never installs anything.
The ``process-run-crate`` profile of 0.12.1 encodes version 0.5 rules (extends
RO-Crate 1.1), so its descriptor ``conformsTo`` REQUIRED failure is the known
0.5/0.6 version mismatch and is not asserted away here.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

BIN = os.environ.get("AIHYDRO_ROCRATE_VALIDATOR")
GOLDEN = Path(__file__).resolve().parent / "data" / "rocrate" / "capsule"
pytestmark = pytest.mark.skipif(not BIN or not Path(BIN).exists(), reason="AIHYDRO_ROCRATE_VALIDATOR not set")


def _run(profile, tmp_path):
    out = tmp_path / f"{profile}.json"
    subprocess.run([BIN, "validate", "-p", profile, "-l", "recommended", "--no-paging", "--output-format", "json",
                    "--output-file", str(out), str(GOLDEN)], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    return json.loads(out.read_text())["issues"]


def test_ro_crate_1_3_has_no_required_issues(tmp_path):
    issues = _run("ro-crate-1.3", tmp_path)
    required = [(i["check"]["identifier"], i["message"][:100]) for i in issues if i["severity"] == "REQUIRED"]
    assert required == []


def test_process_run_crate_only_known_version_mismatch(tmp_path):
    issues = _run("process-run-crate", tmp_path)
    required = {i["check"]["identifier"] for i in issues if i["severity"] == "REQUIRED"}
    assert required <= {"ro-crate-1.1_5.3"}          # descriptor must conformTo RO-Crate 1.1 (0.5 rules vs 0.6/1.3)
