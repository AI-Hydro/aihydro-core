"""Golden and structural tests for the Bundle -> RO-Crate projection."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aihydro_core.export import (
    dumps_crate,
    load_inputs,
    record_key,
    scan_files,
    to_rocrate,
    validate_crate,
    verify_crate,
)
from aihydro_core.export import rocrate as rc
from aihydro_core.export.rocrate_validate import errors
from aihydro_core.records import Bundle
from tests.rocrate_fixture import BASIN_REF, CLAIM_ID, build_capsule

GOLDEN = Path(__file__).resolve().parent / "data" / "rocrate" / "capsule"


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _graph(d: Path) -> dict:
    return {e["@id"]: e for e in json.loads((d / "ro-crate-metadata.json").read_text())["@graph"]}


@pytest.fixture()
def cap(tmp_path):
    build_capsule(tmp_path / "c")
    return tmp_path / "c"


def test_golden_capsule_and_crate_are_byte_identical(tmp_path):
    out = tmp_path / "c"
    build_capsule(out)
    if os.environ.get("AIHYDRO_REGEN_GOLDEN") == "1":  # explicit, never implicit
        import shutil
        shutil.rmtree(GOLDEN, ignore_errors=True)
        shutil.copytree(out, GOLDEN)
    assert _tree(out) == _tree(GOLDEN)


def test_golden_crate_validates_and_verifies():
    assert errors(validate_crate(GOLDEN)) == []
    res = verify_crate(GOLDEN)
    assert res.ok, res.failures
    assert res.records_verified == res.records_total == 12 and res.unverifiable_ids == []


def test_projection_is_deterministic_and_pinned(cap):
    bundle = Bundle.from_dict(json.loads((cap / "bundle.json").read_text()))
    records, bodies, files = load_inputs(cap, bundle)
    a = dumps_crate(to_rocrate(bundle, records, bodies, files))
    b = dumps_crate(to_rocrate(bundle, dict(reversed(list(records.items()))), bodies, files))
    assert a == b and a.endswith("}\n") and not a.endswith("\n\n") and "\t" not in a
    assert a == json.dumps(json.loads(a), indent=2, ensure_ascii=False, sort_keys=True, separators=(",", ": ")) + "\n"
    ids = [e["@id"] for e in json.loads(a)["@graph"]]
    assert ids == sorted(ids)
    assert all("@" not in i.replace("@id", "") or i.startswith("http") for i in ids if i.startswith("#"))  # '@' percent-encoded


def test_context_descriptor_and_profile_claims(cap):
    crate = json.loads((cap / "ro-crate-metadata.json").read_text())
    assert crate["@context"][0] == "https://w3id.org/ro/crate/1.3/context"
    assert not any("workflow-run" in str(c) for c in crate["@context"])         # would remap sha256
    g = _graph(cap)
    assert g["ro-crate-metadata.json"]["conformsTo"] == {"@id": "https://w3id.org/ro/crate/1.3"}
    assert g["./"]["conformsTo"] == {"@id": "https://w3id.org/ro/wfrun/process/0.6"}   # M3/M4: no AI-Hydro profile
    assert g["./"]["@type"] == "Dataset" and g["./"]["datePublished"] == "2026-10-03T12:00:00Z"
    assert "Integrity is not origin" in g["./"]["description"]
    assert g["./"]["license"] == {"@id": "#license-unspecified"}
    keys = {k for e in crate["@graph"] for k in e}
    assert not {"prov:wasGeneratedBy", "wasGeneratedBy", "sameAs"} & keys


def test_files_have_bare_hex_sha256_and_sizes(cap):
    g = _graph(cap)
    files = scan_files(cap)
    for path, f in files.items():
        e = g[rc.file_id(path)]
        assert e["@type"] == "File" and e["sha256"] == f["sha256"] and len(e["sha256"]) == 64
        assert not e["sha256"].startswith("sha256:") and e["contentSize"] == str(f["size"])
    assert g["data/served_streamflow_x.csv"]["license"] == "CC0-1.0"
    assert g["data/served_streamflow_x.csv"]["encodingFormat"] == "text/csv"
    assert "ro-crate-metadata.json" not in files and "manifest-sha256.txt" not in files


def test_one_action_per_call_with_both_record_digests(cap):
    g = _graph(cap)
    q = g["#action-q.1"]
    assert len(q["aihydro:recordDigest"]) == 2
    assert "#action-streamflow.1" not in g and "#action-signatures.1" not in g
    assert q["result"] and {"@id": "data/streamflow_x.json"} in q["result"]       # retained file is a result
    sigs = g["#action-sigs.1"]
    assert sigs["prov:wasInformedBy"] == {"@id": "#action-q.1"}                    # parent run mapped to its call action
    assert {"@id": "#output-q.1"} in sigs["object"] and {"@id": "data/streamflow_x.json"} in sigs["object"]
    assert {"@id": "#source-usgs-nwis-f28e1813"} in sigs["object"]
    assert g["#output-sigs.1"]["value"].startswith("sha256:") and "not carried" in g["#output-sigs.1"]["description"]
    for a in g.values():
        if a.get("@type") == "CreateAction":
            assert a["instrument"] and a.get("endTime")
            assert "startTime" not in a and "agent" not in a                       # never invented


def test_gate_refusal_is_a_failed_action_with_allowlisted_code(cap):
    g = _graph(cap)
    promo = g["#action-promo.1"]
    assert promo["actionStatus"] == "http://schema.org/FailedActionStatus" and promo["error"] == "APPROVAL_REQUIRED"
    assert "error" not in g["#action-claim.1"]


def test_statistic_is_a_result_and_claims_derive_from_it(cap):
    g = _graph(cap)
    stat = g["#stat-sigs.1-baseflow_index"]
    assert stat["value"] == 0.5853970180143581 and stat["measurementMethod"] == "bootstrap_block"
    assert {"@id": stat["@id"]} in g["#action-sigs.1"]["result"]
    ci = g[stat["valueReference"]["@id"]]
    assert ci["additionalType"] == "http://purl.obolibrary.org/obo/STATO_0000196"
    assert (ci["minValue"], ci["maxValue"]) == (0.5714594819304801, 0.5987070972165335)
    props = {g[r["@id"]]["propertyID"]: g[r["@id"]]["value"] for r in ci["additionalProperty"]}
    assert props["http://purl.obolibrary.org/obo/STATO_0000561"] == 0.9 and props["n"] == 7305
    for cid in ("#claim-bfi-test-claim-rev1", "#claim-bfi-test-claim-view"):
        assert g[cid]["prov:wasDerivedFrom"] == {"@id": stat["@id"]}


def test_claim_basis_is_stated_and_revisions_chain(cap):
    g = _graph(cap)
    for n in range(3):
        c = g[f"#claim-{CLAIM_ID}-rev{n}"]
        assert g[c["additionalProperty"]["@id"]]["value"] == "sealed_revision"
        assert c["aihydro:recordDigest"].startswith("sha256:") and c["aihydro:recordLocation"].endswith(f"#/{n}")
        assert ("prov:wasRevisionOf" in c) == (n > 0)
    assert g[f"#claim-{CLAIM_ID}-rev2"]["prov:wasRevisionOf"] == {"@id": f"#claim-{CLAIM_ID}-rev1"}
    view = g[f"#claim-{CLAIM_ID}-view"]
    assert g[view["additionalProperty"]["@id"]]["value"] == "working_view_unsealed"
    assert "working view, unsealed" in view["name"] and "aihydro:recordDigest" not in view


def test_place_model_and_aliases_never_same_as(cap):
    g = _graph(cap)
    hexid = BASIN_REF["id"].split(":")[-1]
    basin, outlet = g[f"#basin-{hexid}"], g[f"#outlet-{hexid}"]
    assert basin["identifier"] == BASIN_REF["id"] and basin["containsPlace"] == {"@id": outlet["@id"]}
    assert g[outlet["geo"]["@id"]]["latitude"] == 47.2375
    aliases = [g[i["@id"]] for i in outlet["identifier"]]
    assert {a["propertyID"] for a in aliases} == {"usgs", "geoconnex"}
    assert all("unverified" in a["description"] for a in aliases)
    assert basin["aihydro:recordLocation"] == "run_log.json#/watershed.1/key_outputs/basin_ref"


def test_replay_assess_action_and_root_mirror(cap):
    g = _graph(cap)
    a = g["#assess-replay"]
    assert a["@type"] == "AssessAction" and a["object"] == {"@id": "./"} and a["instrument"] == {"@id": "#tool-verifier"}
    ver = g["#tool-verifier"]
    assert len(ver["sha256"]) == 64 and ver["version"] == "0.2.4"
    res = {g[r["@id"]]["propertyID"]: g[r["@id"]] for r in a["result"]}
    assert res["replayStatus"]["value"] == "archive_integrity" == g["./"]["aihydro:replayStatus"]
    assert (res["records_verified"]["value"], res["records_verified"]["maxValue"]) == (12, 12)
    assert "Complete." in a["description"] and "partial" not in a["description"].lower()
    assert "Self-assessed" in a["description"] and "nothing was recomputed" in a["description"]


def test_terms_are_defined_in_graph_under_one_namespace(cap):
    g = _graph(cap)
    used = {k for e in g.values() for k in e if k.startswith("aihydro:")}
    assert used == {"aihydro:canonicalization", "aihydro:recordDigest", "aihydro:recordLocation", "aihydro:replayStatus"}
    for t in used:
        d = g[rc.PROFILE_NS + t.split(":")[1]]
        assert d["@type"] == "rdf:Property" and all(d[k] for k in ("name", "description", "rdfs:label", "rdfs:comment"))
        assert "unregistered" in d["rdfs:comment"]
    assert rc.PROFILE_NS.startswith("https://") and ".invalid/" in rc.PROFILE_NS


def test_export_action_results_exclude_files_produced_by_runs(cap):
    g = _graph(cap)
    ex = {r["@id"] for r in g["#action-export"]["result"]}
    assert "data/streamflow_x.json" not in ex and "data/served_streamflow_x.csv" in ex and "bundle.json" in ex
    assert "Its own run record" in g["#action-export"]["description"]


# ------------------------------------------------------- body binding (M2)
def _project(cap, mutate_bodies=None, mutate_bundle=None):
    bundle = Bundle.from_dict(json.loads((cap / "bundle.json").read_text()))
    if mutate_bundle:
        mutate_bundle(bundle)
        bundle.seal()
    records, bodies, files = load_inputs(cap, bundle)
    if mutate_bodies:
        mutate_bodies(bodies)
    return json.loads(dumps_crate(to_rocrate(bundle, records, bodies, files)))


def test_values_come_only_from_bound_bodies(cap):
    def edit(b):
        b[record_key("run", "sigs.1")]["evidence"]["uncertainty"]["baseflow_index"]["value"] = 0.9
        b[record_key("run", "signatures.1")]["evidence"]["uncertainty"]["baseflow_index"]["value"] = 0.9
    crate = _project(cap, mutate_bodies=edit)
    ids = {e["@id"] for e in crate["@graph"]}
    assert "#stat-sigs.1-baseflow_index" not in ids and "0.9" not in json.dumps(crate)   # tampered body is not projected

    def unbind(bundle):
        for e in bundle.records:
            e.pop("binding", None)
    crate = _project(cap, mutate_bundle=unbind)
    assert "#stat-sigs.1-baseflow_index" not in {e["@id"] for e in crate["@graph"]}      # no binding, no projection


def test_unsealed_or_mismatched_inputs_are_refused(cap):
    bundle = Bundle.from_dict(json.loads((cap / "bundle.json").read_text()))
    records, bodies, files = load_inputs(cap, bundle)
    unsealed = Bundle.from_dict({**bundle.to_dict(), "bundle_id": None, "record_digest": None})
    with pytest.raises(ValueError):
        to_rocrate(unsealed, records, bodies, files)
    bad = {k: dict(v) for k, v in files.items()}
    bad["run_log.json"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        to_rocrate(bundle, records, bodies, bad)
    with pytest.raises(ValueError):
        to_rocrate(bundle, {}, bodies, files)                                           # a verified run needs its record


# ------------------------------------------------------ partial / privacy stubs
def test_unverifiable_records_become_digest_only_stubs_and_say_partial(tmp_path):
    out = tmp_path / "c"
    build_capsule(out, redact=["claim.1", "sigs.1"])
    assert errors(validate_crate(out)) == []
    res = verify_crate(out)
    assert res.ok, res.failures
    assert res.unverifiable_ids == ["claim.1", "sigs.1"] and len(res.notes) == 2
    g = _graph(out)
    assert "withheld" in g["#action-claim.1"]["description"] and "instrument" in g["#action-claim.1"]
    assert "#stat-sigs.1-baseflow_index" not in g                                      # body withheld: nothing projected
    a = g["#assess-replay"]
    assert "partial" in a["description"].lower() and "sigs.1" in a["description"]
    assert g["#replay-coverage"]["value"] == 10 and g["#replay-coverage"]["maxValue"] == 12
    assert g["./"]["aihydro:replayStatus"] == "archive_integrity"


def test_actor_projection_only_for_humans(tmp_path):
    from tests import rocrate_fixture as fx
    bundle = build_capsule(tmp_path / "c")
    records, bodies, files = load_inputs(tmp_path / "c", bundle)
    records[record_key("run", "start.1")] = {**records[record_key("run", "start.1")],
                                              "actor": {"kind": "human", "id": "reviewer-1"}}
    crate = json.loads(dumps_crate(to_rocrate(bundle, records, bodies, files)))
    g = {e["@id"]: e for e in crate["@graph"]}
    ag = g["#action-start.1"]["agent"]["@id"]
    assert g[ag]["@type"] == "Person"
    records[record_key("run", "start.1")]["actor"] = {"kind": "package", "id": "aihydro-tools"}
    g = {e["@id"]: e for e in json.loads(dumps_crate(to_rocrate(bundle, records, bodies, files)))["@graph"]}
    assert "agent" not in g["#action-start.1"]
    assert fx.SID
