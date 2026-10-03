"""
RO-Crate projection of a sealed Bundle (ADR-005, slice 5).

``to_rocrate`` is a *pure projection*: Bundle + the records and bodies it
points at + a file map in, one JSON-LD dict out. No store is created and
nothing sealed is rewritten. Determinism is the integrity check for the crate
itself (M1): ``verify_crate`` regenerates the crate from ``bundle.json``, the
records and the files, then byte-compares it with the shipped
``ro-crate-metadata.json``.

Modelling decisions (all from the slice-5 plan, "Lead adoption"):

- RO-Crate **1.3** context and descriptor; Process Run Crate **0.6** as
  ``conformsTo`` (M3). The workflow-run context is *not* added: it remaps
  ``sha256`` (C14). File ``sha256`` is bare hex (``schema:sha256``).
- ``conformsTo`` lists no AI-Hydro profile (M4): the profile IRI is
  unregistered until OPEN-8. The few AI-Hydro terms are defined in the graph
  under :data:`PROFILE_NS` (a single constant, marked unregistered).
- One ``CreateAction`` per *tool call*: the two sealed records of one call
  (``extra.call_run_id`` pairing a ``put_result`` row with its ``post_run``
  row) are one action carrying both record digests (C4).
- A claim states its basis: a sealed revision, or "working view, unsealed"
  (M7). A statistic is projected only from a body whose binding verifies
  (``aihydro.entry/1``, M2); the claim ``prov:wasDerivedFrom`` that statistic,
  which is a ``result`` of the producing action (M5). No ``wasGeneratedBy``.
- Replay status is an ``AssessAction`` the exporter performed on itself, with
  the coverage counts; it is mirrored on the root. Integrity is not origin
  (C7): the root says so.
- Aliases are ``identifier`` PropertyValues on the outlet Place and are never
  ``sameAs`` (R3).

Stdlib + ``aihydro_core.records`` only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import quote

from aihydro_core.records import (
    GATE_CODES,
    GATE_OUTCOMES,
    Bundle,
    BundleError,
    ReplayStatus,
    coverage_complete,
    replay_rank,
    resolve_location,
    split_location,
    verify_binding,
)

ROCRATE_CONTEXT = "https://w3id.org/ro/crate/1.3/context"
ROCRATE_SPEC = "https://w3id.org/ro/crate/1.3"
PRC_PROFILE = "https://w3id.org/ro/wfrun/process/0.6"
#: Required ``url`` of every SoftwareApplication (rocrate-validator ro-crate-1.3 check 32.2).
#: Tool calls are dispatched by the aihydro-tools MCP server; ORG_URL is the fallback.
TOOLS_URL = "https://github.com/AI-Hydro/aihydro-tools"
ORG_URL = "https://github.com/AI-Hydro"
SPDX_BASE = "https://spdx.org/licenses/"
PROV_NS = "http://www.w3.org/ns/prov#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
CRATE_FILE = "ro-crate-metadata.json"
BAGIT_FILE = "manifest-sha256.txt"

#: UNREGISTERED namespace (OPEN-8). ``.invalid`` can never resolve, so no
#: reader is misled into thinking a profile page exists. Replace in one place
#: once the owner publishes an IRI.
PROFILE_NS = "https://ai-hydro.invalid/terms/0.1/"
PROFILE_STATUS = "unregistered: OPEN-8 has not published a resolvable IRI for this namespace"

STATO_CONFIDENCE_INTERVAL = "http://purl.obolibrary.org/obo/STATO_0000196"
STATO_CONFIDENCE_LEVEL = "http://purl.obolibrary.org/obo/STATO_0000561"

INTEGRITY_NOTICE = (
    "Integrity is not origin: digests and seals show that content is unchanged since it was "
    "sealed; they do not establish who produced it."
)
COMPLETED = "http://schema.org/CompletedActionStatus"
FAILED = "http://schema.org/FailedActionStatus"

#: Terms defined in-graph (RO-Crate 1.3 extension rule): IRI, label, comment.
TERMS: Dict[str, Tuple[str, str]] = {
    "contentDigest": (
        "Content digest",
        "sha256:<hex> digest of the JSON object this entity was projected from. Unlike recordDigest it is "
        "not a seal: the object is content-addressed and is trustworthy only because it lies inside a "
        "body that is bound to a sealed record.",
    ),
    "canonicalization": (
        "Canonicalization",
        "Name of the canonical encoding that the accompanying digest was computed under "
        "(for example aihydro.c14n/1, RFC 8785 JCS after tagging).",
    ),
    "recordDigest": (
        "Record digest",
        "sha256:<hex> seal of the sealed AI-Hydro record this entity was projected from. "
        "Re-verify it against the record, not against this crate.",
    ),
    "recordLocation": (
        "Record location",
        "Where the sealed record lives in this crate: relative file path, '#', then an RFC 6901 "
        "JSON Pointer (with ~0/~1 escaping).",
    ),
    "replayStatus": (
        "Replay status",
        "Strongest level of replay the exporter actually performed: not_performed, "
        "archive_integrity, cross_check, recomputed or independently_replicated. "
        "Integrity checks are never presented as recomputation.",
    ),
}

#: Top-level directories that mark a local absolute path. One list shared by the
#: projection, the validator and (by import) aihydro-tools' scrubber.
LOCAL_ROOTS = ("Users", "home", "private", "var", "tmp", "opt", "root", "mnt", "Volumes", "srv",
               "scratch", "etc")
_B = r"(?:^|[\s\"'(])"                  # boundary before a path ('/', ':' and '=' excluded: URLs, k=v text)
#: Local-path leak detector: POSIX roots, file:// URLs, Windows drive and UNC paths,
#: //server/share, ~/ and $HOME-style references.
PATH_PATTERN = re.compile(
    r"file://"
    r"|(?:^|[\s\"'(=:,;\[])/(?:" + "|".join(LOCAL_ROOTS) + r")/"
    r"|(?:^|[\s\"'(=,;\[])[A-Za-z]:(?:\\|/(?:Users|Windows|Documents|Program|home|tmp|temp)\b)"
    r"|" + _B + r"//[A-Za-z0-9_-]+/[^/\s]+"             # //server/share; a dotted host is a protocol-relative URL
    r"|\\\\[^\\\s]+\\[^\\\s]+"
    r"|" + _B + r"~(?:[A-Za-z_][A-Za-z0-9_-]*)?/[A-Za-z._]"          # ~/notes, ~alice/x; not "~/-" or "~/2"
    r"|\$\{?HOME\b|%USERPROFILE%|%HOMEPATH%"
)

_MEDIA_TYPES = {
    ".json": "application/json", ".csv": "text/csv", ".md": "text/markdown", ".py": "text/x-python",
    ".txt": "text/plain", ".yml": "application/yaml", ".yaml": "application/yaml",
    ".bib": "application/x-bibtex", ".png": "image/png", ".svg": "image/svg+xml",
    ".geojson": "application/geo+json", ".nc": "application/x-netcdf",
}


# ----------------------------------------------------------------- id helpers
def frag(*parts: str) -> str:
    """Percent-encoded fragment @id: ``#`` + parts joined with ``-``."""
    return "#" + "-".join(quote(p, safe="-._~") for p in parts)


def file_id(path: str) -> str:
    """Percent-encoded relative @id of a capsule file."""
    return quote(path, safe="/-._~")


def record_key(kind: str, id: str) -> str:
    """Key into the ``records`` / ``bodies`` maps handed to :func:`to_rocrate`."""
    return f"{kind}:{id}"


def ref(id_: str) -> Dict[str, str]:
    return {"@id": id_}


def _refs(ids: Iterable[str]) -> Any:
    """Absent, single ref, or sorted list of refs (stable shape)."""
    uniq = sorted(set(ids))
    if not uniq:
        return None
    return ref(uniq[0]) if len(uniq) == 1 else [ref(i) for i in uniq]


def _one_or_many(values: Iterable[Any]) -> Any:
    uniq = sorted(set(values), key=lambda v: json.dumps(v, sort_keys=True))
    if not uniq:
        return None
    return uniq[0] if len(uniq) == 1 else uniq


def _safe_text(s: str) -> str:
    return "[local path withheld]" if PATH_PATTERN.search(s) or s.startswith("/") else s


def media_type_for(path: str) -> Optional[str]:
    """Pinned extension table (``mimetypes`` varies by platform, so it is not used)."""
    dot = path.rfind(".")
    return _MEDIA_TYPES.get(path[dot:].lower()) if dot >= 0 else None


def iso_ms(ts: Optional[str]) -> Optional[str]:
    """``2026-10-03T10:00:04.000101Z`` -> ``2026-10-03T10:00:04.000+00:00``.

    Process Run Crate validators accept only ``YYYY-MM-DDTHH:MM:SS[.mmm]+HH:MM``
    for ``endTime``; the sealed record keeps the exact value. Fractions are
    truncated, never rounded.
    """
    if not isinstance(ts, str):
        return ts
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$", ts)
    if not m:
        return ts
    frac = f".{(m.group(2) + '000')[:3]}" if m.group(2) else ""
    return m.group(1) + frac + ("+00:00" if m.group(3) == "Z" else m.group(3))


def _license_entity(g: "_Graph", lic: str) -> str:
    """Contextual CreativeWork for a licence given as an SPDX id or an http(s) URL."""
    lid = lic if lic.startswith("http") else SPDX_BASE + quote(lic, safe="-._+") + ".html"
    name = lid.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".html"):
        name = name[:-5]
    return g.add({"@id": lid, "@type": "CreativeWork", "name": name,
                  "description": f"Licence {name}. The licence text is at {lid}."})


_FILE_DESCRIPTIONS = {
    "bundle.json": "Sealed AI-Hydro Bundle (aihydro.bundle/1): content-addressed objects and located records.",
    "capsule_manifest.json": "Capsule manifest: per-file digests and the exporter's replay status.",
    "replay.py": "Standalone stdlib verifier shipped with the capsule.",
}


def _sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]


def _pv(id_: str, name: str, value: Any, *, property_id: Optional[str] = None,
        description: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    e: Dict[str, Any] = {"@id": id_, "@type": "PropertyValue", "name": name, "value": value}
    if property_id is not None:
        e["propertyID"] = property_id
    if description is not None:
        e["description"] = description
    e.update({k: v for k, v in extra.items() if v is not None})
    return e


class _Graph:
    def __init__(self) -> None:
        self.ents: Dict[str, Dict[str, Any]] = {}

    def add(self, ent: Dict[str, Any]) -> str:
        ent = {k: v for k, v in ent.items() if v is not None}
        existing = self.ents.get(ent["@id"])
        if existing is not None and existing != ent:
            raise ValueError(f"conflicting definitions for @id {ent['@id']!r}")
        self.ents[ent["@id"]] = ent
        return ent["@id"]


# --------------------------------------------------------------- projection
def to_rocrate(
    bundle: Bundle,
    records: Mapping[str, Mapping[str, Any]],
    bodies: Mapping[str, Mapping[str, Any]],
    files: Mapping[str, Mapping[str, Any]],
    *,
    license: Optional[str] = None,
) -> Dict[str, Any]:
    """Project a sealed ``bundle`` into an RO-Crate 1.3 / Process Run Crate 0.6 dict.

    ``records`` / ``bodies`` are keyed by :func:`record_key`. ``files`` maps a
    relative path to ``{"sha256": <bare hex>, "size": int, "media_type": str}``
    and holds every capsule file except the crate itself and the BagIt manifest
    (see :func:`scan_files`). Records the bundle declares unverifiable are
    projected as digest-only stubs; their content is never read.
    """
    if not isinstance(bundle, Bundle) or not bundle.verify():
        raise ValueError("to_rocrate needs a sealed Bundle that verifies")
    if not bundle.replay or not bundle.coverage:
        raise ValueError("the Bundle must carry its replay assessment and coverage")
    # Only archive-integrity-level facts can be projected: no recomputation or cross-check
    # entity exists in this projection yet, so a stronger level cannot be supported.
    if any(replay_rank(bundle.replay.get(k, bundle.replay["status"])) >= replay_rank(ReplayStatus.RECOMPUTED)
           for k in ("manifest_status", "checked_status")):
        raise ValueError("a manifest or checked level of recomputed or above needs a recomputation entity "
                         "that this projection cannot emit; refusing to state it")
    if replay_rank(bundle.replay["status"]) >= replay_rank(ReplayStatus.CROSS_CHECK):
        raise ValueError(f"replay level {bundle.replay['status']!r} needs a recomputation or cross-check "
                         "entity that this projection cannot emit; refusing to state it")
    for o in bundle.objects:
        f = files.get(o["ref"])
        if f is None or "sha256:" + f["sha256"] != o["digest"] or f["size"] != o["size"]:
            raise ValueError(f"file map does not match bundle object {o['ref']!r}")

    g = _Graph()
    unverifiable = set(bundle.coverage["unverifiable_ids"])
    hex_to_paths: Dict[str, List[str]] = {}
    for path in sorted(files):
        hex_to_paths.setdefault(files[path]["sha256"], []).append(path)
    obj_license = {o["ref"]: o.get("license") for o in bundle.objects}
    obj_role = {o["ref"]: o["role"] for o in bundle.objects}

    def file_for(digest_value: Optional[str]) -> Optional[str]:
        if not isinstance(digest_value, str) or not digest_value.startswith("sha256:"):
            return None
        paths = hex_to_paths.get(digest_value[7:])
        return file_id(paths[0]) if paths else None

    # ---- files
    for path in sorted(files):
        f = files[path]
        role = obj_role.get(path)
        ent = {"@id": file_id(path), "@type": "File", "name": path, "sha256": f["sha256"],
               "contentSize": str(f["size"]), "encodingFormat": f.get("media_type") or media_type_for(path),
               "description": _FILE_DESCRIPTIONS.get(path) or (f"Capsule file (role: {role})." if role else "Capsule file.")}
        if obj_license.get(path):
            ent["license"] = ref(_license_entity(g, obj_license[path]))
        g.add(ent)

    entries = {(e["kind"], e["id"]): e for e in bundle.records}

    def rec_of(kind: str, id_: str) -> Optional[Mapping[str, Any]]:
        return records.get(record_key(kind, id_))

    # ---- run groups: one action per tool call (C4)
    group_of: Dict[str, str] = {}
    groups: Dict[str, List[str]] = {}
    for (kind, rid), _e in sorted(entries.items()):
        if kind != "run" or rid in unverifiable:
            continue
        rec = rec_of("run", rid)
        if rec is None:
            raise ValueError(f"missing record for verified run {rid!r}")
        gk = ((rec.get("extra") or {}).get("call_run_id")) or rid
        group_of[rid] = gk
        groups.setdefault(gk, []).append(rid)
    for rid in sorted(r for (k, r) in entries if k == "run" and r in unverifiable):
        group_of[rid] = rid
        groups[rid] = [rid]

    output_pv: Dict[str, str] = {}
    for gk, rids in sorted(groups.items()):
        digs = [rec_of("run", r).get("output_digest") for r in rids
                if r not in unverifiable and rec_of("run", r) is not None]
        digs = [d for d in digs if d]
        if digs:
            output_pv[gk] = frag("output", gk)

    # ---- instruments
    def tool_entity(tool: str, version: Optional[str], env_digest: Optional[str]) -> str:
        tid = frag("tool", tool + (f"@{version}" if version else ""))
        ent: Dict[str, Any] = {"@id": tid, "@type": "SoftwareApplication", "name": tool, "version": version or "unversioned",
                               "url": TOOLS_URL}
        if env_digest:
            env = frag("env", env_digest.replace("sha256:", ""))
            g.add(_pv(env, "environment digest", env_digest, property_id="env_digest",
                      description="Digest of the recorded environment fingerprint "
                                  "(python, platform, distributions); the fingerprint is in capsule_manifest.json."))
            ent["additionalProperty"] = ref(env)
        return g.add(ent)

    sources_seen: Dict[str, str] = {}

    def source_entity(text: str) -> str:
        text = _safe_text(text)
        sid = frag("source", re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40], _sha8(text))
        sources_seen[sid] = text
        return g.add({"@id": sid, "@type": "CreativeWork", "name": text,
                      "description": "Source named by the sealed run record; request parameters are in the record's input digest."})

    action_ids: List[str] = []
    produced_files: set = set()
    gate_by_run: Dict[str, set] = {}
    for gt in derive_gates(bundle, records, bodies):
        gate_by_run.setdefault(gt["run_id"], set()).add(gt["code"])

    for gk, rids in sorted(groups.items()):
        aid = frag("action", gk)
        action_ids.append(aid)
        if rids[0] in unverifiable and len(rids) == 1:
            rid = rids[0]
            unknown_tool = g.add({"@id": frag("tool", "unverifiable-record"), "@type": "SoftwareApplication",
                                  "name": "unknown (record withheld or unverifiable)", "version": "unknown",
                                  "url": ORG_URL})
            g.add({"@id": aid, "@type": "CreateAction", "name": f"unverifiable record {rid}",
                   "description": "Digest-only stub: this record could not be verified or was withheld on export "
                                  "(see the replay assessment coverage). Nothing is claimed about its content.",
                   "instrument": ref(unknown_tool), "actionStatus": None,
                   "aihydro:recordDigest": entries[("run", rid)]["record_digest"]})
            continue
        recs = [(r, rec_of("run", r)) for r in rids]
        primary = next((rc for r, rc in recs if r == gk), recs[0][1])
        failed = any(rc.get("status") != "ok" for _r, rc in recs)
        codes = sorted({c for r in rids for c in gate_by_run.get(r, ())})
        tool = primary["tool"]
        instr = tool_entity(tool, primary.get("tool_version"), primary.get("env_digest"))
        objects: List[str] = []
        results: List[str] = []
        informed: List[str] = []
        # parameters digest
        if primary.get("input_digest"):
            pid = frag("params", gk)
            g.add(_pv(pid, f"parameters of {tool}", primary["input_digest"], property_id="input_digest",
                      description="Digest of the call parameters; the parameter values are not carried in this crate."))
            objects.append(pid)
        seen_in = set()
        for _r, rc in recs:
            for n, iref in enumerate(rc.get("input_refs") or []):
                key = (iref.get("ref"), iref.get("digest"))
                if key in seen_in:
                    continue
                seen_in.add(key)
                f_id = file_for(iref.get("digest"))
                base = (iref.get("ref") or "").split("#", 1)[0]
                up = group_of.get(base)
                if f_id:
                    objects.append(f_id)
                elif up and up in output_pv and iref.get("digest") == _output_digest_of(up, groups, rec_of, unverifiable) \
                        and "#" not in (iref.get("ref") or ""):
                    objects.append(output_pv[up])
                else:
                    iid = frag("input", gk, _sha8(json.dumps(key, sort_keys=True)))
                    g.add(_pv(iid, _safe_text(str(iref.get("ref"))), iref.get("digest"), property_id="input_digest",
                              description=f"Input reference (role {iref.get('role', 'other')}); digest only, not carried."))
                    objects.append(iid)
            for src in ((rc.get("extra") or {}).get("internal_acquisitions") or []):
                for s in src.get("sources_cited_by_result") or []:
                    if isinstance(s, str) and s:
                        objects.append(source_entity(s))
            for rf in ((rc.get("extra") or {}).get("retained_files") or []):
                f_id = file_for(rf.get("digest"))
                if f_id:
                    results.append(f_id)
                    produced_files.add(f_id)
            for p in rc.get("parents") or []:
                pg = group_of.get(p)
                if pg and pg != gk:
                    informed.append(frag("action", pg))
        if gk in output_pv:
            od = _output_digest_of(gk, groups, rec_of, unverifiable)
            g.add(_pv(output_pv[gk], f"output of {tool}", od, property_id="output_digest",
                      description="Digest of the canonical output (aihydro.c14n/1). The output itself is not carried in this crate."))
            results.append(output_pv[gk])
        ent: Dict[str, Any] = {
            "@id": aid, "@type": "CreateAction", "name": tool,
            "description": "Tool call recorded by the AI-Hydro run log. endTime is the sealed record's "
                           "recorded_at (transaction time), not an execution timestamp.",
            "instrument": ref(instr), "endTime": iso_ms(primary.get("recorded_at")),
            "actionStatus": FAILED if failed else COMPLETED,
            "object": _refs(objects), "result": None,  # results filled after claims
            "aihydro:recordDigest": _one_or_many(
                entries[("run", r)]["record_digest"] for r in rids),
            "aihydro:canonicalization": primary.get("canonicalization"),
            "prov:wasInformedBy": _refs(informed),
        }
        if failed and codes:
            ent["error"] = codes[0] if len(codes) == 1 else codes
        actor = primary.get("actor")
        if isinstance(actor, Mapping) and actor.get("kind") == "human" and actor.get("id"):
            pid = frag("actor", str(actor["id"]))
            g.add({"@id": pid, "@type": "Person", "name": _safe_text(str(actor["id"]))})
            ent["agent"] = ref(pid)
        g.ents[aid] = {k: v for k, v in ent.items() if v is not None}
        g.ents[aid]["_results"] = results

    # ---- places
    basin_ids: Dict[str, str] = {}

    def basin_hex(bid: str) -> str:
        pre = "aihydro:basin:sha256:"
        return bid[len(pre):] if bid.startswith(pre) else bid

    def place_for(bid: str) -> str:
        pid = frag("basin", basin_hex(bid))
        if pid in g.ents:
            return pid
        return g.add({"@id": pid, "@type": "Place", "name": f"Basin {bid}", "identifier": bid})

    for (kind, bid), e in sorted(entries.items()):
        if kind != "basin_ref":
            continue
        pid = frag("basin", basin_hex(bid))
        if bid in unverifiable or rec_of("basin_ref", bid) is None:
            g.add({"@id": pid, "@type": "Place", "name": f"Basin {bid}", "identifier": bid,
                   "description": "Basin reference could not be verified or was withheld; identifier only.",
                   "aihydro:contentDigest": e["record_digest"]})
            continue
        br = rec_of("basin_ref", bid)
        hexid = basin_hex(bid)
        outlet = br.get("outlet") or {}
        out_id = frag("outlet", hexid)
        geo_id = frag("outlet-geo", hexid)
        props = []
        for key, label in (("area_km2", "area_km2"), ("method", "delineation method"),
                           ("geometry_digest", "geometry digest"), ("quality_flags", "quality flags")):
            if br.get(key) is not None:
                pvid = frag("basin", hexid, key)
                g.add(_pv(pvid, label, br[key], property_id=key,
                          description="Count of quality flags recorded on the basin reference; the flags are in the run record."
                          if key == "quality_flags" else None))
                props.append(pvid)
        anchor = br.get("anchor") or {}
        g.add({"@id": pid, "@type": "Place", "name": f"Basin anchored at {anchor.get('element', bid)}",
               "identifier": bid, "containsPlace": ref(out_id), "additionalProperty": _refs(props),
               "aihydro:contentDigest": e["record_digest"], "aihydro:recordLocation": e["record_location"]})
        alias_ids = []
        for n, al in enumerate(outlet.get("aliases") or []):
            aid_ = frag("alias", hexid, str(al.get("scheme")), str(n))
            note = (f"relation={al.get('relation')}; source={al.get('source')}; verified={str(bool(al.get('verified'))).lower()}"
                    + ("" if al.get("verified") else "; unverified, so not asserted as sameAs"))
            g.add(_pv(aid_, f"{al.get('scheme')} identifier", al.get("id"), property_id=str(al.get("scheme")),
                      description=note))
            alias_ids.append(aid_)
        o_ent: Dict[str, Any] = {"@id": out_id, "@type": "Place", "name": f"Outlet of basin {bid}",
                                 "identifier": _refs(alias_ids)}
        if isinstance(outlet.get("lat"), (int, float)) and isinstance(outlet.get("lon"), (int, float)):
            g.add({"@id": geo_id, "@type": ["GeoCoordinates", "Geometry"], "name": f"Outlet coordinates of basin {bid}",
                   "latitude": outlet["lat"], "longitude": outlet["lon"],
                   "asWKT": f"POINT({outlet['lon']} {outlet['lat']})"})
            o_ent["geo"] = ref(geo_id)
        g.add(o_ent)
        basin_ids[bid] = pid

    # ---- claims
    def bound_body(rid: str) -> Optional[Mapping[str, Any]]:
        return _bound_run_body(entries.get(("run", rid)), rid in unverifiable,
                               records.get(record_key("run", rid)), bodies.get(record_key("run", rid)))

    def stat_for(span: Mapping[str, Any]) -> Optional[str]:
        if span.get("source_type") != "run" or not span.get("metric_ref"):
            return None
        gk = group_of.get(span.get("source_id"))
        if gk is None:
            return None
        metric = span["metric_ref"]
        for rid in sorted(groups.get(gk, ())):
            body = bound_body(rid)
            if body is None:
                continue
            unc = (body.get("evidence") or {}).get("uncertainty") if isinstance(body.get("evidence"), Mapping) else None
            u = unc.get(metric) if isinstance(unc, Mapping) else None
            if not isinstance(u, Mapping) or "value" not in u:
                continue
            sid, cid = frag("stat", gk, metric), frag("ci", gk, metric)
            ci_props = []
            if u.get("ci_level") is not None:
                clid = frag("cl", gk, metric)
                g.add(_pv(clid, "confidence level", u["ci_level"], property_id=STATO_CONFIDENCE_LEVEL))
                ci_props.append(clid)
            for key in ("n", "block_size"):
                if u.get(key) is not None:
                    pid = frag(key, gk, metric)
                    g.add(_pv(pid, key, u[key], property_id=key))
                    ci_props.append(pid)
            g.add({"@id": cid, "@type": "PropertyValue", "name": "confidence interval",
                   "additionalType": STATO_CONFIDENCE_INTERVAL, "minValue": u.get("ci_low"),
                   "maxValue": u.get("ci_high"), "additionalProperty": _refs(ci_props),
                   "description": _safe_text(str(u["scope"])) if u.get("scope") else None})
            g.add({"@id": sid, "@type": "PropertyValue", "name": metric, "value": u["value"],
                   "measurementMethod": u.get("method"), "valueReference": ref(cid),
                   "description": "Value and interval taken from the evidence body bound to a sealed run record "
                                  "(aihydro.entry/1)."})
            g.ents[frag("action", gk)]["_results"].append(sid)
            return sid
        return None

    claim_ents: List[str] = []

    def basis_pv(owner: str, kind_value: str, desc: str) -> str:
        return g.add(_pv(owner + "-basis", "claim basis", kind_value, property_id="claimBasis", description=desc))

    def claim_common(content: Mapping[str, Any]) -> Dict[str, Any]:
        spans = content.get("evidence_spans") or []
        stats = [s for s in (stat_for(sp) for sp in spans if isinstance(sp, Mapping)) if s]
        scope = content.get("scope") if isinstance(content.get("scope"), Mapping) else {}
        places = [place_for(b["id"]) for b in (scope.get("basin_refs") or [])
                  if isinstance(b, Mapping) and isinstance(b.get("id"), str)]
        return {"text": content.get("text", content.get("claim")),
                "creativeWorkStatus": content.get("status"),
                "spatialCoverage": _refs(places),
                "prov:wasDerivedFrom": _refs(stats)}

    for (kind, eid), e in sorted(entries.items()):
        if kind == "claim_revision":
            cid, _, rev = eid.rpartition("@")
            cent = frag("claim", cid, f"rev{rev}")
            if eid in unverifiable or rec_of("claim_revision", eid) is None:
                bp = basis_pv(cent, "sealed_revision", "Sealed revision whose record could not be verified or was withheld.")
                g.add({"@id": cent, "@type": "Claim", "name": f"Claim {cid} revision {rev} (unverifiable)",
                       "version": int(rev) if rev.isdigit() else None, "additionalProperty": ref(bp),
                       "aihydro:recordDigest": e["record_digest"], "aihydro:recordLocation": e["record_location"]})
            else:
                rec = rec_of("claim_revision", eid)
                bp = basis_pv(cent, "sealed_revision", "Projected from a sealed, append-only claim revision record.")
                prev = frag("claim", cid, f"rev{int(rev) - 1}") if rev.isdigit() and int(rev) > 0 else None
                ent = {"@id": cent, "@type": "Claim", "name": f"Claim {cid} revision {rev}",
                       "version": int(rev) if rev.isdigit() else None, "dateModified": rec.get("recorded_at"),
                       "additionalProperty": ref(bp), "aihydro:recordDigest": e["record_digest"],
                       "aihydro:recordLocation": e["record_location"],
                       "aihydro:canonicalization": rec.get("canonicalization"),
                       "prov:wasRevisionOf": ref(prev) if prev and ("claim_revision", f"{cid}@{int(rev) - 1}") in entries else None}
                ent.update(claim_common(rec.get("content") or {}))
                g.add(ent)
            claim_ents.append(cent)
        elif kind == "claim_view":
            body = bodies.get(record_key("claim_view", eid))
            if body is None or (e.get("binding") is not None and not verify_binding(body, e["binding"])):
                continue
            cent = frag("claim", eid, "view")
            bp = basis_pv(cent, "working_view_unsealed",
                          "Working view, unsealed: copied from the mutable session; its text and status may change "
                          "and carry no seal.")
            ent = {"@id": cent, "@type": "Claim", "name": f"Claim {eid} (working view, unsealed)",
                   "description": "Working view, unsealed. The status shown is the session's current value, not a sealed one.",
                   "additionalProperty": ref(bp)}
            ent.update(claim_common(body))
            g.add(ent)
            claim_ents.append(cent)

    # finalise action results
    for aid in action_ids:
        a = g.ents[aid]
        res = a.pop("_results", [])
        r = _refs(res)
        if r is not None:
            a["result"] = r
        else:
            a.pop("result", None)

    # ---- export action (C5)
    exporter = bundle.exporter or {"name": "unspecified exporter"}
    ex_tool = g.add({"@id": frag("tool", "exporter"), "@type": "SoftwareApplication", "name": exporter["name"],
                     "version": exporter.get("version"), "sha256": exporter.get("sha256"),
                     "url": exporter.get("url") or TOOLS_URL})
    export_results = [file_id(p) for p in sorted(files) if file_id(p) not in produced_files]
    export_id = frag("action", "export")
    g.add({"@id": export_id, "@type": "CreateAction", "name": "Capsule export",
           "description": "The export step. It created or copied every file not produced by a recorded tool call. "
                          "Its own run record, if one exists, is sealed after the capsule and is not part of this bundle.",
           "instrument": ref(ex_tool), "endTime": iso_ms(bundle.created_at), "actionStatus": COMPLETED,
           "result": _refs(export_results)})
    action_ids.append(export_id)

    # ---- replay AssessAction (C2)
    rp, cov = bundle.replay, bundle.coverage
    verifier = rp.get("assessor") or {"name": "unspecified verifier"}
    # a verifier that is a capsule file (replay.py) is addressed by its relative path
    verifier_url = verifier.get("url") or next(
        (file_id(p) for p in sorted(files) if verifier.get("sha256") and files[p]["sha256"] == verifier["sha256"]),
        TOOLS_URL)
    ver_id = g.add({"@id": frag("tool", "verifier"), "@type": "SoftwareApplication", "name": verifier["name"],
                    "version": verifier.get("version"), "sha256": verifier.get("sha256"),
                    "url": verifier_url})
    complete = coverage_complete(cov)
    level = rp["status"]
    cov_text = (f"{cov['records_verified']} of {cov['records_total']} sealed records verified"
                + ("" if complete else f"; partial coverage, unverifiable: {', '.join(cov['unverifiable_ids'])}"))
    pvs = [g.add(_pv(frag("replay", "level"), "replay status", level, property_id="replayStatus",
                     description="Strongest replay level the exporter actually performed.")),
           g.add(_pv(frag("replay", "manifest-level"), "manifest replay status",
                     rp.get("manifest_status", level), property_id="manifestStatus",
                     description="Level the capsule manifest states.")),
           g.add(_pv(frag("replay", "checked-level"), "checked replay status",
                     rp.get("checked_status", level), property_id="checkedStatus",
                     description="Level the exporter re-verified while building.")),
           g.add(_pv(frag("replay", "coverage"), "record coverage", cov["records_verified"],
                     property_id="records_verified", description=cov_text,
                     maxValue=cov["records_total"]))]
    replay_id = frag("assess", "replay")
    g.add({"@id": replay_id, "@type": "AssessAction", "name": "Replay assessment",
           "description": (f"Self-assessed by the exporter at export time, not by an independent party. "
                           f"Level {level}: {cov_text}. {'Complete.' if complete else 'This is a partial assessment.'} "
                           f"This is an integrity check; nothing was recomputed. {INTEGRITY_NOTICE}"),
           "instrument": ref(ver_id), "object": ref("./"), "endTime": iso_ms(bundle.created_at),
           "actionStatus": COMPLETED, "result": _refs(pvs)})
    action_ids.append(replay_id)

    # ---- licence, profile, terms
    lic_ref: Any
    if license:
        lic_ref = ref(_license_entity(g, license))
    else:
        lic_ref = ref(g.add({"@id": "#license-unspecified", "@type": "CreativeWork",
                             "name": "No licence selected by exporter",
                             "description": "The exporter did not select a licence for this crate; per-file licences, "
                                            "where known, are on the File entities."}))
    g.add({"@id": PRC_PROFILE, "@type": ["CreativeWork", "Profile"], "name": "Process Run Crate", "version": "0.6"})
    bid_pv = g.add(_pv("#bundle-id", "AI-Hydro bundle id", bundle.bundle_id, property_id="aihydro.bundle_id",
                       description="Content digest naming this Bundle: {schema, session_id, objects, records}."))
    for term, (label, comment) in sorted(TERMS.items()):
        g.add({"@id": PROFILE_NS + term, "@type": "rdf:Property", "name": label, "description": comment,
               "rdfs:label": label, "rdfs:comment": f"{comment} Namespace status: {PROFILE_STATUS}."})

    root = {
        "@id": "./", "@type": "Dataset",
        "name": f"AI-Hydro evidence bundle for session {_safe_text(bundle.session_id)}",
        "description": ("Deterministic RO-Crate projection of a sealed AI-Hydro Bundle. " + INTEGRITY_NOTICE
                        + f" Replay level: {level} ({cov_text}); see the replay assessment."),
        "datePublished": bundle.created_at, "license": lic_ref, "identifier": ref(bid_pv),
        "conformsTo": ref(PRC_PROFILE),
        "hasPart": _refs(file_id(p) for p in files),
        "mentions": _refs(list(action_ids) + claim_ents),
        "aihydro:replayStatus": level,
    }
    g.add(root)
    g.add({"@id": CRATE_FILE, "@type": "CreativeWork", "about": ref("./"), "conformsTo": ref(ROCRATE_SPEC)})

    graph = sorted(g.ents.values(), key=lambda e: e["@id"])
    return {
        "@context": [ROCRATE_CONTEXT, context_terms()],
        "@graph": graph,
    }


#: Compact keys used in the graph that the RO-Crate context does not define.
#: Each is declared as an explicit term (rocrate-validator ro-crate-1.3 check 4.1
#: requires every key to resolve through the @context, not merely have a prefix).
EXTRA_TERMS = {
    "prov:wasInformedBy": PROV_NS + "wasInformedBy",
    "prov:wasDerivedFrom": PROV_NS + "wasDerivedFrom",
    "prov:wasRevisionOf": PROV_NS + "wasRevisionOf",
    "rdfs:label": RDFS_NS + "label",
    "rdfs:comment": RDFS_NS + "comment",
}


def context_terms() -> Dict[str, str]:
    """The inline @context object: prefixes plus an explicit term for every compact key used."""
    ctx = {"aihydro": PROFILE_NS, "prov": PROV_NS, "rdf": RDF_NS, "rdfs": RDFS_NS}
    ctx.update({f"aihydro:{t}": PROFILE_NS + t for t in TERMS})
    ctx.update(EXTRA_TERMS)
    return ctx


def _bound_run_body(entry, unverifiable: bool, record, body) -> Optional[Mapping[str, Any]]:
    """The row body of a run, only if its binding is *the sealed one*: the bundle's binding
    verifies against the body AND equals ``record.extra.entry_digest`` (so the body is bound
    to the sealed record, not merely to the bundle)."""
    if entry is None or unverifiable or body is None or record is None:
        return None
    binding = entry.get("binding")
    if not verify_binding(body, binding):
        return None
    extra = record.get("extra")
    sealed = extra.get("entry_digest") if isinstance(extra, Mapping) else None
    return body if sealed == binding["digest"] else None


def derive_gates(bundle: Bundle, records: Mapping[str, Any], bodies: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Gate refusals found in verified, sealed-bound run bodies: ``error_summary`` equal to an
    allowlisted code. ``bundle.gates`` is only a declaration that must equal this set."""
    unverifiable = set((bundle.coverage or {}).get("unverifiable_ids", []))
    out = []
    for e in bundle.records:
        if e["kind"] != "run":
            continue
        rid = e["id"]
        rec = records.get(record_key("run", rid))
        body = _bound_run_body(e, rid in unverifiable, rec, bodies.get(record_key("run", rid)))
        code = body.get("error_summary") if body else None
        if code in GATE_CODES:
            out.append({"run_id": rid, "code": code,
                        "outcome": rec["status"] if rec.get("status") in GATE_OUTCOMES else "error"})
    return sorted(out, key=lambda g: (g["run_id"], g["code"]))


def _output_digest_of(gk, groups, rec_of, unverifiable) -> Optional[str]:
    for r in sorted(groups.get(gk, ())):
        if r in unverifiable:
            continue
        rc = rec_of("run", r)
        if rc is not None and rc.get("output_digest"):
            return rc["output_digest"]
    return None


# ------------------------------------------------------------ serialisation
def _normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [_normalise(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
    return value


def dumps_crate(crate: Mapping[str, Any]) -> str:
    """The pinned serialisation: indent 2, sorted keys, UTF-8, sorted arrays, trailing newline."""
    graph = _normalise(crate["@graph"])
    graph.sort(key=lambda e: e["@id"])
    out = {"@context": crate["@context"], "@graph": graph}
    return json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True, separators=(",", ": ")) + "\n"


def write_crate(crate: Mapping[str, Any], directory: "str | Path") -> Path:
    path = Path(directory) / CRATE_FILE
    path.write_bytes(dumps_crate(crate).encode("utf-8"))
    return path


# ------------------------------------------------------------------- inputs
def find_symlinks(directory: "str | Path") -> List[str]:
    """Relative paths of every symlink (file or directory) under ``directory``."""
    root = Path(directory)
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in list(dirnames) + list(filenames):
            full = Path(dirpath) / name
            if full.is_symlink():
                found.append(full.relative_to(root).as_posix())
    return sorted(found)


def find_irregular(directory: "str | Path") -> List[str]:
    """Relative paths of entries that are neither a regular file, a directory nor a symlink
    (FIFO, socket, device). They are never opened."""
    root = Path(directory)
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            full = Path(dirpath) / name
            if not full.is_symlink() and not full.is_file():
                found.append(full.relative_to(root).as_posix())
    return sorted(found)


def _walk_files(root: Path) -> List[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for name in filenames:
            full = Path(dirpath) / name
            if not full.is_symlink() and full.is_file():
                out.append(full)
    return sorted(out)


def scan_files(directory: "str | Path", *, strict: bool = True) -> Dict[str, Dict[str, Any]]:
    """The ``files`` map for a capsule directory.

    Every regular file under ``directory`` except the crate and the BagIt
    manifest, as ``{relpath: {sha256 (bare hex), size, media_type}}``. A symlink
    anywhere is an error (``ValueError``) unless ``strict=False`` (the verifier
    reports symlinks itself).
    """
    root = Path(directory)
    if strict:
        links = find_symlinks(root)
        if links:
            raise ValueError(f"capsule contains symlinks, which are never exported: {links}")
        odd = find_irregular(root)
        if odd:
            raise ValueError(f"capsule contains non-regular files (FIFO, socket, device): {odd}")
    out: Dict[str, Dict[str, Any]] = {}
    for p in _walk_files(root):
        rel = p.relative_to(root).as_posix()
        if rel in (CRATE_FILE, BAGIT_FILE):
            continue
        data = p.read_bytes()
        out[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                    "media_type": media_type_for(rel)}
    return out


def load_inputs(directory: "str | Path", bundle: Bundle, *, strict: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Resolve every bundle location from disk: ``(records, bodies, files)``.

    Records that cannot be resolved are simply absent (``verify_crate`` reports
    them); nothing here verifies a seal.
    """
    root = Path(directory)
    docs: Dict[str, Any] = {}

    def doc(path: str) -> Any:
        if path not in docs:
            try:
                docs[path] = json.loads((root / path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                docs[path] = _MISSING
        return docs[path]

    records: Dict[str, Any] = {}
    bodies: Dict[str, Any] = {}
    for e in bundle.records:
        key = record_key(e["kind"], e["id"])
        for loc_name, target in (("record_location", records), ("body_location", bodies)):
            loc = e.get(loc_name)
            if loc is None:
                continue
            try:
                path, _tokens = split_location(loc)
                d = doc(path)
                if d is _MISSING:
                    continue
                target[key] = resolve_location({path: d}, loc)
            except BundleError:
                continue
    return records, bodies, scan_files(root, strict=strict)


_MISSING = object()


def write_manifest_sha256(directory: "str | Path") -> Path:
    """BagIt-style ``manifest-sha256.txt``: ``<hex>  <path>`` for every file but itself."""
    root = Path(directory)
    links = find_symlinks(root)
    if links:
        raise ValueError(f"capsule contains symlinks, which are never exported: {links}")
    odd = find_irregular(root)
    if odd:
        raise ValueError(f"capsule contains non-regular files (FIFO, socket, device): {odd}")
    lines = []
    for p in _walk_files(root):
        rel = p.relative_to(root).as_posix()
        if rel != BAGIT_FILE:
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}")
    lines.sort(key=lambda s: s.split("  ", 1)[1])
    path = root / BAGIT_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":  # python -m aihydro_core.export.rocrate {validate,verify} DIR
    from aihydro_core.export.__main__ import main
    raise SystemExit(main())
