"""
Tests for aihydro_core.records — canonical encoding, digests, sealed run
records, environment fingerprint and replay vocabulary (ADR-001, ADR-005).
"""
from __future__ import annotations

import ast
import datetime as dt
import decimal
import enum
import sys
from pathlib import Path

import pytest

from aihydro_core.records import (
    CANONICALIZATION,
    RUN_SCHEMA,
    Actor,
    ArtifactRef,
    ReplayStatus,
    RunRecord,
    UnencodableError,
    canonical_json,
    digest,
    digest_bytes,
    digest_or_error,
    environment_fingerprint,
    input_ref,
    is_digest,
    verify_record_dict,
)


# ---------------------------------------------------------------- canonical
def test_digest_format_and_key_order_independence():
    a = digest({"b": 1, "a": [1, 2, {"z": None, "y": True}]})
    b = digest({"a": [1, 2, {"y": True, "z": None}], "b": 1})
    assert a == b
    assert is_digest(a) and a.startswith("sha256:") and len(a) == 71


def test_list_order_is_significant():
    assert digest([1, 2]) != digest([2, 1])


def test_non_finite_floats_are_tagged_not_rejected():
    enc = canonical_json({"x": float("nan"), "y": float("inf"), "z": float("-inf")})
    assert b'"$float":"nan"' in enc and b'"$float":"inf"' in enc and b'"$float":"-inf"' in enc
    assert digest(float("nan")) == digest(float("nan"))
    assert digest(float("inf")) != digest(float("-inf"))


def test_tagged_types_do_not_collide_with_strings():
    assert digest(dt.date(2020, 1, 1)) != digest("2020-01-01")
    assert digest(b"abc") != digest("abc")
    assert digest(decimal.Decimal("1.10")) != digest("1.10")


def test_user_dict_cannot_imitate_a_tag():
    real_nan = digest(float("nan"))
    fake_nan = digest({"$float": "nan"})
    assert real_nan != fake_nan


def test_int_keys_stringified_but_collisions_refused():
    assert digest({1: "a"}) == digest({"1": "a"})
    with pytest.raises(UnencodableError):
        canonical_json({1: "a", "1": "b"})


def test_unknown_types_raise_instead_of_str_fallback():
    class Abbreviated:
        """Mimics a DataFrame whose str() hides most of its content."""

        def __init__(self, rows):
            self.rows = rows

        def __str__(self):
            return f"<frame {len(self.rows)} rows ...>"

    with pytest.raises(UnencodableError):
        digest(Abbreviated([1, 2, 3]))
    d, err = digest_or_error({"frame": Abbreviated([1])})
    assert d is None and err.startswith("unencodable:") and "$.frame" in err


def test_sets_are_order_independent():
    assert digest({3, 1, 2}) == digest({2, 3, 1})
    assert digest({1, 2}) != digest([1, 2])


def test_enum_and_dataclass_encoding():
    class Color(str, enum.Enum):
        RED = "red"

    assert digest(Color.RED) == digest("red")
    ref = ArtifactRef(ref="a", digest=digest("x"))
    assert digest(ref) == digest({"ref": "a", "digest": digest("x"), "media_type": None,
                                  "license": None, "permission_status": None})


def test_digest_bytes_matches_hashlib():
    import hashlib

    assert digest_bytes(b"hello") == "sha256:" + hashlib.sha256(b"hello").hexdigest()


class _FakeDType:
    def __init__(self, s, hasobject=False):
        self.str = s
        self.hasobject = hasobject


class _FakeArray:
    """Duck-typed stand-in for a NumPy array so the test needs no NumPy."""

    def __init__(self, raw: bytes, shape, dtype="<f8"):
        self._raw, self.shape, self.dtype = raw, shape, _FakeDType(dtype)

    def tobytes(self):
        return self._raw


def test_array_like_full_content_no_aliasing():
    a = _FakeArray(b"\x00" * 8000, (1000,))
    b = _FakeArray(b"\x00" * 7992 + b"\x01" * 8, (1000,))
    assert digest(a) != digest(b)
    assert digest(_FakeArray(b"\x00" * 16, (2,))) != digest(_FakeArray(b"\x00" * 16, (2,), "<i8"))
    assert digest(_FakeArray(b"\x00" * 16, (2,))) != digest(_FakeArray(b"\x00" * 16, (1, 2)))


def test_numpy_arrays_and_scalars_when_available():
    np = pytest.importorskip("numpy")
    x = np.zeros(5000)
    y = x.copy()
    y[2500] = 1.0
    assert digest(x) != digest(y)
    assert digest(np.float64(1.5)) == digest(1.5)
    assert digest(np.int64(7)) == digest(7)
    assert digest(np.bool_(True)) == digest(True)
    assert digest(np.array(3.0)) == digest(3.0)
    assert digest(np.array([1, 2], dtype=np.int32)) != digest(np.array([1, 2], dtype=np.int64))


def test_pandas_objects_are_refused_not_stringified():
    pd = pytest.importorskip("pandas")
    with pytest.raises(UnencodableError):
        digest(pd.DataFrame({"q": range(100)}))
    with pytest.raises(UnencodableError):
        digest(pd.Series(range(100)))


# ---------------------------------------------------------------- RunRecord
def _record(**kw):
    base = dict(run_id="q.20261002.abc.0001", tool="fetch_streamflow_data", session_id="s1",
                input_digest=digest({"gauge_id": "01013500"}), output_digest=digest([1.0, 2.0]))
    base.update(kw)
    return RunRecord(**base)


def test_seal_verify_and_tamper_detection():
    rec = _record().seal()
    assert rec.schema == RUN_SCHEMA and rec.canonicalization == CANONICALIZATION
    assert rec.verify()
    d = rec.to_dict()
    assert verify_record_dict(d)
    d["output_digest"] = digest([1.0, 2.5])
    assert not verify_record_dict(d)


def test_unsealed_record_does_not_verify():
    assert not _record().verify()


def test_seal_is_idempotent():
    rec = _record().seal()
    first = rec.record_digest
    assert rec.seal().record_digest == first


def test_unknown_fields_round_trip_without_breaking_digest():
    d = _record().seal().to_dict()
    d["future_field"] = {"added_by": "a newer writer"}
    resealed = RunRecord.from_dict(d).seal()
    clone = RunRecord.from_dict(resealed.to_dict())
    assert clone.unknown == {"future_field": {"added_by": "a newer writer"}}
    assert clone.verify()
    assert clone.to_dict()["future_field"] == {"added_by": "a newer writer"}


def test_recorded_at_is_utc_z():
    assert _record().recorded_at.endswith("Z")


def test_validation_rejects_bad_values():
    with pytest.raises(ValueError):
        _record(status="maybe")
    with pytest.raises(ValueError):
        _record(input_digest="abc123")
    with pytest.raises(ValueError):
        _record(run_id="")
    with pytest.raises(ValueError):
        input_ref("run:x", "nothex", role="served_data")
    with pytest.raises(ValueError):
        input_ref("run:x", None, role="unknown_role")


def test_parents_input_refs_and_actor():
    parent = _record().seal()
    child = _record(
        run_id="sigs.20261002.abc.0002", tool="extract_hydrological_signatures",
        parents=[parent.run_id],
        input_refs=[input_ref(parent.run_id, parent.output_digest, role="served_data")],
        actor=Actor(kind="agent", id="assistant", model_id="example-model", client="vscode"),
    ).seal()
    d = child.to_dict()
    assert d["parents"] == [parent.run_id]
    assert d["input_refs"][0] == {"ref": parent.run_id, "digest": parent.output_digest, "role": "served_data"}
    assert d["actor"]["kind"] == "agent"
    assert child.verify()


def test_record_error_is_explicit():
    rec = _record(output_digest=None, record_error="unencodable: $.data: DataFrame").seal()
    assert rec.verify()
    assert rec.to_dict()["record_error"].startswith("unencodable")


def test_actor_and_artifact_validation():
    with pytest.raises(ValueError):
        Actor(kind="robot", id="x")
    with pytest.raises(ValueError):
        ArtifactRef(ref="a", digest="md5:abc")


# ---------------------------------------------------------------- env + replay
def test_environment_fingerprint_shape_and_missing_dists():
    fp, env_digest = environment_fingerprint(["aihydro-core", "definitely-not-installed-xyz"])
    assert fp["python"] and fp["platform"]
    assert fp["distributions"]["definitely-not-installed-xyz"] is None
    assert is_digest(env_digest) and env_digest == digest(fp)


def test_replay_status_vocabulary():
    assert ReplayStatus.ARCHIVE_INTEGRITY.value == "archive_integrity"
    assert [s.value for s in ReplayStatus] == [
        "not_performed", "archive_integrity", "cross_check", "recomputed", "independently_replicated",
    ]


# ---------------------------------------------------------------- stdlib-only guard
_RECORDS_DIR = Path(__file__).resolve().parent.parent / "aihydro_core" / "records"


@pytest.mark.skipif(sys.version_info < (3, 10), reason="sys.stdlib_module_names needs 3.10+")
def test_records_imports_only_stdlib_and_core():
    allowed = set(sys.stdlib_module_names) | {"aihydro_core", "__future__"}
    offenders = []
    for path in sorted(_RECORDS_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] not in allowed]
    assert not offenders, offenders
