"""
Round-trip verification of an exported capsule directory.

``verify_crate(directory)`` re-derives everything it can from the files on
disk and trusts nothing the crate says about itself:

1. ``bundle.json``: identity (``bundle_id`` names ``{schema, session_id,
   objects, records}``) and seal.
2. Every bundle object: file present, sha256 and size equal; ``objects`` equal
   to the capsule manifest's ``files`` when ``capsule_manifest.json`` exists
   (M6: three file indices must not drift).
3. Every record: located, seal re-verified (``verify_record_dict``,
   ``verify_claim_revision_dict``, ``verify_chain`` per claim, basin id from
   its anchor), declared digest equal, body binding (``aihydro.entry/1``)
   re-verified and tied to the sealed ``extra.entry_digest``.
4. Coverage: the not-verified set must equal the bundle's declared
   ``unverifiable_ids`` exactly. A declared unverifiable record is honest
   partiality, not a failure; an undeclared one is a failure.
5. The crate is **regenerated** from bundle + records + files and byte-compared
   with the shipped ``ro-crate-metadata.json`` (M1). Determinism is the
   integrity check for the crate itself. The licence is the one input that is
   an exporter choice, not derivable evidence, so it is read from the shipped
   crate.
6. ``manifest-sha256.txt`` (BagIt-style), if present, covers every file but
   itself and every digest matches.

A passing verification shows integrity (the files, records and crate are
internally consistent and unchanged). It does not show origin.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from aihydro_core.export.rocrate import (
    BAGIT_FILE,
    CRATE_FILE,
    claim_links_problem,
    claim_stub_problem,
    derive_gates,
    dumps_crate,
    find_irregular,
    find_symlinks,
    load_inputs,
    run_stub_problem,
    scan_files,
    to_rocrate,
)
from aihydro_core.records import (
    UNSEALED_KINDS,
    Bundle,
    BundleError,
    basin_id_from_anchor,
    coverage_complete,
    digest,
    entry_digest,
    read_legacy_replay_status,
    replay_rank,
    resolve_location,
    split_location,
    verify_basin_ref_dict,
    verify_binding,
    verify_claim_revision_dict,
    verify_record_dict,
)

BUNDLE_FILE = "bundle.json"
MANIFEST_FILE = "capsule_manifest.json"
VERIFIER_FILE = "replay.py"
#: Files that are not bundle objects: the bundle itself, the crate and the bag manifest.
NON_OBJECT_FILES = (BUNDLE_FILE, CRATE_FILE, BAGIT_FILE)


class Failure:
    def __init__(self, rule: str, message: str, entity: Optional[str] = None):
        self.rule, self.message, self.entity = rule, message, entity

    def __repr__(self) -> str:
        return f"Failure({self.rule}, {self.entity!r}, {self.message!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "entity": self.entity, "message": self.message}


class VerifyResult:
    def __init__(self) -> None:
        self.failures: List[Failure] = []
        self.unverifiable_ids: List[str] = []
        self.notes: List[str] = []
        self.records_verified = 0
        self.records_total = 0

    @property
    def ok(self) -> bool:
        return not self.failures

    def fail(self, rule: str, message: str, entity: Optional[str] = None) -> None:
        self.failures.append(Failure(rule, message, entity))

    @property
    def rules(self) -> List[str]:
        return sorted({f.rule for f in self.failures})

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "failures": [f.to_dict() for f in self.failures],
                "unverifiable_ids": self.unverifiable_ids, "notes": self.notes,
                "records_verified": self.records_verified, "records_total": self.records_total}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _basin_id_ok(rec: Mapping[str, Any]) -> bool:
    """The id must be the anchor's id. Run-log rows hold a *summary* of the BasinRef
    (``aliases`` and ``quality_flags`` as counts), which ``BasinRef.from_dict``
    rejects, so the anchor id is checked directly when the full parse fails."""
    if verify_basin_ref_dict(rec):
        return True
    try:
        return rec.get("schema") == "aihydro.basin_ref/1" and rec.get("id") == basin_id_from_anchor(rec["anchor"])
    except Exception:
        return False


def verify_crate(directory: "str | Path") -> VerifyResult:
    root = Path(directory)
    res = VerifyResult()

    # ---- 1. bundle
    try:
        bundle = Bundle.from_dict(_read_json(root / BUNDLE_FILE))
    except (OSError, ValueError, TypeError) as exc:
        res.fail("VER-BUNDLE-SEAL", f"cannot read a valid {BUNDLE_FILE}: {exc}")
        return res
    identity_ok = bundle.verify_identity()
    if not identity_ok:
        res.fail("VER-BUNDLE-IDENTITY", "bundle_id does not name {schema, session_id, objects, records} (or order is not canonical)")
    seal_ok = False
    try:
        seal_ok = bundle.record_digest is not None and bundle.compute_digest() == bundle.record_digest
    except Exception:
        pass
    if not seal_ok:
        res.fail("VER-BUNDLE-SEAL", "bundle record_digest does not match its content")

    # ---- 2. objects and files
    for link in find_symlinks(root):
        res.fail("VER-UNLISTED-FILE", "symlinks are never part of a capsule", link)
    for odd in find_irregular(root):
        res.fail("VER-UNLISTED-FILE", "not a regular file (FIFO, socket or device); capsules hold regular files only", odd)
    files = scan_files(root, strict=False)
    objects = {o["ref"]: o for o in bundle.objects}
    for path in sorted(set(files) - set(objects) - set(NON_OBJECT_FILES)):
        res.fail("VER-UNLISTED-FILE", "file is in the capsule but is not a bundle object (remove it, or re-export)", path)
    for ref, o in sorted(objects.items()):
        f = files.get(ref)
        if f is None:
            res.fail("VER-FILE-DIGEST", "bundle object is missing from the capsule", ref)
        elif "sha256:" + f["sha256"] != o["digest"] or f["size"] != o["size"]:
            res.fail("VER-FILE-DIGEST", "file bytes differ from the digest/size the bundle sealed", ref)
    manifest_path = root / MANIFEST_FILE
    manifest: Any = None
    if manifest_path.is_file():
        try:
            manifest = _read_json(manifest_path)
            listed = {m["path"]: ("sha256:" + m["sha256"], m["size"]) for m in manifest["files"]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            manifest = None
            res.fail("VER-OBJECTS-MANIFEST", f"cannot read files from {MANIFEST_FILE}: {exc}")
        else:
            # objects == manifest files + the manifest itself + the verifier, exactly (M3)
            mine = {r: (o["digest"], o["size"]) for r, o in objects.items()}
            for path in sorted(set(listed) | set(mine)):
                if path in (MANIFEST_FILE, VERIFIER_FILE):
                    continue
                if listed.get(path) != mine.get(path):
                    res.fail("VER-OBJECTS-MANIFEST", "bundle.objects and the manifest files disagree", path)
            for path in (MANIFEST_FILE, VERIFIER_FILE):
                if path not in objects:
                    res.fail("VER-OBJECTS-MANIFEST", f"{path} must be a bundle object (it carries the capsule's "
                                                     "self-description or verifier)", path)
    else:
        res.fail("VER-OBJECTS-MANIFEST", f"{MANIFEST_FILE} is missing")
    # the verifier the crate names must be a file in this capsule
    assessor = (bundle.replay or {}).get("assessor")
    if isinstance(assessor, dict):
        named = assessor.get("url") if assessor.get("url") in files else VERIFIER_FILE
        if not assessor.get("sha256"):
            res.fail("VER-ASSESSOR", f"replay.assessor must carry the sha256 of {named}")
        elif named not in files:
            res.fail("VER-ASSESSOR", f"the verifier file {named} is not in the capsule", named)
        elif files[named]["sha256"] != assessor["sha256"]:
            res.fail("VER-ASSESSOR", f"replay.assessor.sha256 is not the digest of the file it names ({named})", named)

    # ---- 2b. replay level is anchored to the on-disk manifest and to what was checked (M1)
    rp = bundle.replay or {}
    try:
        level_rank = replay_rank(rp["status"])
        if level_rank > replay_rank(rp["checked_status"]) or level_rank > replay_rank(rp["manifest_status"]):
            res.fail("VER-REPLAY-MANIFEST", "replay.status exceeds replay.manifest_status or replay.checked_status")
        if manifest is not None:
            m_level, m_complete = read_legacy_replay_status(manifest.get("replay_status"))
            if rp["manifest_status"] != m_level.value:
                res.fail("VER-REPLAY-MANIFEST",
                         f"replay.manifest_status {rp['manifest_status']!r} differs from the manifest's {m_level.value!r}")
            if level_rank > replay_rank(m_level):
                res.fail("VER-REPLAY-MANIFEST", "replay.status exceeds the level the on-disk manifest states")
            if not m_complete and coverage_complete(bundle.coverage):
                res.fail("VER-REPLAY-MANIFEST", "the manifest states a partial result but the bundle claims complete coverage")
    except (KeyError, ValueError) as exc:
        res.fail("VER-REPLAY-MANIFEST", f"cannot establish the replay level: {exc!r}")

    # ---- 3. records
    docs: Dict[str, Any] = {}

    def locate(loc: str) -> Tuple[bool, Any, str]:
        try:
            path, _t = split_location(loc)
        except BundleError as exc:
            return False, None, str(exc)
        if path not in objects:
            return False, None, f"location file {path!r} is not a sealed bundle object"
        if path not in docs:
            try:
                docs[path] = _read_json(root / path)
            except (OSError, ValueError):
                docs[path] = None
        if docs[path] is None:
            return False, None, f"location file {path!r} is unreadable"
        try:
            return True, resolve_location({path: docs[path]}, loc), ""
        except BundleError as exc:
            return False, None, str(exc)

    not_ok: Dict[Tuple[str, str], Tuple[str, str]] = {}   # (kind,id) -> (rule, reason)
    revisions: Dict[str, List[Tuple[Tuple[str, str], Dict[str, Any], bool]]] = {}
    content_checks: List[Tuple[str, str]] = []
    withheld_ok: set = set()    # (kind, id) of privacy-withheld stubs that proved everything they can

    for e in bundle.records:
        kind, eid = e["kind"], e["id"]
        key = (kind, eid)
        label = f"{kind}:{eid}"
        body = None
        if e.get("body_location"):
            okb, body, why = locate(e["body_location"])
            if not okb:
                if kind in UNSEALED_KINDS:
                    res.fail("VER-BINDING", f"body unresolvable: {why}", label)
                else:
                    not_ok[key] = ("VER-BINDING", f"body unresolvable: {why}")
                continue
        if kind == "run" and isinstance(body, dict) and body.get("redacted_for_privacy") is True:
            # withholding excuses only the body binding; the stub must still prove everything else
            problem = run_stub_problem(e, body, bundle.session_id)
            if problem is None:
                not_ok[key] = ("VER-BINDING", "body withheld for privacy")
                withheld_ok.add(key)
            else:
                not_ok[key] = problem
            continue
        if e.get("binding") is not None and not verify_binding(body, e["binding"]):
            if kind in UNSEALED_KINDS:
                res.fail("VER-BINDING", "body does not match its aihydro.entry/1 binding", label)
            else:
                not_ok[key] = ("VER-BINDING", "body does not match its aihydro.entry/1 binding")
            continue
        if kind in UNSEALED_KINDS:
            continue
        okr, rec, why = locate(e["record_location"])
        if not okr or not isinstance(rec, dict):
            not_ok[key] = ("VER-RECORD-SEAL", f"record unresolvable: {why}")
            continue
        if kind == "claim_revision" and rec.get("redacted_for_privacy") is True:
            problem = claim_stub_problem(e, rec, bundle.session_id)
            if problem is not None:
                not_ok[key] = problem
            else:                                   # its own seal is excused; the chain around it is not
                revisions.setdefault(rec["claim_id"], []).append((key, rec, True))
            continue
        if kind == "run":
            if not verify_record_dict(rec):
                not_ok[key] = ("VER-RECORD-SEAL", "run record seal does not verify")
            elif rec.get("record_digest") != e["record_digest"]:
                not_ok[key] = ("VER-RECORD-DIGEST", "record_digest differs from the bundle entry")
            elif rec.get("session_id") != bundle.session_id:
                not_ok[key] = ("VER-SESSION", "record session_id is missing or differs from the bundle's session_id")
            elif rec.get("run_id") != eid:
                not_ok[key] = ("VER-RECORD-DIGEST", "record run_id differs from the bundle entry id")
            elif e.get("binding") is not None and (
                    not isinstance(rec.get("extra"), dict)
                    or rec["extra"].get("entry_digest") != e["binding"]["digest"]):
                not_ok[key] = ("VER-BINDING", "the declared binding is not the sealed one: the record's "
                                              "extra.entry_digest is missing or differs from the binding digest")
            elif body is not None and isinstance(rec.get("extra"), dict) and rec["extra"].get("entry_digest") \
                    and entry_digest(body) != rec["extra"]["entry_digest"]:
                not_ok[key] = ("VER-BINDING", "body does not match the sealed extra.entry_digest")
        elif kind == "claim_revision":
            if not verify_claim_revision_dict(rec):
                not_ok[key] = ("VER-RECORD-SEAL", "claim revision seal does not verify")
            elif rec.get("record_digest") != e["record_digest"]:
                not_ok[key] = ("VER-RECORD-DIGEST", "record_digest differs from the bundle entry")
            elif rec.get("session_id") != bundle.session_id:
                not_ok[key] = ("VER-SESSION", "record session_id is missing or differs from the bundle's session_id")
            elif eid != f"{rec.get('claim_id')}@{rec.get('revision')}":
                not_ok[key] = ("VER-RECORD-DIGEST", "claim revision id differs from claim_id@revision")
            else:
                revisions.setdefault(rec["claim_id"], []).append((key, rec, False))
        elif kind == "basin_ref":
            if digest(rec) != e["record_digest"] or not _basin_id_ok(rec) or rec.get("id") != eid:
                not_ok[key] = ("VER-RECORD-SEAL", "basin reference does not verify (digest, anchor id)")
            else:
                content_checks.append(key)
        else:  # approval and any later content-addressed kind: content digest only
            if digest(rec) != e["record_digest"]:
                not_ok[key] = ("VER-RECORD-SEAL", "content digest differs from the bundle entry")
            else:
                content_checks.append(key)

    # content-addressed kinds (basin_ref, approval) are not seals: they must lie inside a run body
    # that is bound to a sealed record that verified in this same pass (S1)
    bound_prefixes = []
    for e in bundle.records:
        if e["kind"] == "run" and ("run", e["id"]) not in not_ok and e.get("binding") and e.get("body_location"):
            bound_prefixes.append(split_location(e["body_location"]))
    for key in content_checks:
        path, toks = split_location(next(x for x in bundle.records if (x["kind"], x["id"]) == key)["record_location"])
        if not any(path == bp and toks[:len(bt)] == bt for bp, bt in bound_prefixes):
            not_ok[key] = ("VER-RECORD-SEAL", "content-addressed record does not lie inside a body bound to a "
                                              "verified sealed record")

    for claim_id, items in sorted(revisions.items()):
        items.sort(key=lambda it: it[1]["revision"])
        # every non-stub revision already verified on its own; check the links around any stub gap
        chain_problem = claim_links_problem([r for _k, r, _s in items])
        if chain_problem is not None:
            for k, _r, _s in items:
                not_ok[k] = ("VER-CHAIN", f"claim {claim_id}: {chain_problem}")
                withheld_ok.discard(k)
        else:
            for k, _r, is_stub in items:           # a stub excuses only itself
                if is_stub:
                    not_ok[k] = ("VER-RECORD-SEAL", "revision withheld for privacy")
                    withheld_ok.add(k)

    sealed = [e for e in bundle.records if e["kind"] not in UNSEALED_KINDS]
    bad_ids = sorted({eid for (_k, eid) in not_ok})
    res.records_total = len(sealed)
    res.records_verified = len(sealed) - len(not_ok)
    res.unverifiable_ids = bad_ids
    declared = (bundle.coverage or {}).get("unverifiable_ids", [])
    for (kind, eid), (rule, why) in sorted(not_ok.items()):
        if eid in declared:
            if (kind, eid) in withheld_ok:
                res.notes.append(f"{kind}:{eid} declared unverifiable ({rule}: {why})")
            else:
                # a declaration cannot launder a defect: only a privacy-withheld row is acceptable partiality
                res.fail("VER-UNVERIFIABLE", f"declared unverifiable but not withheld for privacy ({rule}: {why})",
                         f"{kind}:{eid}")
        else:
            res.fail(rule, why, f"{kind}:{eid}")
    cov = bundle.coverage or {}
    derived_withheld = sorted(eid for (_k, eid) in withheld_ok)
    if "withheld_ids" in cov and sorted(cov["withheld_ids"]) != derived_withheld:
        res.fail("VER-UNVERIFIABLE", f"declared withheld ids {sorted(cov['withheld_ids'])} differ from the privacy "
                                     f"stubs derived from stub shape and digests {derived_withheld}")
    if cov.get("records_total") != res.records_total or cov.get("records_verified") != res.records_verified \
            or sorted(declared) != bad_ids:
        res.fail("VER-COVERAGE",
                 f"declared coverage {cov.get('records_verified')}/{cov.get('records_total')} "
                 f"{declared} differs from recomputed {res.records_verified}/{res.records_total} {bad_ids}")

    # ---- 4a. run_rows.sealed must equal the run entries the bundle lists
    if bundle.run_rows is not None:
        n_runs = sum(1 for x in bundle.records if x["kind"] == "run")
        sealed_n, withheld_n = bundle.run_rows["sealed"], bundle.run_rows["withheld_for_privacy"]
        # A privacy-withheld row that kept its record digest is a run entry too (it lands in
        # unverifiable_ids) but is counted under withheld_for_privacy, not sealed; a withheld row
        # with no digest has no entry at all. So sealed <= run entries <= sealed + withheld.
        derived_run_stubs = sum(1 for (k, _i) in withheld_ok if k == "run")
        if derived_run_stubs > withheld_n:
            res.fail("VER-RUN-ROWS", f"{derived_run_stubs} run stubs derived but run_rows counts only "
                                     f"{withheld_n} withheld_for_privacy rows")
        if not sealed_n <= n_runs <= sealed_n + withheld_n:
            res.fail("VER-RUN-ROWS", f"run_rows says {sealed_n} sealed and {withheld_n} withheld rows, which cannot "
                                     f"account for the {n_runs} run records the bundle lists "
                                     f"(need sealed <= entries <= sealed + withheld_for_privacy)")

    # ---- 4b. gates are derived from verified bodies; the declared list must equal them (S2)
    try:
        recs_g, bods_g, _f = load_inputs(root, bundle, strict=False)
        derived = {(g["run_id"], g["code"]) for g in derive_gates(bundle, recs_g, bods_g)
                   if ("run", g["run_id"]) not in not_ok}
        declared_g = {(g["run_id"], g["code"]) for g in (bundle.gates or [])}
        if derived != declared_g:
            res.fail("VER-GATES", f"declared gates {sorted(declared_g)} differ from gates derived from the "
                                  f"verified row bodies {sorted(derived)}")
    except Exception as exc:  # pragma: no cover - defensive
        res.fail("VER-GATES", f"cannot derive gates: {exc!r}")

    # ---- 5. crate regeneration
    crate_path = root / CRATE_FILE
    if not crate_path.is_file():
        res.fail("VER-CRATE-REGEN", f"{CRATE_FILE} is missing")
    elif identity_ok and seal_ok:
        shipped = crate_path.read_bytes()
        license_value: Optional[str] = None
        try:
            for ent in json.loads(shipped.decode("utf-8")).get("@graph", []):
                if ent.get("@id") == "./":
                    lic = ent.get("license")
                    lid = lic.get("@id") if isinstance(lic, dict) else lic
                    if isinstance(lid, str) and lid != "#license-unspecified":
                        license_value = lid
        except (ValueError, AttributeError):
            pass
        try:
            records, bodies, files_now = load_inputs(root, bundle, strict=False)
            regenerated = dumps_crate(to_rocrate(bundle, records, bodies, files_now, license=license_value)).encode("utf-8")
        except Exception as exc:
            res.fail("VER-CRATE-REGEN", f"crate could not be regenerated: {type(exc).__name__}: {exc}")
        else:
            if regenerated != shipped:
                a, b = regenerated.decode("utf-8").splitlines(), shipped.decode("utf-8", "replace").splitlines()
                at = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                res.fail("VER-CRATE-REGEN",
                         f"shipped crate differs from the crate regenerated from bundle, records and files "
                         f"(first difference at line {at + 1}: shipped {b[at].strip()[:80]!r} vs regenerated "
                         f"{a[at].strip()[:80] if at < len(a) else '<end>'!r})")

    # ---- 5b. the structural/honesty validator is part of verification: one gate
    from aihydro_core.export.rocrate_validate import errors as _verrors
    from aihydro_core.export.rocrate_validate import validate_crate
    for f in _verrors(validate_crate(root)):
        res.fail("VER-VALIDATE", f"{f.rule}: {f.message}", f.entity)

    # ---- 6. BagIt-style manifest
    bag = root / BAGIT_FILE
    if bag.is_file():
        listed_bag: Dict[str, str] = {}
        for line in bag.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            h, _, p = line.partition("  ")
            listed_bag[p] = h
        actual = {p: f["sha256"] for p, f in scan_files(root, strict=False).items()}
        if crate_path.is_file():
            actual[CRATE_FILE] = hashlib.sha256(crate_path.read_bytes()).hexdigest()
        for p in sorted(set(listed_bag) | set(actual)):
            if listed_bag.get(p) != actual.get(p):
                res.fail("VER-BAGIT", f"{BAGIT_FILE} and the files disagree", p)
    return res
