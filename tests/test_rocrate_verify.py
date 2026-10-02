"""Tamper tests: every edit must fail verify (or validate) with a named rule id."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aihydro_core.export import load_inputs, scan_files, to_rocrate, verify_crate, write_crate
from aihydro_core.export import rocrate as rc
from aihydro_core.export.rocrate_validate import errors, validate_crate
from aihydro_core.records import Bundle
from tests.rocrate_fixture import CLAIM_ID, build_capsule

GOLDEN = Path(__file__).resolve().parent / "data" / "rocrate" / "capsule"


@pytest.fixture()
def cap(tmp_path):
    d = tmp_path / "c"
    shutil.copytree(GOLDEN, d)
    return d


def _jedit(path: Path, fn):
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")


def _refresh_bag(d: Path):
    rc.write_manifest_sha256(d)


def _reseal_bundle(d: Path, fn):
    """A *sophisticated* edit: change bundle.json and re-seal it consistently."""
    def edit(doc):
        b = Bundle.from_dict(doc)
        fn(b)
        doc.clear()
        doc.update(b.seal().to_dict())
    _jedit(d / "bundle.json", edit)


def _regen(d: Path):
    """Attacker re-generates a self-consistent crate + bag after editing."""
    b = Bundle.from_dict(json.loads((d / "bundle.json").read_text()))
    recs, bods, files = load_inputs(d, b)
    write_crate(to_rocrate(b, recs, bods, files), d)
    _refresh_bag(d)


def test_golden_passes(cap):
    r = verify_crate(cap)
    assert r.ok and r.failures == []


def test_data_byte_flip(cap):
    p = cap / "data/streamflow_x.json"
    data = bytearray(p.read_bytes())
    data[5] ^= 0x01
    p.write_bytes(bytes(data))
    assert "VER-FILE-DIGEST" in verify_crate(cap).rules
    _refresh_bag(cap)                                   # even with a rewritten bag manifest
    assert "VER-FILE-DIGEST" in verify_crate(cap).rules


def test_run_record_field_edit(cap):
    _jedit(cap / "run_log.json", lambda d: d["sigs.1"]["record"].__setitem__("tool_version", "9.9.9"))
    _refresh_bag(cap)
    res = verify_crate(cap)
    assert not res.ok and {"VER-FILE-DIGEST", "VER-RECORD-SEAL"} <= set(res.rules)


def test_run_record_edit_with_everything_else_rewritten_still_fails_the_seal(cap):
    _jedit(cap / "run_log.json", lambda d: d["sigs.1"]["record"].__setitem__("tool_version", "9.9.9"))
    # attacker also fixes the file digests: bundle objects, manifest, crate, bag
    files = scan_files(cap)
    _reseal_bundle(cap, lambda b: [o.update(digest="sha256:" + files["run_log.json"]["sha256"], size=files["run_log.json"]["size"])
                                   for o in b.objects if o["ref"] == "run_log.json"])
    _jedit(cap / "capsule_manifest.json", lambda d: [m.update(sha256=files["run_log.json"]["sha256"], size=files["run_log.json"]["size"])
                                                    for m in d["files"] if m["path"] == "run_log.json"])
    _regen(cap)
    res = verify_crate(cap)
    assert not res.ok and "VER-RECORD-SEAL" in res.rules and "VER-FILE-DIGEST" not in res.rules


def test_body_value_edit_uncertainty(cap):
    _jedit(cap / "run_log.json", lambda d: d["sigs.1"]["evidence"]["uncertainty"]["baseflow_index"].__setitem__("value", 0.9))
    _refresh_bag(cap)
    res = verify_crate(cap)
    assert "VER-BINDING" in res.rules and not res.ok


def test_body_value_edit_with_digests_rewritten_still_fails_binding(cap):
    _jedit(cap / "run_log.json", lambda d: d["sigs.1"]["evidence"]["uncertainty"]["baseflow_index"].__setitem__("value", 0.9))
    files = scan_files(cap)
    _reseal_bundle(cap, lambda b: [o.update(digest="sha256:" + files["run_log.json"]["sha256"], size=files["run_log.json"]["size"])
                                   for o in b.objects if o["ref"] == "run_log.json"])
    _jedit(cap / "capsule_manifest.json", lambda d: [m.update(sha256=files["run_log.json"]["sha256"], size=files["run_log.json"]["size"])
                                                    for m in d["files"] if m["path"] == "run_log.json"])
    _regen(cap)
    res = verify_crate(cap)
    assert "VER-BINDING" in res.rules                    # the bundle's binding names the original body


def test_crate_value_edit(cap):
    crate = cap / "ro-crate-metadata.json"
    text = crate.read_text()
    assert "0.5853970180143581" in text
    crate.write_text(text.replace("0.5853970180143581", "0.9"))
    _refresh_bag(cap)
    assert "VER-CRATE-REGEN" in verify_crate(cap).rules


def test_action_removed_from_crate(cap):
    def drop(c):
        c["@graph"] = [e for e in c["@graph"] if e["@id"] != "#action-promo.1"]
        root = next(e for e in c["@graph"] if e["@id"] == "./")
        root["mentions"] = [m for m in root["mentions"] if m["@id"] != "#action-promo.1"]
    _jedit(cap / "ro-crate-metadata.json", drop)
    _refresh_bag(cap)
    assert "VER-CRATE-REGEN" in verify_crate(cap).rules


def test_file_id_retargeted(cap):
    text = (cap / "ro-crate-metadata.json").read_text().replace('"@id": "data/streamflow_x.json"', '"@id": "data/served_streamflow_x.csv"')
    (cap / "ro-crate-metadata.json").write_text(text)
    _refresh_bag(cap)
    res = verify_crate(cap)
    assert "VER-CRATE-REGEN" in res.rules
    assert {"RC-ID-UNIQUE"} & {f.rule for f in errors(validate_crate(cap))}


def test_bundle_objects_edit_without_reseal(cap):
    _jedit(cap / "bundle.json", lambda d: d["objects"][0].__setitem__("size", d["objects"][0]["size"] + 1))
    res = verify_crate(cap)
    assert {"VER-BUNDLE-IDENTITY", "VER-BUNDLE-SEAL"} <= set(res.rules)


def test_bundle_objects_edit_resealed(cap):
    def edit(b):
        b.objects[0]["digest"] = "sha256:" + "f" * 64
    _reseal_bundle(cap, edit)
    res = verify_crate(cap)
    assert {"VER-FILE-DIGEST", "VER-OBJECTS-MANIFEST"} <= set(res.rules)


def test_bundle_object_dropped_resealed_disagrees_with_manifest(cap):
    _reseal_bundle(cap, lambda b: b.objects.pop(0))
    assert "VER-OBJECTS-MANIFEST" in verify_crate(cap).rules


def test_revision_dropped_from_chain(cap):
    # drop the middle revision everywhere an attacker can reach, and re-seal the bundle
    _jedit(cap / "records/claim_revisions.json", lambda d: d.pop(1))
    def edit(b):
        b.records = [r for r in b.records if r["id"] != f"{CLAIM_ID}@1"]
        for r in b.records:
            if r["id"] == f"{CLAIM_ID}@2":
                r["record_location"] = "records/claim_revisions.json#/1"
        b.coverage = {"records_verified": 11, "records_total": 11, "unverifiable_ids": []}

    def fix_objects(b):
        edit(b)
        f = scan_files(cap)
        for o in b.objects:
            if o["ref"] == "records/claim_revisions.json":
                o["digest"], o["size"] = "sha256:" + f[o["ref"]]["sha256"], f[o["ref"]]["size"]
    _reseal_bundle(cap, fix_objects)
    f = scan_files(cap)
    _jedit(cap / "capsule_manifest.json", lambda d: [m.update(sha256=f["records/claim_revisions.json"]["sha256"], size=f["records/claim_revisions.json"]["size"])
                                                    for m in d["files"] if m["path"] == "records/claim_revisions.json"])
    _refresh_bag(cap)
    res = verify_crate(cap)
    assert "VER-CHAIN" in res.rules and not res.ok


def test_revision_dropped_without_touching_bundle(cap):
    _jedit(cap / "records/claim_revisions.json", lambda d: d.pop(1))
    res = verify_crate(cap)
    assert not res.ok and "VER-FILE-DIGEST" in res.rules


def test_replay_status_edited_to_recomputed(cap):
    def edit(c):
        for e in c["@graph"]:
            if e["@id"] == "./":
                e["aihydro:replayStatus"] = "recomputed"
    _jedit(cap / "ro-crate-metadata.json", edit)
    _refresh_bag(cap)
    assert "VER-CRATE-REGEN" in verify_crate(cap).rules
    assert "HON-REPLAY-LEVEL" in {f.rule for f in errors(validate_crate(cap))}


def test_replay_status_recomputed_in_bundle_is_rejected_by_validator(cap):
    def edit(b):
        b.replay = {**b.replay, "status": "recomputed", "manifest_status": "recomputed", "checked_status": "recomputed"}
    _reseal_bundle(cap, edit)
    _regen(cap)
    assert verify_crate(cap).ok                          # consistent, so verify cannot object ...
    assert "HON-RECOMPUTED" in {f.rule for f in errors(validate_crate(cap))}   # ... the honesty rule does


def test_injected_absolute_path(cap):
    p = cap / "ro-crate-metadata.json"
    p.write_text(p.read_text().replace("Capsule export", "Capsule export from /Users/someone/secret", 1))
    _refresh_bag(cap)
    assert "PRIV-PATH" in {f.rule for f in errors(validate_crate(cap))}
    assert "VER-CRATE-REGEN" in verify_crate(cap).rules


def test_bagit_manifest_tamper(cap):
    p = cap / "manifest-sha256.txt"
    p.write_text(p.read_text().replace(p.read_text()[:8], "00000000", 1))
    assert "VER-BAGIT" in verify_crate(cap).rules


def test_unlisted_stray_file_is_detected(cap):
    (cap / "stray.txt").write_text("x")
    res = verify_crate(cap)
    assert {"VER-CRATE-REGEN", "VER-BAGIT"} <= set(res.rules)


def test_missing_bundle_and_crate(cap):
    (cap / "ro-crate-metadata.json").unlink()
    assert "VER-CRATE-REGEN" in verify_crate(cap).rules
    (cap / "bundle.json").unlink()
    assert "VER-BUNDLE-SEAL" in verify_crate(cap).rules


def test_undeclared_unverifiable_record_fails_but_declared_one_is_honest_partiality(tmp_path):
    d = tmp_path / "c"
    build_capsule(d, redact=["claim.1"])
    assert verify_crate(d).ok                           # declared in coverage
    _jedit(d / "run_log.json", lambda x: x["claim.1"]["record"].__setitem__("tool_version", "0"))
    res = verify_crate(d)
    assert not res.ok                                   # a failing seal is never mere partiality


def test_overclaiming_coverage_fails(tmp_path):
    d = tmp_path / "c"
    build_capsule(d, redact=["claim.1"])
    _reseal_bundle(d, lambda b: setattr(b, "coverage", {"records_verified": 12, "records_total": 12, "unverifiable_ids": []}))
    res = verify_crate(d)
    assert "VER-COVERAGE" in res.rules and not res.ok


def test_cli_exit_codes(cap, tmp_path):
    run = lambda *a: subprocess.run([sys.executable, "-m", "aihydro_core.export.rocrate", *a], capture_output=True, text=True)  # noqa: E731
    ok_v, ok_val = run("verify", str(cap)), run("validate", str(cap))
    assert ok_v.returncode == 0 and "verify: OK" in ok_v.stdout and "not origin" in ok_v.stdout
    assert ok_val.returncode == 0 and "validate: OK" in ok_val.stdout
    (cap / "data/streamflow_x.json").write_text("{}")
    bad = run("verify", str(cap))
    assert bad.returncode == 1 and "VER-FILE-DIGEST" in bad.stdout
    p = cap / "ro-crate-metadata.json"
    p.write_text(p.read_text().replace("Capsule export", "x /Users/a/b", 1))
    badv = run("validate", str(cap))
    assert badv.returncode == 1 and "PRIV-PATH" in badv.stdout
    assert "RuntimeWarning" not in bad.stderr
