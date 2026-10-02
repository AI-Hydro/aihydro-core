"""Each stdlib validator rule fires, by id, on a crate that violates it."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aihydro_core.export import RULES, validate_graph
from aihydro_core.export import rocrate as rc
from aihydro_core.export.rocrate_validate import RECOMPUTATION_TYPE, errors, validate_crate

GOLDEN = Path(__file__).resolve().parent / "data" / "rocrate" / "capsule"
BASE = json.loads((GOLDEN / "ro-crate-metadata.json").read_text())


def _ent(crate, id_):
    return next(e for e in crate["@graph"] if e["@id"] == id_)


def _pv(crate, prop):
    return next(e for e in crate["@graph"] if e.get("propertyID") == prop and e["@id"].startswith("#replay"))


def _drop(crate, id_):
    crate["@graph"] = [e for e in crate["@graph"] if e["@id"] != id_]


def _m_root(**kw):
    def f(c):
        _ent(c, "./").update(kw)
    return f


def _set_level(level, manifest=None, checked=None):
    def f(c):
        _ent(c, "./")["aihydro:replayStatus"] = level
        _pv(c, "replayStatus")["value"] = level
        if manifest:
            _pv(c, "manifestStatus")["value"] = manifest
        if checked:
            _pv(c, "checkedStatus")["value"] = checked
    return f


def _del_key(id_, key):
    def f(c):
        _ent(c, id_).pop(key, None)
    return f


def _dup(c):
    c["@graph"].append(copy.deepcopy(_ent(c, "#action-q.1")))


def _nest(c):
    _ent(c, "#action-q.1")["instrument"] = {"@id": "#tool-x", "name": "nested"}


def _dangling(c):
    _ent(c, "#action-q.1")["object"] = {"@id": "#nowhere"}


def _hasPart_drop(c):
    root = _ent(c, "./")
    root["hasPart"] = [h for h in root["hasPart"] if h["@id"] != "session.json"]


def _file_abs(c):
    _ent(c, "session.json")["@id"] = "/abs/session.json"


def _undefined_term(c):
    _ent(c, "./")["aihydro:madeUp"] = "x"


def _drop_term(c):
    _drop(c, rc.PROFILE_NS + "recordDigest")


def _partial_no_word(c):
    _pv(c, "records_verified")["value"] = 3
    _pv(c, "records_verified")["description"] = "3 of 12 records verified"
    _ent(c, "#assess-replay")["description"] = "Self-assessed. Integrity is not origin."


def _claim_basis_missing(c):
    _drop(c, "#claim-bfi-test-claim-rev1-basis")


def _claim_view_with_digest(c):
    _ent(c, "#claim-bfi-test-claim-view")["aihydro:recordDigest"] = "sha256:" + "a" * 64


def _claim_sealed_no_digest(c):
    _ent(c, "#claim-bfi-test-claim-rev1").pop("aihydro:recordDigest")


def _derived_from_action(c):
    _ent(c, "#claim-bfi-test-claim-rev1")["prov:wasDerivedFrom"] = {"@id": "#action-sigs.1"}


def _stat_not_result(c):
    a = _ent(c, "#action-sigs.1")
    a["result"] = [r for r in a["result"] if r["@id"] != "#stat-sigs.1-baseflow_index"]


def _informed_by_non_action(c):
    _ent(c, "#action-sigs.1")["prov:wasInformedBy"] = {"@id": "#output-q.1"}


def _recomputed_with_entity_free(c):
    _set_level("recomputed", "recomputed", "recomputed")(c)


def _recomputed_with_entity(c):
    _set_level("recomputed", "recomputed", "recomputed")(c)
    c["@graph"].append({"@id": "#recompute-1", "@type": "CreateAction", "name": "recomputation",
                        "additionalType": RECOMPUTATION_TYPE, "instrument": {"@id": "#tool-verifier"}})


CASES = {
    "RC-JSON": lambda c: c.pop("@graph"),
    "RC-CONTEXT": lambda c: c.__setitem__("@context", ["https://w3id.org/ro/crate/1.2/context", {}]),
    "RC-CONTEXT/wfrun": lambda c: c["@context"].append("https://w3id.org/ro/terms/workflow-run/context"),
    "RC-DESCRIPTOR": lambda c: _drop(c, "ro-crate-metadata.json"),
    "RC-DESCRIPTOR/conforms": lambda c: _ent(c, "ro-crate-metadata.json").__setitem__("conformsTo", {"@id": "https://w3id.org/ro/crate/1.1"}),
    "RC-DESCRIPTOR/profile": lambda c: _ent(c, "./").__setitem__("conformsTo", [{"@id": "https://w3id.org/ro/wfrun/process/0.6"}, {"@id": rc.PROFILE_NS + "profile"}]),
    "RC-ROOT": _del_key("./", "datePublished"),
    "RC-FLAT": _nest,
    "RC-ID-UNIQUE": _dup,
    "RC-REF-RESOLVE": _dangling,
    "RC-FILE/absolute": _file_abs,
    "RC-FILE/prefixed-sha": lambda c: _ent(c, "session.json").__setitem__("sha256", "sha256:" + "a" * 64),
    "RC-HASPART": _hasPart_drop,
    "RC-TERM-DEFINED/undefined": _undefined_term,
    "RC-TERM-DEFINED/dropped": _drop_term,
    "PRC-INSTRUMENT": _del_key("#action-q.1", "instrument"),
    "PRC-ACTION/error-completed": lambda c: _ent(c, "#action-q.1").__setitem__("error", "X"),
    "PRC-ACTION/agent": lambda c: _ent(c, "#action-q.1").__setitem__("agent", {"@id": "#tool-verifier"}),
    "PRC-ACTION/status": lambda c: _ent(c, "#action-q.1").__setitem__("actionStatus", "done"),
    "PRC-ACTION/both-versions": lambda c: _ent(c, "#tool-verifier").__setitem__("softwareVersion", "1"),
    "PROV-DOMAIN/derived": _derived_from_action,
    "PROV-DOMAIN/informed": _informed_by_non_action,
    "PROV-STAT-RESULT": _stat_not_result,
    "HON-REPLAY-PRESENT": _del_key("./", "aihydro:replayStatus"),
    "HON-REPLAY-ASSESS": lambda c: _drop(c, "#assess-replay"),
    "HON-REPLAY-LEVEL/root-only": _m_root(**{"aihydro:replayStatus": "recomputed"}),
    "HON-REPLAY-LEVEL/above-manifest": _set_level("cross_check"),
    "HON-RECOMPUTED": _recomputed_with_entity_free,
    "HON-COVERAGE/missing": lambda c: _drop(c, "#replay-coverage"),
    "HON-COVERAGE/partial-wording": _partial_no_word,
    "HON-NOT-ORIGIN": _m_root(description="A crate."),
    "CLM-BASIS/missing": _claim_basis_missing,
    "CLM-BASIS/view-with-seal": _claim_view_with_digest,
    "CLM-BASIS/sealed-without-digest": _claim_sealed_no_digest,
    "PRIV-PATH/value": lambda c: _ent(c, "#action-q.1").__setitem__("description", "ran in /Users/someone/work/x"),
    "PRIV-PATH/file-url": lambda c: _ent(c, "#action-q.1").__setitem__("description", "see file:///tmp/x"),
    "PRIV-PATH/id": lambda c: _ent(c, "#action-q.1").__setitem__("@id", "file:///etc/passwd"),
    "PRIV-PATH/windows": lambda c: _ent(c, "#action-q.1").__setitem__("name", "C:\\Users\\a"),
}


def test_golden_has_no_findings():
    assert validate_graph(copy.deepcopy(BASE), GOLDEN) == []


@pytest.mark.parametrize("case", sorted(CASES))
def test_rule_fires(case):
    crate = copy.deepcopy(BASE)
    CASES[case](crate)
    rule = case.split("/")[0]
    found = errors(validate_graph(crate, GOLDEN))
    assert rule in {f.rule for f in found}, (case, found)
    assert rule in RULES and RULES[rule]                       # every rule cites a clause
    assert all(f.clause for f in found)


def test_recomputed_is_allowed_only_with_a_recomputation_entity():
    crate = copy.deepcopy(BASE)
    _recomputed_with_entity(crate)
    assert "HON-RECOMPUTED" not in {f.rule for f in errors(validate_graph(crate, GOLDEN))}


def test_missing_file_on_disk_is_reported(tmp_path):
    import shutil
    d = tmp_path / "c"
    shutil.copytree(GOLDEN, d)
    (d / "session.json").unlink()
    found = errors(validate_crate(d))
    assert any(f.rule == "RC-FILE" and f.entity == "session.json" for f in found)


def test_unreadable_crate_is_a_finding(tmp_path):
    assert errors(validate_crate(tmp_path))[0].rule == "RC-JSON"


def test_every_rule_has_a_clause_url_or_citation():
    for rule, clause in RULES.items():
        assert clause and ("http" in clause or "plan" in clause or "ADR" in clause), rule
