"""Bundle (aihydro.bundle/1), body binding (aihydro.entry/1) and locations."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aihydro_core.records import (
    ENTRY_BINDING,
    Bundle,
    BundleError,
    ReplayStatus,
    digest,
    entry_digest,
    escape_pointer_token,
    make_binding,
    make_coverage,
    make_location,
    make_object_entry,
    make_pointer,
    make_record_entry,
    min_replay_status,
    read_legacy_replay_status,
    replay_rank,
    resolve_location,
    split_location,
    unescape_pointer_token,
    verify_binding,
    verify_bundle_dict,
)

D = {c: "sha256:" + c * 64 for c in "abcdef"}
VECTORS = Path(__file__).resolve().parent / "data" / "entry_vectors.json"


def _bundle(**kw) -> Bundle:
    objects = [
        make_object_entry("run_log.json", D["a"], 10, "run_log", media_type="application/json"),
        make_object_entry("data/x.csv", D["b"], 5, "served_data", license="CC0-1.0"),
    ]
    records = [
        make_record_entry("run", "r2", D["d"], make_location("run_log.json", ["r2", "record"]),
                          make_location("run_log.json", ["r2"]),
                          {"scheme": ENTRY_BINDING, "digest": D["e"]}),
        make_record_entry("run", "r1", D["c"], make_location("run_log.json", ["r1", "record"])),
    ]
    args = dict(session_id="s1", objects=objects, records=records, created_at="2026-10-03T00:00:00Z",
                replay={"status": "archive_integrity", "manifest_status": "archive_integrity",
                        "checked_status": "archive_integrity"},
                coverage=make_coverage(2, 2))
    args.update(kw)
    return Bundle(**args).seal()


# ---------------------------------------------------------------- entry binding
def test_entry_vectors():
    spec = json.loads(VECTORS.read_text())
    assert spec["binding"] == ENTRY_BINDING
    for case in spec["cases"]:
        assert entry_digest(case["object"]) == case["digest"], case["name"]


def test_entry_excludes_only_top_level_record():
    assert entry_digest({"record": {"a": 1}, "x": 1}) == digest({"x": 1})
    assert entry_digest({"x": 1}) == digest({"x": 1})
    assert entry_digest({"x": {"record": 1}}) == digest({"x": {"record": 1}})


def test_verify_binding_detects_body_edit_and_scheme():
    row = {"record": {"r": 1}, "evidence": {"v": 1}}
    b = make_binding(row)
    assert verify_binding(row, b)
    row2 = copy.deepcopy(row)
    row2["evidence"]["v"] = 2
    assert not verify_binding(row2, b)
    assert not verify_binding(row, {**b, "scheme": "other/1"})
    assert not verify_binding(row, None) and not verify_binding(None, b)


# ------------------------------------------------------------------- pointers
@pytest.mark.parametrize("token", ["plain", "a/b", "a~b", "~1", "~0", "/~", "a/b~c", "", "é"])
def test_pointer_escape_round_trip(token):
    assert unescape_pointer_token(escape_pointer_token(token)) == token
    assert "/" not in escape_pointer_token(token)


def test_pointer_escape_rule_is_rfc6901():
    assert escape_pointer_token("a/b~c") == "a~1b~0c"
    assert unescape_pointer_token("~01") == "~1"      # ~0 then literal 1, not '/'
    assert make_pointer(["x", 3, "a/b"]) == "/x/3/a~1b"
    for bad in ("~", "a~2", "~x"):
        with pytest.raises(BundleError):
            unescape_pointer_token(bad)


def test_location_round_trip_and_resolution():
    docs = {"run_log.json": {"a/b~c": {"record": {"k": [10, 20]}}}}
    loc = make_location("run_log.json", ["a/b~c", "record", "k", 1])
    assert loc == "run_log.json#/a~1b~0c/record/k/1"
    assert split_location(loc) == ("run_log.json", ["a/b~c", "record", "k", "1"])
    assert resolve_location(docs, loc) == 20
    assert resolve_location(docs, "run_log.json#") == docs["run_log.json"]


@pytest.mark.parametrize("loc", [
    "nofragment", "/abs.json#/a", "../x.json#/a", "a/../b.json#/a", "a\\b.json#/a",
    "a.json#nonroot", "a.json#/a~2", "a//b.json#/x", "#/a",
])
def test_bad_locations_rejected(loc):
    with pytest.raises(BundleError):
        split_location(loc)


def test_resolution_failures():
    docs = {"f.json": {"a": [1]}}
    for loc in ("g.json#/a", "f.json#/b", "f.json#/a/1", "f.json#/a/01", "f.json#/a/0/x"):
        with pytest.raises(BundleError):
            resolve_location(docs, loc)


# --------------------------------------------------------------------- bundle
def test_seal_is_idempotent_and_orders_canonically():
    b = _bundle()
    first = (b.bundle_id, b.record_digest)
    assert b.seal() and (b.bundle_id, b.record_digest) == first
    assert [r["id"] for r in b.records] == ["r1", "r2"]
    assert [o["ref"] for o in b.objects] == ["data/x.csv", "run_log.json"]
    assert b.verify() and verify_bundle_dict(b.to_dict())


def test_id_is_identity_digest_of_content_only():
    b = _bundle()
    assert b.bundle_id == digest({"schema": "aihydro.bundle/1", "session_id": "s1",
                                  "objects": b.objects, "records": b.records})
    # assessments / envelope changes never move the id
    b2 = _bundle(created_at="2030-01-01T00:00:00Z", effective_tier="T2",
                 replay={"status": "cross_check", "manifest_status": "cross_check",
                         "checked_status": "cross_check"},
                 coverage=make_coverage(1, 2, ["r2"]),
                 gates=[{"run_id": "r1", "code": "APPROVAL_REQUIRED", "outcome": "error"}])
    assert b2.bundle_id == b.bundle_id and b2.record_digest != b.record_digest


def test_unknown_fields_round_trip_with_unchanged_digest():
    b = _bundle()
    d = copy.deepcopy(b.to_dict())
    d["future_top"] = {"x": [1, 2]}
    d["objects"][0]["future_obj"] = "k"          # inside identity: must be re-sealed
    d2 = Bundle.from_dict(d).seal().to_dict()
    assert d2["future_top"] == {"x": [1, 2]} and d2["objects"][0]["future_obj"] == "k"
    # unknown top-level field rides in the seal, not the id
    top_only = copy.deepcopy(b.to_dict())
    top_only["future_top"] = 1
    resealed = Bundle.from_dict(top_only).seal()
    assert resealed.bundle_id == b.bundle_id and resealed.record_digest != b.record_digest
    # an unchanged round trip keeps both digests
    again = Bundle.from_dict(json.loads(json.dumps(resealed.to_dict())))
    assert again.verify() and again.record_digest == resealed.record_digest


def _tamper_cases():
    def mut(fn):
        def run(d):
            fn(d)
            return d
        return run
    return {
        "session_id": mut(lambda d: d.__setitem__("session_id", "s2")),
        "object digest": mut(lambda d: d["objects"][0].__setitem__("digest", D["f"])),
        "object size": mut(lambda d: d["objects"][0].__setitem__("size", 99)),
        "object dropped": mut(lambda d: d["objects"].pop()),
        "record digest": mut(lambda d: d["records"][0].__setitem__("record_digest", D["f"])),
        "record location": mut(lambda d: d["records"][0].__setitem__("record_location", "x.json#/y")),
        "record dropped": mut(lambda d: d["records"].pop()),
        "created_at": mut(lambda d: d.__setitem__("created_at", "2031-01-01T00:00:00Z")),
        "replay": mut(lambda d: d["replay"].__setitem__("status", "cross_check")),
        "coverage": mut(lambda d: d["coverage"].__setitem__("records_verified", 1) or d["coverage"].__setitem__("unverifiable_ids", ["r1"])),
        "bundle_id": mut(lambda d: d.__setitem__("bundle_id", D["f"])),
        "record_digest": mut(lambda d: d.__setitem__("record_digest", D["f"])),
        "unknown field": mut(lambda d: d.__setitem__("added", 1)),
        "order": mut(lambda d: d["records"].reverse()),
    }


@pytest.mark.parametrize("name", sorted(_tamper_cases()))
def test_any_edit_is_detected(name):
    d = copy.deepcopy(_bundle().to_dict())
    assert verify_bundle_dict(d)
    assert not verify_bundle_dict(_tamper_cases()[name](d)), name


def test_unsealed_bundle_does_not_verify():
    b = Bundle(session_id="s", objects=[], records=[])
    assert not b.verify()


def test_validation():
    with pytest.raises(BundleError):
        make_object_entry("a.json", "nothex", 1, "r")
    with pytest.raises(BundleError):
        make_object_entry("../a.json", D["a"], 1, "r")
    with pytest.raises(BundleError):
        make_object_entry("a.json", D["a"], -1, "r")
    with pytest.raises(BundleError):          # sealed kinds need a seal and a location
        make_record_entry("run", "r", None, None)
    with pytest.raises(BundleError):          # an unsealed view must not claim a seal
        make_record_entry("claim_view", "c", D["a"], "a.json#/x", "a.json#/x")
    with pytest.raises(BundleError):          # binding needs a body
        make_record_entry("run", "r", D["a"], "a.json#/x", None, {"scheme": ENTRY_BINDING, "digest": D["a"]})
    make_record_entry("claim_view", "c", None, None, "session.json#/claims/c", make_binding({"a": 1}))
    with pytest.raises(BundleError):
        Bundle(session_id="s", objects=[make_object_entry("a", D["a"], 1, "r")] * 2)
    with pytest.raises(BundleError):          # gate codes are allowlisted, never free text
        Bundle(session_id="s", gates=[{"run_id": "r", "code": "something went wrong", "outcome": "error"}])
    with pytest.raises(BundleError):
        Bundle(session_id="s", replay={"status": "archive_integrity_partial"})
    with pytest.raises(BundleError):
        Bundle(session_id="s", exporter={"version": "1"})
    with pytest.raises(BundleError):
        Bundle(session_id="s", replay={"status": "archive_integrity", "assessor": {"name": "v", "sha256": "sha256:" + "a" * 64}})
    with pytest.raises(BundleError):
        make_coverage(2, 1)
    with pytest.raises(BundleError):          # ids must name exactly the unverified records
        make_coverage(1, 2, [])


def test_coverage_helpers():
    cov = make_coverage(1, 3, ["b", "a"])
    assert cov == {"records_verified": 1, "records_total": 3, "unverifiable_ids": ["a", "b"]}


# ------------------------------------------------------------ replay vocabulary
def test_no_partial_member_in_enum():
    assert "archive_integrity_partial" not in {s.value for s in ReplayStatus}


def test_legacy_partial_maps_to_archive_integrity_with_incomplete_coverage():
    assert read_legacy_replay_status("archive_integrity_partial") == (ReplayStatus.ARCHIVE_INTEGRITY, False)
    assert read_legacy_replay_status("cross_check") == (ReplayStatus.CROSS_CHECK, True)
    with pytest.raises(ValueError):
        read_legacy_replay_status("nonsense")


def test_replay_ordering():
    assert replay_rank("not_performed") < replay_rank("archive_integrity") < replay_rank("cross_check")
    assert replay_rank("cross_check") < replay_rank("recomputed") < replay_rank("independently_replicated")
    assert min_replay_status("cross_check", "archive_integrity") is ReplayStatus.ARCHIVE_INTEGRITY
