"""Core 0.2.10: partial derived from content (C-S1) and deleted projected keys count as VER-HEAD differences."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aihydro_core.export import verify_crate
from tests.rocrate_fixture import CLAIM_ID, build_capsule
from tests.test_rocrate_adversary import _declare_withheld, _row_edit, _stub_of
from tests.test_rocrate_fm3 import _edit_view
from tests.test_rocrate_verify import _regen, _reseal_bundle, _sync_objects

GOLDEN = Path(__file__).resolve().parent / "data" / "rocrate" / "capsule"


@pytest.fixture()
def cap(tmp_path):
    d = tmp_path / "c"
    shutil.copytree(GOLDEN, d)
    return d


def _relabel_stub_as_legacy(cap):
    """The C-S1 forgery: a genuine stub row, but the bundle counts it as a legacy unsealed row with no entry."""
    def edit(rl, rid):
        rl[rid] = _stub_of(rl[rid])
    _row_edit(cap, "claim.1", edit)

    def fix(b):
        b.records = [r for r in b.records if not (r["kind"] == "run" and r["id"] == "claim.1")]
        b.coverage = {"records_verified": 11, "records_total": 11, "unverifiable_ids": [], "withheld_ids": []}
        b.run_rows = {"run_log_rows": 8, "sealed": 7, "legacy_no_record": 1, "unbound": 0, "unsealable": 0,
                      "withheld_for_privacy": 0}
        b.gates = b.gates
    _reseal_bundle(cap, fix)
    _sync_objects(cap, set())
    _regen(cap)


def test_cs1_stub_relabelled_as_legacy_row_is_not_ok(cap):
    _relabel_stub_as_legacy(cap)
    res = verify_crate(cap)
    # the row has the privacy-stub shape: partial at least, and the relabelling is a failure
    assert res.partial and "withheld" in res.partial_reasons
    assert "VER-RUN-ROWS" in res.rules and not res.ok


def test_cs1_stub_row_counted_as_withheld_is_partial_not_ok(cap):
    def edit(rl, rid):
        rl[rid] = _stub_of(rl[rid])
    _row_edit(cap, "claim.1", edit)
    _declare_withheld(cap, ["claim.1"])
    _regen(cap)
    res = verify_crate(cap)
    assert res.ok and res.status == "ok_partial_withheld" and res.partial_reasons == ["withheld"]


def test_cs1_stub_row_with_no_run_rows_declared_is_still_partial(cap):
    def edit(rl, rid):
        rl[rid] = _stub_of(rl[rid])
    _row_edit(cap, "claim.1", edit)

    def fix(b):
        b.records = [r for r in b.records if not (r["kind"] == "run" and r["id"] == "claim.1")]
        b.coverage = {"records_verified": 11, "records_total": 11, "unverifiable_ids": [], "withheld_ids": []}
        b.run_rows = None
    _reseal_bundle(cap, fix)
    _sync_objects(cap, set())
    _regen(cap)
    res = verify_crate(cap)
    assert res.partial and "withheld" in res.partial_reasons


def test_cs1_only_unsealed_legacy_rows_is_partial_unsealed_not_ok(tmp_path):
    d = tmp_path / "c"
    build_capsule(d)
    # rewrite the run log as legacy rows (no record) and the bundle as an unsealed-only capsule
    rl = {rid: {k: v for k, v in row.items() if k != "record"}
          for rid, row in json.loads((d / "run_log.json").read_text()).items()}
    (d / "run_log.json").write_text(json.dumps(rl, indent=2, sort_keys=True) + "\n")

    def fix(b):
        b.records = []
        b.coverage = {"records_verified": 0, "records_total": 0, "unverifiable_ids": []}
        b.run_rows = {"run_log_rows": 8, "sealed": 0, "legacy_no_record": 8, "unbound": 0, "unsealable": 0,
                      "withheld_for_privacy": 0}
        b.gates = None
    _reseal_bundle(d, fix)
    _sync_objects(d, {"run_log.json"})
    _regen(d)
    res = verify_crate(d)
    assert res.ok, res.failures
    assert res.partial_reasons == ["unsealed"] and res.status == "ok_partial_unsealed" and res.exit_code == 3
    out = subprocess.run([sys.executable, "-m", "aihydro_core.export.rocrate", "verify", str(d), "--json"],
                         capture_output=True, text=True)
    assert out.returncode == 3 and json.loads(out.stdout)["partial_reasons"] == ["unsealed"]


def test_cs2_golden_has_no_unsealed_rows_and_is_plain_ok(cap):
    res = verify_crate(cap)
    assert res.ok and res.status == "ok" and res.partial_reasons == [] and res.exit_code == 0


def _legacy_row_variant(cap, *, bare_stub_flag_stripped=False):
    """One run-log row loses its record (a legacy row); the other 7 stay sealed."""
    def edit(rl, rid):
        row = _stub_of(rl[rid]) if bare_stub_flag_stripped else rl[rid]
        row = {k: v for k, v in row.items() if k not in ("record", "redacted_for_privacy")}
        rl[rid] = row
    _row_edit(cap, "claim.1", edit)

    def fix(b):
        b.records = [r for r in b.records if not (r["kind"] == "run" and r["id"] == "claim.1")]
        b.coverage = {"records_verified": 11, "records_total": 11, "unverifiable_ids": []}
        b.run_rows = {"run_log_rows": 8, "sealed": 7, "legacy_no_record": 1, "unbound": 0, "unsealable": 0,
                      "withheld_for_privacy": 0}
    _reseal_bundle(cap, fix)
    _sync_objects(cap, set())
    _regen(cap)


def test_cs2_mixed_sealed_and_unsealed_rows_is_partial_unsealed(cap):
    _legacy_row_variant(cap)
    res = verify_crate(cap)
    assert res.ok, res.failures
    assert res.partial_reasons == ["unsealed"] and res.status == "ok_partial_unsealed" and res.exit_code == 3
    assert res.records_verified > 0                              # not only the zero-verified case


def test_cs2_stub_flag_stripped_into_a_bare_legacy_row_is_not_plain_ok(cap):
    _legacy_row_variant(cap, bare_stub_flag_stripped=True)
    res = verify_crate(cap)
    assert res.status != "ok" and "unsealed" in res.partial_reasons and res.exit_code == 3


def test_cs2_declared_legacy_rows_alone_make_it_partial(cap):
    # run_rows.legacy_no_record > 0 with no matching log row is still an honest "unsealed" declaration
    _reseal_bundle(cap, lambda b: setattr(b, "run_rows", {"run_log_rows": 9, "sealed": 8, "legacy_no_record": 1,
                                                          "unbound": 0, "unsealable": 0, "withheld_for_privacy": 0}))
    _regen(cap)
    res = verify_crate(cap)
    assert "unsealed" in res.partial_reasons and res.exit_code == 3


def test_cs2_status_precedence(tmp_path):
    d = tmp_path / "c"
    build_capsule(d, redact=["claim.1"])
    rl = json.loads((d / "run_log.json").read_text())
    del rl["start.1"]["record"]                                   # also one legacy row
    (d / "run_log.json").write_text(json.dumps(rl, indent=2, sort_keys=True) + "\n")

    def fix(b):
        b.records = [r for r in b.records if not (r["kind"] == "run" and r["id"] == "start.1")]
        b.coverage = {"records_verified": 10, "records_total": 11, "unverifiable_ids": ["claim.1"],
                      "withheld_ids": ["claim.1"]}
        b.run_rows = {"run_log_rows": 8, "sealed": 6, "legacy_no_record": 1, "unbound": 0, "unsealable": 0,
                      "withheld_for_privacy": 1}
    _reseal_bundle(d, fix)
    _sync_objects(d, {"run_log.json"})
    _regen(d)
    res = verify_crate(d)
    assert res.ok and res.partial_reasons == ["withheld", "unsealed"] and res.status == "ok_partial_withheld"


# ---- deleted projected keys
@pytest.mark.parametrize("key", ["claim", "claim_type", "status", "confidence", "confidence_rationale", "limitations"])
def test_deleted_projected_key_is_a_head_difference(cap, key):
    s = json.loads((cap / "session.json").read_text())
    del s["claims"][CLAIM_ID][key]
    (cap / "session.json").write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
    _reseal_bundle(cap, lambda b: [r.update(binding=__import__("aihydro_core.records", fromlist=["x"]).make_binding(s["claims"][CLAIM_ID]))
                                   for r in b.records if r["kind"] == "claim_view"])
    _sync_objects(cap, {"session.json"})
    _regen(cap)
    res = verify_crate(cap)
    assert "VER-HEAD" in res.rules and any(key in f.message for f in res.failures if f.rule == "VER-HEAD")


def test_claim_removed_from_session_is_a_head_difference(cap):
    s = json.loads((cap / "session.json").read_text())
    s["claims"] = {}
    (cap / "session.json").write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
    _reseal_bundle(cap, lambda b: setattr(b, "records", [r for r in b.records if r["kind"] != "claim_view"]))
    _sync_objects(cap, {"session.json"})
    _regen(cap)
    res = verify_crate(cap)
    assert "VER-HEAD" in res.rules and any("absent from session.json" in f.message for f in res.failures)


def test_deleted_enumerated_key_under_a_withheld_head_is_unverifiable_but_string_key_fails(cap):
    from tests.test_rocrate_fm3 import _withheld_head
    _withheld_head(cap)
    s = json.loads((cap / "session.json").read_text())
    del s["claims"][CLAIM_ID]["status"]
    (cap / "session.json").write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
    from aihydro_core.records import make_binding
    _reseal_bundle(cap, lambda b: [r.update(binding=make_binding(s["claims"][CLAIM_ID])) for r in b.records if r["kind"] == "claim_view"])
    _sync_objects(cap, {"session.json"})
    _regen(cap)
    res = verify_crate(cap)
    assert res.ok and res.partial                                # enumerated: unverifiable under a withheld head
    _edit_view(cap)                                              # restore binding path; now delete the claim text
    s = json.loads((cap / "session.json").read_text())
    del s["claims"][CLAIM_ID]["claim"]
    (cap / "session.json").write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
    _reseal_bundle(cap, lambda b: [r.update(binding=make_binding(s["claims"][CLAIM_ID])) for r in b.records if r["kind"] == "claim_view"])
    _sync_objects(cap, {"session.json"})
    _regen(cap)
    assert "VER-HEAD" in verify_crate(cap).rules


def test_docs_describe_exit_codes():
    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    assert "(`ok`), 1 (`failed`) or 3" in readme and "nonzero exit" not in readme
    import aihydro_core.export.__main__ as m
    assert "3 = verified but partial" in m.__doc__
