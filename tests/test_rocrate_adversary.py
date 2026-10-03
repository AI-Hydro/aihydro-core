"""Regression tests for the slice-5 adversary review (attacks a1-a14, should-fixes S1-S7)."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aihydro_core.export import (
    load_inputs,
    scan_files,
    to_rocrate,
    validate_crate,
    validate_graph,
    verify_crate,
)
from aihydro_core.export import rocrate as rc
from aihydro_core.export.rocrate_validate import errors
from aihydro_core.records import Bundle, BundleError, RunRecord, digest, make_binding
from tests.rocrate_fixture import BASIN_REF, CLAIM_ID, build_capsule
from tests.test_rocrate_verify import _jedit, _refresh_bag, _regen, _reseal_bundle, _sync_objects

GOLDEN = Path(__file__).resolve().parent / "data" / "rocrate" / "capsule"


@pytest.fixture()
def cap(tmp_path):
    d = tmp_path / "c"
    shutil.copytree(GOLDEN, d)
    return d


def _try_regen(d):
    """Attacker's regeneration; the projection itself refuses when files and bundle disagree."""
    try:
        _regen(d)
    except ValueError:
        _refresh_bag(d)


def _crate(d):
    return {e["@id"]: e for e in json.loads((d / "ro-crate-metadata.json").read_text())["@graph"]}


def _rules(d):
    return set(verify_crate(d).rules)


# ----------------------------------------------------------------------- M1
def test_a1_manifest_replay_status_edit_is_caught(cap):
    _jedit(cap / "capsule_manifest.json", lambda m: m.update(replay_status="recomputed", privacy={"redacted_rows": 99}))
    _try_regen(cap)
    r = _rules(cap)
    assert {"VER-REPLAY-MANIFEST", "VER-FILE-DIGEST"} <= r         # manifest is now a sealed object


def test_a3_bundle_level_above_on_disk_manifest(cap):
    _reseal_bundle(cap, lambda b: b.replay.update(status="cross_check", manifest_status="cross_check",
                                                 checked_status="cross_check"))
    with pytest.raises(ValueError):
        _regen(cap)                                                 # projection refuses cross_check
    assert "VER-REPLAY-MANIFEST" in _rules(cap)


def test_a3b_manifest_partial_but_bundle_claims_complete(cap):
    _jedit(cap / "capsule_manifest.json", lambda m: m.update(replay_status="archive_integrity_partial"))
    _sync_objects(cap, set())
    _regen(cap)
    res = verify_crate(cap)
    assert "VER-REPLAY-MANIFEST" in res.rules
    assert any("partial" in f.message for f in res.failures)


def test_a3c_manifest_status_must_match_manifest(cap):
    _reseal_bundle(cap, lambda b: b.replay.update(manifest_status="cross_check", checked_status="cross_check"))
    _regen(cap)
    assert "VER-REPLAY-MANIFEST" in _rules(cap)


def test_a12_verify_cli_is_a_single_gate(cap):
    # a consistent crate that the validator rejects (a local path inside a bound, sealed-consistent claim view)
    def leak(d):
        d["claims"][CLAIM_ID]["claim"] = "see /Users/someone/notes.txt"
    _jedit(cap / "session.json", leak)
    s = json.loads((cap / "session.json").read_text())
    _reseal_bundle(cap, lambda b: [r.update(binding=make_binding(s["claims"][CLAIM_ID]))
                                   for r in b.records if r["kind"] == "claim_view"])
    _sync_objects(cap, {"session.json"})
    _regen(cap)
    res = verify_crate(cap)
    assert not res.ok and "VER-VALIDATE" in res.rules and "PRIV-PATH" in " ".join(f.message for f in res.failures)
    out = subprocess.run([sys.executable, "-m", "aihydro_core.export.rocrate", "verify", str(cap)],
                         capture_output=True, text=True)
    assert out.returncode == 1 and "verify: OK" not in out.stdout


def test_to_rocrate_refuses_unsupported_levels(cap):
    for level in ("cross_check", "recomputed", "independently_reproduced"):
        b = Bundle.from_dict(json.loads((cap / "bundle.json").read_text()))
        b.replay = {**b.replay, "status": level, "manifest_status": level, "checked_status": level}
        b.seal()
        recs, bods, files = load_inputs(cap, b)
        with pytest.raises(ValueError):
            to_rocrate(b, recs, bods, files)


# ----------------------------------------------------------------------- M2
def _strip_entry_digest(d):
    rl = json.loads((d / "run_log.json").read_text())
    for rid in ("sigs.1", "signatures.1"):
        rec = rl[rid]["record"]
        rec["extra"].pop("entry_digest")
        rec.pop("record_digest")
        rl[rid]["record"] = RunRecord.from_dict(rec).seal().to_dict()
        rl[rid]["evidence"]["uncertainty"]["baseflow_index"]["value"] = 0.123456
    (d / "run_log.json").write_text(json.dumps(rl, indent=2, sort_keys=True) + "\n")

    def fix(b):
        for r in b.records:
            if r["kind"] == "run" and r["id"] in ("sigs.1", "signatures.1"):
                r["record_digest"] = rl[r["id"]]["record"]["record_digest"]
                r["binding"] = make_binding({k: v for k, v in rl[r["id"]].items() if k != "record"})
    _reseal_bundle(d, fix)
    _sync_objects(d, {"run_log.json"})


def test_a4_binding_must_be_the_sealed_one(cap):
    _strip_entry_digest(cap)
    res_before_regen = verify_crate(cap)
    assert "VER-BINDING" in res_before_regen.rules
    b = Bundle.from_dict(json.loads((cap / "bundle.json").read_text()))
    recs, bods, files = load_inputs(cap, b)
    g = {e["@id"]: e for e in to_rocrate(b, recs, bods, files)["@graph"]}
    assert "#stat-sigs.1-baseflow_index" not in g and "0.123456" not in json.dumps(g)   # never projected


# ----------------------------------------------------------------------- M3
def test_a2_replay_py_is_content_and_assessor_must_match(cap):
    (cap / "replay.py").write_bytes(b"print('verified OK')\n")
    _try_regen(cap)
    assert {"VER-FILE-DIGEST", "VER-ASSESSOR"} <= _rules(cap)
    # even if the attacker also fixes the object digest, the assessor hash names the old verifier
    _sync_objects(cap, set())
    files = scan_files(cap)
    _reseal_bundle(cap, lambda b: [o.update(digest="sha256:" + files["replay.py"]["sha256"], size=files["replay.py"]["size"])
                                   for o in b.objects if o["ref"] == "replay.py"])
    _regen(cap)
    assert "VER-ASSESSOR" in _rules(cap)


def test_objects_must_include_manifest_and_verifier_exactly(cap):
    _reseal_bundle(cap, lambda b: b.objects.__delitem__(next(i for i, o in enumerate(b.objects) if o["ref"] == "replay.py")))
    assert "VER-OBJECTS-MANIFEST" in _rules(cap)


def test_a10_identity_rewrites(cap):
    _reseal_bundle(cap, lambda b: b.replay["assessor"].update(sha256="0" * 64))
    _regen(cap)
    assert "VER-ASSESSOR" in _rules(cap)


# ------------------------------------------------------------------- S1, S2
def test_a5_basin_ref_must_lie_inside_a_bound_body(cap):
    s = json.loads((cap / "session.json").read_text())
    br = copy.deepcopy(BASIN_REF)
    br["area_km2"] = 9999.0
    s["basin_ref"] = br
    (cap / "session.json").write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")

    def fix(b):
        for r in b.records:
            if r["kind"] == "basin_ref":
                r["record_location"], r["record_digest"] = "session.json#/basin_ref", digest(br)
    _reseal_bundle(cap, fix)
    _sync_objects(cap, {"session.json"})
    _regen(cap)
    assert "VER-RECORD-SEAL" in _rules(cap)


def test_basin_digest_uses_content_term_not_seal_term(cap):
    g = _crate(cap)
    place = next(e for k, e in g.items() if k.startswith("#basin-") and e.get("@type") == "Place" and "containsPlace" in e)
    assert "aihydro:contentDigest" in place and "aihydro:recordDigest" not in place
    assert "not a seal" in g[rc.PROFILE_NS + "contentDigest"]["description"]


def test_a6_declared_gates_must_equal_derived(cap):
    _reseal_bundle(cap, lambda b: setattr(b, "gates", []))
    _regen(cap)
    assert "VER-GATES" in _rules(cap)
    # and the crate takes the code from the verified body, not the declaration
    assert _crate(cap)["#action-promo.1"]["error"] == "APPROVAL_REQUIRED"


def test_gates_invented_by_the_bundle_are_caught(cap):
    _reseal_bundle(cap, lambda b: setattr(b, "gates", b.gates + [{"run_id": "claim.1", "code": "APPROVAL_REQUIRED", "outcome": "error"}]))
    assert "VER-GATES" in _rules(cap)


# ----------------------------------------------------------------------- S3
def test_s3_versions_required_and_always_present(tmp_path):
    with pytest.raises(BundleError):
        Bundle(session_id="s", replay={"status": "archive_integrity", "assessor": {"name": "replay.py", "sha256": "a" * 64}})
    with pytest.raises(BundleError):
        Bundle(session_id="s", exporter={"name": "x"})
    d = tmp_path / "c"
    build_capsule(d, tool_version=None)                    # real records may lack tool_version
    assert errors(validate_crate(d)) == [] and verify_crate(d).ok
    apps = [e for e in _crate(d).values() if e.get("@type") == "SoftwareApplication"]
    assert apps and all(a.get("version") for a in apps)


# ----------------------------------------------------------------------- S5
def test_a9_a13_stray_file_message_names_the_path(cap):
    (cap / "notes.txt").write_text("hi")
    (cap / ".DS_Store").write_bytes(b"\0")
    res = verify_crate(cap)
    msgs = {f.entity: f.message for f in res.failures if f.rule == "VER-UNLISTED-FILE"}
    assert {"notes.txt", ".DS_Store"} <= set(msgs) and "not a bundle object" in msgs["notes.txt"]


def test_a14_symlinks_are_refused(cap, tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("TOPSECRET")
    os.symlink(target, cap / "data" / "link.json")
    os.symlink(tmp_path, cap / "linkdir")
    res = verify_crate(cap)
    ents = {f.entity for f in res.failures if f.rule == "VER-UNLISTED-FILE"}
    assert {"data/link.json", "linkdir"} <= ents and not res.ok
    with pytest.raises(ValueError):
        scan_files(cap)
    with pytest.raises(ValueError):
        rc.write_manifest_sha256(cap)


# ----------------------------------------------------------------------- S6
def test_s6_version_matches_distribution_metadata():
    import aihydro_core
    text = (Path(aihydro_core.__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert aihydro_core.__version__ == re.search(r'^version = "([^"]+)"', text, re.M).group(1) == "0.2.5"


# ----------------------------------------------------------------------- S7
LEAKS = [
    "/Users/a/b", "/home/a", "ran in /home/a/x", "/private/var/x", "/tmp/x", "/opt/conda/bin", "/scratch/job1/out",
    "/mnt/data/x", "/Volumes/Disk/x", "/srv/www", "/root/.ssh", "/etc/passwd", "file:///x", "FILE:///x"[:0] or "file://h/x",
    "//server/share/file", "\\\\server\\share\\file", "C:\\Users\\a", "C:/Users/a", "~/notes", "~alice/notes",
    "$HOME/x", "${HOME}/x", "%USERPROFILE%\\x", "path=/Users/a", '"/home/b/c"', "(/tmp/z)",
]
SAFE = [
    "https://geoconnex.us/usgs/monitoring-location/01013500", "https://example.org/home/page",
    "http://host/Users/x", "(with ~0/~1 escaping)", "a/b/c", "2026-10-03T10:00:04.000+00:00", "sha256:abc",
    "run_log.json#/sigs.1/record", "data/streamflow_x.json", "usgs:01013500", "x ~1 y", "100% /s",
    # N4: protocol-relative URLs and ~/-style text
    "//geoconnex.us/ref", "see //doi.org/10.1000/x", "value=//x/y", "tolerance ~/- 0.03", "ratio ~/2", "k:/v", " a:/b",
    "$HOMER", "user~joe/", "a ~/ b",
]


@pytest.mark.parametrize("text", LEAKS)
def test_s7_leak_patterns_catch(text):
    assert rc.PATH_PATTERN.search(text), text


@pytest.mark.parametrize("text", SAFE)
def test_s7_leak_patterns_do_not_flag_urls_or_pointers(text):
    assert not rc.PATH_PATTERN.search(text), text


def test_s7_one_shared_root_list_matches_tools_scrubber():
    assert "scratch" in rc.LOCAL_ROOTS and set(rc.LOCAL_ROOTS) >= {
        "Users", "home", "private", "var", "tmp", "opt", "root", "mnt", "Volumes", "srv", "scratch"}


# ------------------------------------------------------------- honest holds
def test_a7_full_reseal_passes_but_says_integrity_is_not_origin(cap):
    rl = json.loads((cap / "run_log.json").read_text())
    from aihydro_core.records import entry_digest
    for rid in ("sigs.1", "signatures.1"):
        rl[rid]["evidence"]["uncertainty"]["baseflow_index"]["value"] = 0.999
        body = {k: v for k, v in rl[rid].items() if k != "record"}
        rec = rl[rid]["record"]
        rec["extra"]["entry_digest"] = entry_digest(body)
        rec.pop("record_digest")
        rl[rid]["record"] = RunRecord.from_dict(rec).seal().to_dict()
    (cap / "run_log.json").write_text(json.dumps(rl, indent=2, sort_keys=True) + "\n")

    def fix(b):
        for r in b.records:
            if r["kind"] == "run" and r["id"] in ("sigs.1", "signatures.1"):
                r["record_digest"] = rl[r["id"]]["record"]["record_digest"]
                r["binding"] = make_binding({k: v for k, v in rl[r["id"]].items() if k != "record"})
    _reseal_bundle(cap, fix)
    _sync_objects(cap, {"run_log.json"})
    _regen(cap)
    assert verify_crate(cap).ok                          # a full reseal is self-consistent: integrity is not origin
    assert "Integrity is not origin" in _crate(cap)["./"]["description"]
    out = subprocess.run([sys.executable, "-m", "aihydro_core.export.rocrate", "verify", str(cap)], capture_output=True, text=True)
    assert "not origin" in out.stdout


def test_a11_working_view_edit_stays_labelled_unsealed(cap):
    s = json.loads((cap / "session.json").read_text())
    s["claims"][CLAIM_ID]["claim"] = "certain"
    (cap / "session.json").write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
    _reseal_bundle(cap, lambda b: [r.update(binding=make_binding(s["claims"][CLAIM_ID])) for r in b.records if r["kind"] == "claim_view"])
    _sync_objects(cap, {"session.json"})
    _regen(cap)
    assert verify_crate(cap).ok
    view = _crate(cap)[f"#claim-{CLAIM_ID}-view"]
    assert "working view, unsealed" in view["name"] and "aihydro:recordDigest" not in view


def test_a8_licence_string_swap_is_a_known_limit(cap):
    _refresh_bag(cap)
    assert verify_crate(cap).ok


# ------------------------------------------------------------------- N1-N3
def _crate_dict(d):
    return json.loads((d / "ro-crate-metadata.json").read_text())


@pytest.mark.parametrize("prop", ["manifestStatus", "checkedStatus"])
def test_n1_recomputed_ceilings_need_a_recomputation_entity(cap, prop):
    crate = _crate_dict(cap)
    for e in crate["@graph"]:
        if e.get("propertyID") == prop:
            e["value"] = "recomputed"
    found = errors(validate_graph(crate, cap))
    assert "HON-RECOMPUTED" in {f.rule for f in found}


@pytest.mark.parametrize("key", ["manifest_status", "checked_status"])
def test_n1_projection_refuses_recomputed_ceilings(cap, key):
    b = Bundle.from_dict(json.loads((cap / "bundle.json").read_text()))
    b.replay = {**b.replay, key: "recomputed"}
    b.seal()
    recs, bods, files = load_inputs(cap, b)
    with pytest.raises(ValueError):
        to_rocrate(b, recs, bods, files)


def test_n2_assessor_sha_is_required_and_must_be_the_named_file(cap):
    def drop_sha(b):
        b.replay["assessor"].pop("sha256")
    _reseal_bundle(cap, drop_sha)
    _try_regen(cap)
    assert "VER-ASSESSOR" in _rules(cap)
    # a sha that belongs to *another* capsule file is not the verifier
    other = scan_files(cap)["README.md"]["sha256"]
    _reseal_bundle(cap, lambda b: b.replay["assessor"].update(sha256=other))
    _try_regen(cap)
    assert "VER-ASSESSOR" in _rules(cap)


def test_n2_assessor_may_name_another_file_via_url(cap):
    files = scan_files(cap)
    _reseal_bundle(cap, lambda b: b.replay["assessor"].update(url="README.md", sha256=files["README.md"]["sha256"]))
    _regen(cap)
    assert "VER-ASSESSOR" not in _rules(cap)
    _reseal_bundle(cap, lambda b: b.replay["assessor"].update(url="README.md", sha256=files["replay.py"]["sha256"]))
    _try_regen(cap)
    assert "VER-ASSESSOR" in _rules(cap)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX FIFOs")
def test_n3_fifo_in_capsule_fails_and_is_never_opened(cap):
    os.mkfifo(cap / "data" / "pipe.json")
    res = verify_crate(cap)                              # would hang if the FIFO were opened
    assert not res.ok
    assert any(f.rule == "VER-UNLISTED-FILE" and f.entity == "data/pipe.json" and "regular" in f.message
               for f in res.failures)
    with pytest.raises(ValueError):
        scan_files(cap)
    with pytest.raises(ValueError):
        rc.write_manifest_sha256(cap)


# ------------------------------------------------------------ C1: VER-SESSION
def _edit_run_session(cap, run_id, value):
    rl = json.loads((cap / "run_log.json").read_text())
    rec = rl[run_id]["record"]
    if value is None:
        rec.pop("session_id")
    else:
        rec["session_id"] = value
    rec.pop("record_digest")
    rl[run_id]["record"] = RunRecord.from_dict(rec).seal().to_dict()
    (cap / "run_log.json").write_text(json.dumps(rl, indent=2, sort_keys=True) + "\n")

    def fix(b):
        for r in b.records:
            if r["kind"] == "run" and r["id"] == run_id:
                r["record_digest"] = rl[run_id]["record"]["record_digest"]
    _reseal_bundle(cap, fix)
    _sync_objects(cap, {"run_log.json"})


@pytest.mark.parametrize("value", ["someone-elses-session", None])
def test_c1_run_record_session_must_equal_bundle_session(cap, value):
    _edit_run_session(cap, "claim.1", value)               # a validly re-sealed record from another/no session
    res = verify_crate(cap)
    assert "VER-SESSION" in res.rules and not res.ok
    assert any(f.entity == "run:claim.1" for f in res.failures if f.rule == "VER-SESSION")


def test_c1_claim_revision_session_and_unsealed_kinds_skipped(cap):
    from aihydro_core.records import ClaimRevision
    revs = json.loads((cap / "records/claim_revisions.json").read_text())
    r = dict(revs[1])
    r.pop("record_digest")
    r["session_id"] = "other"
    revs[1] = ClaimRevision.from_dict(r).seal().to_dict()
    (cap / "records/claim_revisions.json").write_text(json.dumps(revs, indent=2, sort_keys=True) + "\n")

    def fix(b):
        for e in b.records:
            if e["id"] == f"{CLAIM_ID}@1":
                e["record_digest"] = revs[1]["record_digest"]
    _reseal_bundle(cap, fix)
    _sync_objects(cap, {"records/claim_revisions.json"})
    res = verify_crate(cap)
    assert "VER-SESSION" in res.rules
    # the working view (unsealed kind) has no session check: the golden passes
    assert verify_crate(GOLDEN).ok


def test_c1_declared_unverifiable_session_mismatch_is_only_a_note(tmp_path):
    d = tmp_path / "c"
    build_capsule(d, redact=["claim.1"])
    # redacted stubs keep the record; a mismatching session there is declared, so a note, not a failure
    _edit_run_session(d, "claim.1", "other")
    res = verify_crate(d)
    assert not any(f.rule == "VER-SESSION" for f in res.failures)


# ------------------------------------------------------------- C2: run_rows
def test_c2_run_rows_validation_and_seal_compatibility():
    from aihydro_core.records import BundleError, make_run_rows
    good = make_run_rows(run_log_rows=5, sealed=3, legacy_no_record=1, unbound=1, unsealable=1, withheld_for_privacy=1)
    assert set(good) == {"run_log_rows", "sealed", "legacy_no_record", "unbound", "unsealable", "withheld_for_privacy"}
    for bad in ({"run_log_rows": 5, "sealed": 3, "legacy_no_record": 1, "unbound": 0, "unsealable": 0,
                 "withheld_for_privacy": 0},                                   # sum mismatch
                {"run_log_rows": 1, "sealed": 1}, {**good, "sealed": -1}, {**good, "extra": 1}):
        with pytest.raises(BundleError):
            Bundle(session_id="s", run_rows=bad)
    # promoting the field from "unknown" does not change any seal (c14n sorts keys)
    b = Bundle.from_dict(json.loads((GOLDEN / "bundle.json").read_text()))
    d = b.to_dict()
    assert d["run_rows"] == b.run_rows
    old_style = {k: v for k, v in d.items() if k != "run_rows"}
    legacy = Bundle(session_id=old_style["session_id"], objects=old_style["objects"], records=old_style["records"],
                    created_at=old_style["created_at"], exporter=old_style["exporter"], replay=old_style["replay"],
                    coverage=old_style["coverage"], gates=old_style["gates"], unknown={"run_rows": dict(b.run_rows)})
    assert legacy.seal().record_digest == b.record_digest and legacy.bundle_id == b.bundle_id


def test_c2_crate_projects_run_rows_and_says_unsealed(cap):
    def edit(b):
        b.run_rows = {"run_log_rows": 11, "sealed": 8, "legacy_no_record": 2, "unbound": 1, "unsealable": 0,
                      "withheld_for_privacy": 1}
        b.records = b.records
    # 11 rows = 8 + 2 + 1; the bundle lists 8 run entries, so this stays consistent
    _reseal_bundle(cap, edit)
    _regen(cap)
    g = _crate(cap)
    pvs = {e["propertyID"]: e["value"] for e in g.values() if e.get("propertyID") in
           ("run_log_rows", "legacy_no_record", "unbound", "withheld_for_privacy")}
    assert pvs == {"run_log_rows": 11, "legacy_no_record": 2, "unbound": 1, "withheld_for_privacy": 1}
    text = g["#assess-replay"]["description"]
    assert "11 run-log rows: 8 with a sealed record, 2 without one (unsealed)" in text and "1 withheld" in text
    assert verify_crate(cap).ok and errors(validate_crate(cap)) == []


def test_c2_verify_run_rows_sealed_must_equal_run_entries(cap):
    _reseal_bundle(cap, lambda b: setattr(b, "run_rows", {"run_log_rows": 9, "sealed": 9, "legacy_no_record": 0,
                                                          "unbound": 0, "unsealable": 0, "withheld_for_privacy": 0}))
    _regen(cap)
    assert "VER-RUN-ROWS" in _rules(cap)


def test_c2_validator_requires_unsealed_wording(cap):
    crate = _crate_dict(cap)
    for e in crate["@graph"]:
        if e.get("propertyID") == "legacy_no_record":
            e["value"] = 3
    assert "HON-COVERAGE" in {f.rule for f in errors(validate_graph(crate, cap))}
    for e in crate["@graph"]:
        if e["@id"] == "#assess-replay":
            e["description"] += " 3 run-log rows are unsealed."
    assert "HON-COVERAGE" not in {f.rule for f in errors(validate_graph(crate, cap))}


def test_t2_failed_store_claim_stub_says_so(cap):
    stub_digest = digest({"status": "error", "error": "chain broken"})
    def edit(b):
        from aihydro_core.records import make_record_entry
        b.records.append(make_record_entry("claim_revision", f"{CLAIM_ID}@failed-store", stub_digest,
                                           "records/claim_revisions.json#/0"))
        b.coverage = {"records_verified": 12, "records_total": 13, "unverifiable_ids": [f"{CLAIM_ID}@failed-store"]}
    _reseal_bundle(cap, edit)
    _regen(cap)
    g = _crate(cap)
    stub = g[f"#claim-{CLAIM_ID}-revfailed-store"]
    assert "failed verification at export" in stub["name"]
    assert "failed verification at export" in g[stub["additionalProperty"]["@id"]]["description"]


# --------------------------------------------- VER-RUN-ROWS with withheld rows
def test_run_rows_accepts_withheld_rows_that_kept_their_record(tmp_path):
    d = tmp_path / "c"
    b = build_capsule(d, redact=["claim.1", "sigs.1"])
    assert b.run_rows == {"run_log_rows": 8, "sealed": 6, "legacy_no_record": 0, "unbound": 0,
                          "unsealable": 0, "withheld_for_privacy": 2}
    res = verify_crate(d)
    assert res.ok and "VER-RUN-ROWS" not in res.rules             # 8 run entries = 6 sealed + 2 withheld stubs


def test_run_rows_accepts_a_withheld_row_with_no_entry(cap):
    # one extra run-log row was withheld and kept no digest: no entry, but it is counted
    _reseal_bundle(cap, lambda b: setattr(b, "run_rows", {"run_log_rows": 9, "sealed": 8, "legacy_no_record": 0,
                                                          "unbound": 0, "unsealable": 0, "withheld_for_privacy": 1}))
    _regen(cap)
    assert "VER-RUN-ROWS" not in _rules(cap)


def test_run_rows_bounds_still_catch_overclaims_and_underclaims(cap):
    rr = lambda sealed, withheld: {"run_log_rows": sealed + withheld, "sealed": sealed, "legacy_no_record": 0,   # noqa: E731
                                   "unbound": 0, "unsealable": 0, "withheld_for_privacy": withheld}
    for sealed, withheld in ((9, 0), (7, 0), (6, 1)):              # 8 entries: too many sealed, too few, too few
        shutil.copytree(cap, cap.parent / f"c{sealed}{withheld}")
        d = cap.parent / f"c{sealed}{withheld}"
        _reseal_bundle(d, lambda b, s=sealed, w=withheld: setattr(b, "run_rows", rr(s, w)))
        _regen(d)
        assert "VER-RUN-ROWS" in _rules(d), (sealed, withheld)
