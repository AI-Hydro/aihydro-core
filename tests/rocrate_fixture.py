"""Deterministic synthetic capsule for the slice-5 RO-Crate tests.

Everything (ids, timestamps, bytes) is fixed, so ``build_capsule`` is
reproducible and the committed ``tests/data/rocrate/capsule`` tree is the golden
reference. The shapes mirror the real e2e-proof-1 capsule: run-log rows holding
``{record, evidence, ...}`` bound by ``extra.entry_digest``; two sealed records
per tool call (``put_result`` row + ``post_run`` row paired by ``call_run_id``);
a ``watershed`` row carrying a ``basin_ref``; a sealed claim-revision chain; a
working-view claim; a gate refusal (``APPROVAL_REQUIRED``).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from aihydro_core.export import rocrate as rc
from aihydro_core.records import (
    Bundle,
    ClaimRevision,
    RunRecord,
    digest,
    entry_digest,
    make_binding,
    make_coverage,
    make_location,
    make_object_entry,
    make_record_entry,
    make_run_rows,
)

SID = "synthetic-session-1"
CREATED = "2026-10-03T12:00:00Z"
ENV = digest({"python": "3.13.0", "distributions": {"aihydro-core": "0.2.4"}})
BASIN_REF = {
    "schema": "aihydro.basin_ref/1",
    "id": "aihydro:basin:sha256:7d668536474282bdef5eb810f69e6d96b0f5d39dcfc8b05ac1666b1c49331d5a",
    "anchor": {"kind": "gauge_index", "network": "nhdplusv2", "network_version": "unversioned",
               "element": "usgs:01013500"},
    "outlet": {"lon": -68.58277778, "lat": 47.2375, "aliases": [
        {"scheme": "usgs", "id": "01013500", "relation": "same_as", "source": "nwis", "verified": False},
        {"scheme": "geoconnex", "id": "https://geoconnex.us/usgs/monitoring-location/01013500",
         "relation": "same_as", "source": "constructed", "verified": False}]},
    "method": "nldi_gauge_index",
    "geometry_digest": "sha256:c19f8fcefce76767074c28d4cefcdf657030cfca31bf5d1cbbc8a5f6eb6756c6",
    "geometry_algorithm": "aihydro.geom/1", "area_km2": 2258.5163954900077, "aliases": 2,
    "minted_by": {"tool": "aihydro_watershed.identity.mint_basin_ref", "version": "0.1.0"},
    "quality_flags": 2,
}
UNC = {"value": 0.5853970180143581, "ci_low": 0.5714594819304801, "ci_high": 0.5987070972165335,
       "method": "bootstrap_block", "n": 7305, "ci_level": 0.9, "block_size": 365,
       "scope": "sampling_variability_of_ratio; excludes filter and observation uncertainty"}
CLAIM_ID = "bfi-test-claim"
_T = {"start.1": "2026-10-03T10:00:01.000001Z", "watershed.1": "2026-10-03T10:00:02.000001Z",
      "streamflow.1": "2026-10-03T10:00:03.000001Z", "q.1": "2026-10-03T10:00:03.000101Z",
      "signatures.1": "2026-10-03T10:00:04.000001Z", "sigs.1": "2026-10-03T10:00:04.000101Z",
      "claim.1": "2026-10-03T10:00:05.000001Z", "promo.1": "2026-10-03T10:00:06.000001Z"}


_TOOL_VERSION = ["2.1.0"]


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _row(run_id: str, tool: str, *, parents=(), input_refs=(), output: Any = None, status="ok",
         extra: Optional[dict] = None, evidence: Optional[dict] = None, key_outputs: Optional[dict] = None,
         error_summary: Optional[str] = None, actor: Optional[dict] = None) -> Dict[str, Any]:
    row: Dict[str, Any] = {"run_id": run_id, "tool_name": tool, "session_id": SID,
                           "timestamp": _T[run_id], "key_outputs": key_outputs or {}}
    if evidence is not None:
        row["evidence"] = evidence
    if error_summary:
        row.update({"error": True, "error_summary": error_summary})
    ex = dict(extra or {})
    ex["entry_digest"] = entry_digest(row)
    rec = RunRecord(run_id=run_id, tool=tool, tool_version=_TOOL_VERSION[0], version_source="package",
                    session_id=SID, recorded_at=_T[run_id], status=status,
                    input_digest=digest({"params": run_id}), input_refs=list(input_refs),
                    output_digest=digest(output if output is not None else {"out": run_id}),
                    parents=list(parents), env_digest=ENV, extra=ex, actor=actor).seal()
    row["record"] = rec.to_dict()
    return row


def build_capsule(directory: "str | Path", *, redact: Optional[List[str]] = None,
                  revisions: int = 3, tool_version: Optional[str] = "2.1.0") -> Bundle:
    """Write the synthetic capsule into ``directory`` and return its sealed Bundle."""
    _TOOL_VERSION[0] = tool_version
    root = Path(directory)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "records").mkdir(parents=True, exist_ok=True)
    retained = _dump({"q_cms": [1.0, 2.0, 3.0]})
    served = b"date,q_cms\n1989-10-01,1.0\n1989-10-02,2.0\n1989-10-03,3.0\n"
    (root / "data/streamflow_x.json").write_bytes(retained)
    (root / "data/served_streamflow_x.csv").write_bytes(served)
    retained_digest = "sha256:" + hashlib.sha256(retained).hexdigest()
    flow_out = digest({"out": "flow"})

    ev_flow = {"schema_version": 1, "data": {"n_days": 3}, "uncertainty": None}
    ev_sigs = {"schema_version": 1, "data": {"baseflow_index": UNC["value"]},
               "uncertainty": {"baseflow_index": UNC}}
    retained_files = [{"path": "session-data:x.data.streamflow_x.json", "digest": retained_digest, "role": "artifact"}]
    acq = [{"role": "precipitation", "mode": "internal_aihydro_data_fetch",
            "sources_cited_by_result": ["USGS NWIS", "aihydro-data precipitation router (GridMET)"]}]
    sig_inputs = [
        {"ref": "streamflow.1", "digest": flow_out, "role": "served_data"},
        {"ref": "streamflow.1#q_cms", "digest": digest({"col": "q_cms"}), "role": "served_data"},
        {"ref": "session-data:x.data.streamflow_x.json", "digest": retained_digest, "role": "served_data"},
    ]
    rows = {
        "start.1": _row("start.1", "start_session"),
        "watershed.1": _row("watershed.1", "delineate_watershed", key_outputs={"basin_ref": BASIN_REF}),
        "streamflow.1": _row("streamflow.1", "fetch_streamflow_data", output={"out": "flow"},
                             extra={"writer": "put_result", "call_run_id": "q.1", "retained_files": retained_files},
                             evidence=ev_flow),
        "q.1": _row("q.1", "fetch_streamflow_data", output={"out": "flow"},
                    extra={"writer": "post_run", "retained_files": retained_files}, evidence=ev_flow),
        "signatures.1": _row("signatures.1", "extract_hydrological_signatures", parents=["streamflow.1"],
                             input_refs=sig_inputs, output={"out": "sigs"},
                             extra={"writer": "put_result", "call_run_id": "sigs.1", "internal_acquisitions": acq},
                             evidence=ev_sigs),
        "sigs.1": _row("sigs.1", "extract_hydrological_signatures", parents=["streamflow.1"],
                       input_refs=sig_inputs, output={"out": "sigs"},
                       extra={"writer": "post_run", "internal_acquisitions": acq}, evidence=ev_sigs),
        "claim.1": _row("claim.1", "add_claim"),
        "promo.1": _row("promo.1", "promote_claim_to_registry", status="error", error_summary="APPROVAL_REQUIRED"),
    }
    bodies = {rid: {k: v for k, v in row.items() if k != "record"} for rid, row in rows.items()}
    for rid in redact or []:                       # privacy stub: record kept, body withheld
        rec = rows[rid]["record"]
        rows[rid] = {"redacted_for_privacy": True, "run_id": rid, "session_id": SID, "timestamp": _T[rid],
                     "tool_name": rows[rid]["tool_name"], "record_digest": rec["record_digest"],
                     "entry_digest": rec["extra"]["entry_digest"], "reason": "withheld for privacy (fixture)",
                     "record": rec}
    (root / "run_log.json").write_bytes(_dump(rows))

    content = lambda n: {  # noqa: E731
        "schema": "aihydro.claim_revision/2", "text": "The baseflow index is 0.585 (90% CI 0.571-0.599).",
        "claim_type": "empirical_result", "status": ["draft", "supported", "supported"][n % 3],
        "scope": {"basins": ["01013500"], "metric": "baseflow_index",
                  "basin_refs": [{"id": BASIN_REF["id"], "label": "01013500"}]},
        "evidence_spans": [{"source_type": "run", "source_id": "sigs.1", "metric_ref": "baseflow_index"}],
        "limitations": ["synthetic fixture"], "revision_marker": n}
    revs: List[dict] = []
    prev = None
    for n in range(revisions):
        c = content(n)
        rev = ClaimRevision(session_id=SID, claim_id=CLAIM_ID, revision=n, revision_digest=digest(c), content=c,
                            cause={"tool": "add_claim" if n == 0 else "update_claim_status", "reason": "created" if n == 0 else "status_update"},
                            actor={"kind": "package", "id": "aihydro-tools"}, supersedes=prev,
                            recorded_at=f"2026-10-03T10:00:0{5 + n}.500000Z").seal()
        prev = rev.revision_digest
        revs.append(rev.to_dict())
    (root / "records/claim_revisions.json").write_bytes(_dump(revs))
    claim_view = {"id": CLAIM_ID, "claim": "The baseflow index is 0.585 (90% CI 0.571-0.599).", "status": "supported",
                  "scope": {"basin_refs": [{"id": BASIN_REF["id"], "label": "01013500"}]},
                  "evidence_spans": [{"source_type": "run", "source_id": "sigs.1", "metric_ref": "baseflow_index"}]}
    (root / "session.json").write_bytes(_dump({"session_id": SID, "claims": {CLAIM_ID: claim_view}}))
    (root / "replay.py").write_bytes(b"# stub standalone verifier for the synthetic fixture\n")
    (root / "README.md").write_bytes(b"# Synthetic capsule\nFixture for the RO-Crate tests.\n")

    skip = {"replay.py", "capsule_manifest.json", rc.CRATE_FILE, rc.BAGIT_FILE, "bundle.json"}
    listing = {p: f for p, f in rc.scan_files(root).items() if p not in skip}
    manifest = {"n_files": len(listing), "replay_status": "archive_integrity", "recomputation": "not_performed",
                "files": [{"path": p, "sha256": f["sha256"], "size": f["size"]} for p, f in sorted(listing.items())]}
    (root / "capsule_manifest.json").write_bytes(_dump(manifest))

    listing = {p: f for p, f in rc.scan_files(root).items() if p not in (rc.CRATE_FILE, rc.BAGIT_FILE, "bundle.json")}
    roles = {"capsule_manifest.json": "manifest", "replay.py": "verifier","run_log.json": "run_log", "session.json": "session", "README.md": "readme",
             "data/served_streamflow_x.csv": "served_data", "data/streamflow_x.json": "retained_data",
             "records/claim_revisions.json": "claim_revisions"}
    objects = [make_object_entry(p, "sha256:" + f["sha256"], f["size"], roles[p], media_type=f["media_type"],
                                 license="CC0-1.0" if p.startswith("data/") else None)
               for p, f in sorted(listing.items())]
    entries = []
    for rid, row in rows.items():
        entries.append(make_record_entry("run", rid, row["record"]["record_digest"],
                                         make_location("run_log.json", [rid, "record"]),
                                         make_location("run_log.json", [rid]), make_binding(bodies[rid])))
    for n, r in enumerate(revs):
        entries.append(make_record_entry("claim_revision", f"{CLAIM_ID}@{n}", r["record_digest"],
                                         make_location("records/claim_revisions.json", [n])))
    entries.append(make_record_entry("basin_ref", BASIN_REF["id"], digest(BASIN_REF),
                                     make_location("run_log.json", ["watershed.1", "key_outputs", "basin_ref"])))
    entries.append(make_record_entry("claim_view", CLAIM_ID, None, None,
                                     make_location("session.json", ["claims", CLAIM_ID]), make_binding(claim_view)))
    sealed_n = len(entries) - 1
    cov = make_coverage(sealed_n - len(redact or []), sealed_n, redact or [], withheld_ids=redact or [])
    replay_sha = hashlib.sha256((root / "replay.py").read_bytes()).hexdigest()
    bundle = Bundle(
        session_id=SID, objects=objects, records=entries, created_at=CREATED,
        exporter={"name": "aihydro-core test exporter", "version": "0.2.4"},
        replay={"status": "archive_integrity", "manifest_status": "archive_integrity",
                "checked_status": "archive_integrity",
                "assessor": {"name": "aihydro-core test verifier", "version": "0.2.4", "sha256": replay_sha}},
        coverage=cov,
        run_rows=make_run_rows(run_log_rows=len(rows), sealed=len(rows) - len(redact or []),
                               withheld_for_privacy=len(redact or [])),
        gates=[{"run_id": "promo.1", "code": "APPROVAL_REQUIRED", "outcome": "error"}],
    ).seal()
    (root / "bundle.json").write_bytes(_dump(bundle.to_dict()))
    records, bods, files = rc.load_inputs(root, bundle)
    rc.write_crate(rc.to_rocrate(bundle, records, bods, files), root)
    rc.write_manifest_sha256(root)
    return bundle
