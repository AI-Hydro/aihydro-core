"""Fault-matrix-3 core items: F11 (BagIt required), F12 (session view vs sealed head), F13 (partial outcome)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aihydro_core.export import verify_crate
from aihydro_core.records import make_binding
from tests.rocrate_fixture import CLAIM_ID, build_capsule
from tests.test_rocrate_adversary import _declare_withheld, _row_edit, _stub_of, _withhold_claim_rev
from tests.test_rocrate_verify import _regen, _reseal_bundle, _sync_objects

GOLDEN = Path(__file__).resolve().parent / "data" / "rocrate" / "capsule"


@pytest.fixture()
def cap(tmp_path):
    d = tmp_path / "c"
    shutil.copytree(GOLDEN, d)
    return d


def _cli(d, *a):
    return subprocess.run([sys.executable, "-m", "aihydro_core.export.rocrate", "verify", str(d), *a],
                          capture_output=True, text=True)


# ---------------------------------------------------------------------- F11
def test_f11_missing_bagit_manifest_fails(cap):
    (cap / "manifest-sha256.txt").unlink()
    res = verify_crate(cap)
    assert "VER-BAGIT" in res.rules and not res.ok
    assert any("missing" in f.message for f in res.failures if f.rule == "VER-BAGIT")
    assert _cli(cap).returncode == 1


# ---------------------------------------------------------------------- F12
def _edit_view(d, **fields):
    s = json.loads((d / "session.json").read_text())
    s["claims"][CLAIM_ID].update(fields)
    (d / "session.json").write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
    _reseal_bundle(d, lambda b: [r.update(binding=make_binding(s["claims"][CLAIM_ID]))
                                 for r in b.records if r["kind"] == "claim_view"])
    _sync_objects(d, {"session.json"})
    _regen(d)


@pytest.mark.parametrize("field,value", [("claim", "The BFI is 0.999."), ("status", "verified"),
                                         ("claim_type", "other"), ("confidence", "high"),
                                         ("confidence_rationale", "trust me"), ("limitations", ["none"])])
def test_f12_session_view_must_equal_sealed_head(cap, field, value):
    _edit_view(cap, **{field: value})
    res = verify_crate(cap)
    assert "VER-HEAD" in res.rules and not res.ok
    assert field in " ".join(f.message for f in res.failures if f.rule == "VER-HEAD")


def test_f12_unchanged_view_and_unprojected_fields_pass(cap):
    _edit_view(cap, extra_note="not projected by the revision")     # a field the revision does not carry
    assert verify_crate(cap).ok


def _withheld_head(cap):
    _withhold_claim_rev(cap, 2)                                       # real head is a stub; rev 1 is last readable
    _reseal_bundle(cap, lambda b: setattr(b, "coverage", {
        "records_verified": 11, "records_total": 12, "unverifiable_ids": [f"{CLAIM_ID}@2"],
        "withheld_ids": [f"{CLAIM_ID}@2"]}))


def test_f12_withheld_head_enumerated_difference_is_a_note_and_partial(cap):
    _withheld_head(cap)
    _edit_view(cap, status="verified")                                 # may have changed in the withheld revision
    res = verify_crate(cap)
    assert res.ok and res.partial and res.status == "ok_partial_withheld"
    assert any("unverifiable" in n and "status" in n for n in res.notes)


def test_f12_withheld_head_string_difference_fails(cap):
    _withheld_head(cap)
    _edit_view(cap, claim="An edited sentence that hides behind a stub head.")
    assert "VER-HEAD" in verify_crate(cap).rules


def test_f12_marker_must_start_its_token_and_text_must_otherwise_match(cap):
    _withheld_head(cap)
    head_text = "The baseflow index is 0.585 (90% CI 0.571-0.599)."
    _edit_view(cap, claim=head_text + " <abs>/data/x.csv")                 # token STARTS with the marker: scrubbed path
    res = verify_crate(cap)
    assert res.ok and res.partial
    _edit_view(cap, claim=head_text + " not<abs>/data/x.csv")              # marker inside a token: a difference
    assert "VER-HEAD" in verify_crate(cap).rules
    _edit_view(cap, claim="Totally different text <abs>/data/x.csv")       # marker cannot hide an edit of the rest
    assert "VER-HEAD" in verify_crate(cap).rules


def test_f12_every_revision_withheld_is_a_note_and_partial(cap):
    revs = json.loads((cap / "records/claim_revisions.json").read_text())
    from tests.test_rocrate_adversary import _claim_stub
    (cap / "records/claim_revisions.json").write_text(
        json.dumps([_claim_stub(r) for r in revs], indent=2, sort_keys=True) + "\n")
    _sync_objects(cap, {"records/claim_revisions.json"})
    ids = [f"{CLAIM_ID}@{n}" for n in range(3)]
    _reseal_bundle(cap, lambda b: setattr(b, "coverage", {"records_verified": 9, "records_total": 12,
                                                          "unverifiable_ids": ids, "withheld_ids": ids}))
    _regen(cap)
    res = verify_crate(cap)
    assert res.ok and res.partial and any("every revision is withheld" in n for n in res.notes)


# ---------------------------------------------------------------------- F13
def test_f13_statuses_and_exit_codes(tmp_path, cap):
    ok = verify_crate(cap)
    assert ok.status == "ok" and ok.exit_code == 0 and not ok.partial and ok.to_dict()["status"] == "ok"
    out = _cli(cap)
    assert out.returncode == 0 and "verify: OK (" in out.stdout

    d = tmp_path / "p"
    build_capsule(d, redact=["claim.1"])
    part = verify_crate(d)
    assert part.ok and part.partial and part.status == "ok_partial_withheld" and part.exit_code == 3
    out = _cli(d)
    assert out.returncode == 3 and "PARTIAL" in out.stdout and "reject this by policy" in out.stdout
    assert json.loads(_cli(d, "--json").stdout)["status"] == "ok_partial_withheld"

    (cap / "data" / "streamflow_x.json").write_text("{}")
    bad = verify_crate(cap)
    assert bad.status == "failed" and bad.exit_code == 1 and _cli(cap).returncode == 1


def test_f13_forged_stub_is_flagged_partial_not_plain_ok(cap):
    # a forged-but-shape-valid stub on an uncited row is still accepted (documented limit) but never as plain "ok"
    def edit(rl, rid):
        rl[rid] = _stub_of(rl[rid])
    _row_edit(cap, "claim.1", edit)
    _declare_withheld(cap, ["claim.1"])
    _regen(cap)
    res = verify_crate(cap)
    assert res.ok and res.status == "ok_partial_withheld" and res.exit_code == 3
