"""
Stdlib structural validator for crates produced by :func:`to_rocrate`.

This is *not* a general RO-Crate validator and does not replace
``rocrate-validator`` (P5.6). It checks only (a) the structural MUSTs the
crate relies on, and (b) the AI-Hydro honesty, claim-basis and privacy rules.
Every rule has an id and cites the clause it implements. Clause URLs are the
ones recorded in ``plans/slice-5-rocrate-critique.md``; the RO-Crate 1.2 pages
are cited for clauses that 1.3 did not change (its changelog touches only four
Bioschemas workflow terms and a schema.org update). They were *not* fetched by
this offline build, so they are citations, not re-verification.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from aihydro_core.export.rocrate import (
    COMPLETED,
    CRATE_FILE,
    FAILED,
    PATH_PATTERN,
    PRC_PROFILE,
    PROFILE_NS,
    ROCRATE_CONTEXT,
    ROCRATE_SPEC,
    TERMS,
)
from aihydro_core.records import ReplayStatus, replay_rank

_RC = "https://www.researchobject.org/ro-crate/specification/1.2"
_PRC = "https://www.researchobject.org/workflow-run-crate/profiles/process_run_crate/"
_PROV = "https://www.w3.org/TR/prov-o/"

#: Marker type of a recomputation entity (G6). The builder never emits one.
RECOMPUTATION_TYPE = PROFILE_NS + "Recomputation"

RULES: Dict[str, str] = {
    "RC-JSON": f"{_RC}/appendix/jsonld.html",
    "RC-CONTEXT": "https://www.researchobject.org/ro-crate/specification/1.3/appendix/changelog.html "
                  "and https://github.com/ResearchObject/ro-terms/blob/master/workflow-run/vocabulary.csv (sha256 remap)",
    "RC-CONTEXT-RESOLVE": "rocrate-validator ro-crate-1.3 check 4.1 (every compacted key must resolve through the @context); "
                          f"{_RC}/appendix/jsonld.html#ro-crate-json-ld-context",
    "RC-PROFILE": "rocrate-validator ro-crate-1.3 check 16.1 (root conformsTo values MUST reference Profile entities); "
                  f"{_RC}/profiles.html",
    "RC-SOFTWARE-URL": "rocrate-validator ro-crate-1.3 check 32.2 (SoftwareApplication MUST have a url); "
                       f"{_RC}/contextual-entities.html#software",
    "RC-DESCRIPTOR": f"{_RC}/root-data-entity.html#ro-crate-metadata-descriptor",
    "RC-ROOT": f"{_RC}/root-data-entity.html#direct-properties-of-the-root-data-entity",
    "RC-FLAT": f"{_RC}/appendix/jsonld.html#flattened-json-ld",
    "RC-ID-UNIQUE": f"{_RC}/appendix/jsonld.html#describing-entities-in-json-ld",
    "RC-REF-RESOLVE": f"{_RC}/appendix/jsonld.html#describing-entities-in-json-ld",
    "RC-FILE": f"{_RC}/data-entities.html#file-data-entity",
    "RC-HASPART": f"{_RC}/root-data-entity.html#direct-properties-of-the-root-data-entity",
    "RC-TERM-DEFINED": f"{_RC}/appendix/jsonld.html#extending-ro-crate",
    "PRC-ACTION": _PRC,
    "PRC-INSTRUMENT": _PRC,
    "PROV-DOMAIN": f"{_PROV}#Entity and {_PROV}#Activity (wasDerivedFrom is Entity to Entity)",
    "PROV-STAT-RESULT": f"{_PROV} (M5: the statistic is an entity that is a result of the run)",
    "HON-REPLAY-PRESENT": "ADR-005 (replay_status required in every crate)",
    "HON-REPLAY-ASSESS": "plans/slice-5-rocrate-critique.md C2 (AssessAction), Five Safes RO-Crate https://trefx.uk/5s-crate/0.4/",
    "HON-REPLAY-LEVEL": "ADR-005; plan section 4 (level at most the manifest's and at most the level checked)",
    "HON-RECOMPUTED": "ADR-005 (integrity never presented as recomputation); plan section 4",
    "HON-COVERAGE": "plans/slice-5-rocrate-critique.md section F, R2 (partiality is coverage)",
    "HON-NOT-ORIGIN": "plans/slice-5-rocrate-critique.md C7 (integrity is not origin)",
    "CLM-BASIS": "plans/slice-5-rocrate-critique.md M7 (sealed revision or working view, unsealed)",
    "PRIV-PATH": "plan section 4 (privacy: no absolute or file:// paths, no known local roots)",
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Finding:
    """One rule violation (``severity`` is ``error`` or ``warning``)."""

    def __init__(self, rule: str, message: str, entity: Optional[str] = None, severity: str = "error"):
        self.rule, self.message, self.entity, self.severity = rule, message, entity, severity

    @property
    def clause(self) -> str:
        return RULES.get(self.rule, "")

    def __repr__(self) -> str:
        return f"Finding({self.rule}, {self.entity!r}, {self.message!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "severity": self.severity, "entity": self.entity,
                "message": self.message, "clause": self.clause}


def _types(ent: Mapping[str, Any]) -> List[str]:
    t = ent.get("@type")
    return [t] if isinstance(t, str) else list(t or [])


def _as_list(v: Any) -> List[Any]:
    return [] if v is None else (v if isinstance(v, list) else [v])


def _ref_ids(v: Any) -> List[str]:
    return [x["@id"] for x in _as_list(v) if isinstance(x, dict) and "@id" in x]


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)


def validate_graph(crate: Any, directory: "str | Path | None" = None) -> List[Finding]:
    """Validate a parsed crate. With ``directory``, also check File presence."""
    out: List[Finding] = []

    def err(rule: str, msg: str, ent: Optional[str] = None, severity: str = "error") -> None:
        out.append(Finding(rule, msg, ent, severity))

    if not isinstance(crate, dict) or not isinstance(crate.get("@graph"), list) or "@context" not in crate:
        err("RC-JSON", "crate must be an object with @context and an @graph array")
        return out
    ctx = _as_list(crate["@context"])
    if not ctx or ctx[0] != ROCRATE_CONTEXT:
        err("RC-CONTEXT", f"first @context entry must be {ROCRATE_CONTEXT}")
    if any(isinstance(c, str) and "workflow-run" in c for c in ctx):
        err("RC-CONTEXT", "the workflow-run context must not be added: it remaps sha256")
    graph = crate["@graph"]
    inline = {}
    for c in ctx:
        if isinstance(c, dict):
            inline.update(c)
    used_compact = sorted({k for e in graph if isinstance(e, dict) for k in e
                           if ":" in k and not k.startswith("@")})
    for k in used_compact:
        if k not in inline:
            err("RC-CONTEXT-RESOLVE", f"key {k!r} is not defined as a term in the inline @context "
                                       "(a prefix alone does not make the key resolvable)")
    ents: Dict[str, Dict[str, Any]] = {}
    for e in graph:
        if not isinstance(e, dict) or not isinstance(e.get("@id"), str):
            err("RC-FLAT", "every @graph member must be an object with a string @id")
            continue
        if e["@id"] in ents:
            err("RC-ID-UNIQUE", f"duplicate @id {e['@id']!r}", e["@id"])
        ents[e["@id"]] = e

    # --- flatness and reference resolution
    for eid, e in ents.items():
        for key, val in e.items():
            if key.startswith("@"):
                continue
            for item in _as_list(val):
                if isinstance(item, dict):
                    if set(item) != {"@id"}:
                        err("RC-FLAT", f"property {key!r} embeds a nested object; the graph must be flat", eid)
                    else:
                        target = item["@id"]
                        if target not in ents and not re.match(r"^https?://", target):
                            err("RC-REF-RESOLVE", f"{key} -> {target!r} does not resolve in the graph", eid)

    # --- descriptor and root
    desc = ents.get(CRATE_FILE)
    if desc is None or "CreativeWork" not in _types(desc):
        err("RC-DESCRIPTOR", "missing metadata descriptor ro-crate-metadata.json of type CreativeWork")
        root_id = "./"
    else:
        root_id = (desc.get("about") or {}).get("@id") if isinstance(desc.get("about"), dict) else None
        if not root_id:
            err("RC-DESCRIPTOR", "descriptor must have about -> the root data entity", CRATE_FILE)
        conf = _ref_ids(desc.get("conformsTo"))
        if ROCRATE_SPEC not in conf:
            err("RC-DESCRIPTOR", f"descriptor conformsTo must be {ROCRATE_SPEC}", CRATE_FILE)
    root = ents.get(root_id or "./")
    if root is None or "Dataset" not in _types(root):
        err("RC-ROOT", "root data entity must exist and be a Dataset")
        return out
    if not isinstance(root.get("datePublished"), str) or not _ISO_DATE.match(root["datePublished"]):
        err("RC-ROOT", "root datePublished must be an ISO 8601 string", root["@id"])
    for should in ("name", "description", "license"):
        if should not in root:
            err("RC-ROOT", f"root should have {should}", root["@id"], "warning")
    conf = _ref_ids(root.get("conformsTo"))
    if PRC_PROFILE not in conf:
        err("PRC-ACTION", f"root conformsTo must include Process Run Crate {PRC_PROFILE}", root["@id"])
    for c in conf:
        pe = ents.get(c)
        if pe is None or "Profile" not in _types(pe) or not pe.get("name") or not pe.get("version"):
            err("RC-PROFILE", f"root conformsTo {c!r} must reference a contextual entity typed Profile with name and version",
                root["@id"])
    if any(c.startswith(PROFILE_NS) for c in conf):
        err("RC-DESCRIPTOR", "root must not claim an AI-Hydro profile until its IRI resolves (M4)", root["@id"])

    # --- files
    has_part = set(_ref_ids(root.get("hasPart")))
    for eid, e in ents.items():
        if "File" not in _types(e):
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", eid) or eid.startswith("/") or ".." in eid.split("/") \
                or re.search(r"[\s\\]", eid):
            err("RC-FILE", "File @id must be a relative, percent-encoded path", eid)
        if eid not in has_part:
            err("RC-HASPART", "File is not listed in the root hasPart", eid)
        sha, size = e.get("sha256"), e.get("contentSize")
        if not isinstance(sha, str) or not _HEX64.match(sha):
            err("RC-FILE", "File sha256 must be 64 lowercase hex characters (bare)", eid)
        if not (isinstance(size, str) and size.isdigit()):
            err("RC-FILE", "File contentSize must be a decimal string", eid)
        if directory is not None:
            from urllib.parse import unquote
            if not (Path(directory) / unquote(eid)).is_file():
                err("RC-FILE", "File is not present in the crate directory", eid)
    for hp in has_part:
        if hp in ents and "File" not in _types(ents[hp]) and "Dataset" not in _types(ents[hp]):
            err("RC-HASPART", "hasPart member is neither File nor Dataset", hp)

    # --- in-graph term definitions
    used = {k for e in ents.values() for k in e if k.startswith("aihydro:")}
    for k in sorted(used):
        term = k.split(":", 1)[1]
        d = ents.get(PROFILE_NS + term)
        if term not in TERMS or d is None:
            err("RC-TERM-DEFINED", f"term {k!r} is used but not defined in the graph")
            continue
        if "rdf:Property" not in _types(d) or not all(d.get(p) for p in ("name", "description", "rdfs:label", "rdfs:comment")):
            err("RC-TERM-DEFINED", f"definition of {k!r} needs @type rdf:Property, name, description, rdfs:label, rdfs:comment", d["@id"])

    # --- actions (Process Run Crate)
    actions = {i: e for i, e in ents.items() if {"CreateAction", "AssessAction", "UpdateAction", "ActivateAction"} & set(_types(e))}
    mentions = set(_ref_ids(root.get("mentions")))
    for aid, a in actions.items():
        if aid not in mentions:
            err("PRC-ACTION", "action is not listed in the root mentions", aid, "warning")
        ins = _ref_ids(a.get("instrument"))
        if not ins:
            err("PRC-INSTRUMENT", "an action must have an instrument (Process Run Crate MUST)", aid)
        for i in ins:
            if i in ents and not ({"SoftwareApplication", "SoftwareSourceCode", "ComputationalWorkflow"} & set(_types(ents[i]))):
                err("PRC-INSTRUMENT", f"instrument {i!r} must be a SoftwareApplication", aid)
        status = a.get("actionStatus")
        if status is not None and status not in (COMPLETED, FAILED):
            err("PRC-ACTION", "actionStatus must be Completed or Failed", aid)
        if a.get("error") is not None and status != FAILED:
            err("PRC-ACTION", "error is allowed only with a FailedActionStatus", aid)
        for ag in _ref_ids(a.get("agent")):
            if ag in ents and not ({"Person", "Organization"} & set(_types(ents[ag]))):
                err("PRC-ACTION", "agent must be a Person or Organization", aid)
        for rid in _ref_ids(a.get("prov:wasInformedBy")):
            if rid not in actions:
                err("PROV-DOMAIN", f"prov:wasInformedBy must target an action, got {rid!r}", aid)
    for sid, s in ents.items():
        if "SoftwareApplication" in _types(s) and not s.get("url"):
            err("RC-SOFTWARE-URL", "a SoftwareApplication must have a url", sid)
        if "SoftwareApplication" in _types(s) and "version" in s and "softwareVersion" in s:
            err("PRC-ACTION", "SoftwareApplication must not have both version and softwareVersion", sid)

    # --- claims: basis and PROV domain
    results = {r for a in actions.values() for r in _ref_ids(a.get("result"))}
    for cid, c in ents.items():
        if "Claim" not in _types(c):
            continue
        bases = [ents[b] for b in _ref_ids(c.get("additionalProperty")) if b in ents
                 and ents[b].get("propertyID") == "claimBasis"]
        val = bases[0].get("value") if bases else None
        if val not in ("sealed_revision", "working_view_unsealed"):
            err("CLM-BASIS", "claim must state its basis: sealed_revision or working_view_unsealed", cid)
        elif val == "sealed_revision":
            if not c.get("aihydro:recordDigest") or not c.get("aihydro:recordLocation"):
                err("CLM-BASIS", "a claim based on a sealed revision must carry recordDigest and recordLocation", cid)
        else:
            if c.get("aihydro:recordDigest"):
                err("CLM-BASIS", "a working view is unsealed and must not carry a recordDigest", cid)
            if "working view, unsealed" not in str(c.get("name", "")).lower():
                err("CLM-BASIS", "a working-view claim must say 'working view, unsealed' in its name", cid)
        for d in _ref_ids(c.get("prov:wasDerivedFrom")):
            if d in actions or (d in ents and "PropertyValue" not in _types(ents[d])):
                err("PROV-DOMAIN", f"prov:wasDerivedFrom must target an entity (a statistic PropertyValue), got {d!r}", cid)
            elif d not in results:
                err("PROV-STAT-RESULT", f"derived-from statistic {d!r} is not a result of any action", cid)

    # --- replay honesty
    lvl_root = root.get("aihydro:replayStatus")
    level = None
    try:
        level = ReplayStatus(lvl_root)
    except ValueError:
        err("HON-REPLAY-PRESENT", "root aihydro:replayStatus is missing or not a ReplayStatus value", root["@id"])
    assess = [a for a in actions.values() if "AssessAction" in _types(a)]
    pv_by_prop: Dict[str, Dict[str, Any]] = {}
    if len(assess) != 1:
        err("HON-REPLAY-ASSESS", f"exactly one replay AssessAction required, found {len(assess)}")
    else:
        a = assess[0]
        if root["@id"] not in _ref_ids(a.get("object")):
            err("HON-REPLAY-ASSESS", "the replay AssessAction object must be the root dataset", a["@id"])
        for r in _ref_ids(a.get("result")):
            if r in ents and ents[r].get("propertyID"):
                pv_by_prop[ents[r]["propertyID"]] = ents[r]
        for need in ("replayStatus", "manifestStatus", "checkedStatus", "records_verified"):
            if need not in pv_by_prop:
                err("HON-REPLAY-ASSESS", f"AssessAction result is missing the {need} PropertyValue", a["@id"])
    if level is not None and "replayStatus" in pv_by_prop:
        if pv_by_prop["replayStatus"].get("value") != level.value:
            err("HON-REPLAY-LEVEL", "root replayStatus does not match the assessment result", root["@id"])
        for other in ("manifestStatus", "checkedStatus"):
            try:
                cap = ReplayStatus(pv_by_prop[other].get("value"))
            except (KeyError, ValueError):
                continue
            if replay_rank(level) > replay_rank(cap):
                err("HON-REPLAY-LEVEL", f"replay level {level.value} exceeds {other} {cap.value}", root["@id"])
    if level is not None and replay_rank(level) >= replay_rank(ReplayStatus.RECOMPUTED):
        if not any(RECOMPUTATION_TYPE in _as_list(e.get("additionalType")) for e in ents.values()):
            err("HON-RECOMPUTED", f"{level.value} requires a recomputation entity (additionalType {RECOMPUTATION_TYPE}); none exists",
                root["@id"])
    if level is not None and replay_rank(level) >= replay_rank(ReplayStatus.ARCHIVE_INTEGRITY):
        cov = pv_by_prop.get("records_verified")
        if cov is None or not isinstance(cov.get("value"), int) or not isinstance(cov.get("maxValue"), int):
            err("HON-COVERAGE", "coverage (records_verified of records_total) is required at archive_integrity or above",
                root["@id"])
        else:
            partial = cov["value"] < cov["maxValue"]
            texts = " ".join(str(x.get("description", "")) for x in (assess + [cov]))
            if partial and "partial" not in texts.lower():
                err("HON-COVERAGE", "coverage is below 1 but the assessment description does not say 'partial'", root["@id"])
    if "Integrity is not origin" not in str(root.get("description", "")):
        err("HON-NOT-ORIGIN", "the root description must state that integrity is not origin", root["@id"])

    # --- privacy
    for eid, e in ents.items():
        if eid.startswith("/") or eid.startswith("file:"):
            err("PRIV-PATH", "absolute or file:// @id", eid)
        for s in _walk_strings({k: v for k, v in e.items() if k != "@id"}):
            if PATH_PATTERN.search(s):
                err("PRIV-PATH", f"local path or local root in a value: {s[:60]!r}", eid)
                break
    return out


def validate_crate(directory: "str | Path") -> List[Finding]:
    """Validate ``<directory>/ro-crate-metadata.json`` (and File presence)."""
    path = Path(directory) / CRATE_FILE
    try:
        crate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [Finding("RC-JSON", f"cannot read {CRATE_FILE}: {exc}")]
    return validate_graph(crate, directory)


def errors(findings: Iterable[Finding]) -> List[Finding]:
    return [f for f in findings if f.severity == "error"]
