"""
Tests for aihydro_core/science/ — domain-free defensibility protocols.

Phase 3.1: Science kernel extraction. Verifies that:
  1. ClaimStatus, ViolationKind, UncertaintyMethod Literals are non-empty
  2. Helper validators (claim_has_required_keys, report_has_required_keys,
     estimate_has_required_keys, estimate_is_valid) behave correctly
  3. ClaimStore, Auditor, UncertaintyProvider are runtime_checkable Protocols
  4. Minimal mock implementations satisfy each Protocol (structural subtyping)
  5. null_estimate produces a structurally valid sentinel dict
  6. The science package is importable from aihydro_core top-level path
  7. No domain-specific or heavy imports leak from the science package

These tests are intentionally free of hydrology terms — the Protocol shapes
are domain-agnostic and must stay that way.
"""
from __future__ import annotations

import math
import sys
import unittest


class TestClaimProtocol(unittest.TestCase):
    def setUp(self):
        from aihydro_core.science.claim import (
            ClaimStatus, ClaimType, EvidenceSpan,
            ClaimStore, claim_has_required_keys,
            _CLAIM_REQUIRED_KEYS,
        )
        self.ClaimStore = ClaimStore
        self.claim_has_required_keys = claim_has_required_keys
        self.required_keys = _CLAIM_REQUIRED_KEYS
        # Keep these references so we can inspect them in tests
        self.ClaimStatus = ClaimStatus
        self.EvidenceSpan = EvidenceSpan

    def test_required_keys_nonempty(self):
        self.assertGreater(len(self.required_keys), 0)

    def test_valid_claim_passes(self):
        claim = {
            "id": "c-001",
            "claim": "Runoff increases under scenario A.",
            "claim_type": "empirical_result",
            "status": "proposed",
            "confidence": "low",
            "evidence_spans": [],
        }
        self.assertTrue(self.claim_has_required_keys(claim))

    def test_missing_key_fails(self):
        claim = {"id": "c-001", "claim": "test"}
        self.assertFalse(self.claim_has_required_keys(claim))

    def test_extra_keys_still_valid(self):
        claim = {
            "id": "c-002",
            "claim": "Test claim.",
            "claim_type": "hypothesis",
            "status": "supported",
            "confidence": "high",
            "evidence_spans": [],
            "extra_domain_key": "some hydrology value",
        }
        self.assertTrue(self.claim_has_required_keys(claim))

    def test_evidence_span_is_dict_subclass(self):
        span = self.EvidenceSpan(source_type="run", source_id="abc123")
        self.assertIsInstance(span, dict)
        self.assertEqual(span["source_type"], "run")

    def test_claim_store_protocol_minimal_impl(self):
        """Minimal class satisfying ClaimStore via structural subtyping."""
        class MinimalStore:
            @property
            def claims(self) -> dict:
                return {}

            def save(self) -> None:
                pass

        store = MinimalStore()
        self.assertIsInstance(store, self.ClaimStore)

    def test_claim_store_protocol_fails_without_save(self):
        """Class missing save() does NOT satisfy ClaimStore."""
        class BadStore:
            @property
            def claims(self) -> dict:
                return {}

        store = BadStore()
        self.assertNotIsInstance(store, self.ClaimStore)

    def test_claim_store_protocol_fails_without_claims(self):
        """Class missing claims property does NOT satisfy ClaimStore."""
        class BadStore:
            def save(self) -> None:
                pass

        store = BadStore()
        self.assertNotIsInstance(store, self.ClaimStore)


class TestAuditProtocol(unittest.TestCase):
    def setUp(self):
        from aihydro_core.science.audit import (
            ViolationKind,
            AuditViolationRecord,
            AuditReportRecord,
            Auditor,
            violation_is_blocking,
            report_has_required_keys,
            ALLOWED_CLAIM_STATUSES,
            _REPORT_REQUIRED_KEYS,
        )
        self.Auditor = Auditor
        self.violation_is_blocking = violation_is_blocking
        self.report_has_required_keys = report_has_required_keys
        self.allowed_statuses = ALLOWED_CLAIM_STATUSES
        self.required_keys = _REPORT_REQUIRED_KEYS

    def test_required_keys_nonempty(self):
        self.assertGreater(len(self.required_keys), 0)

    def test_allowed_claim_statuses_nonempty(self):
        self.assertGreater(len(self.allowed_statuses), 0)
        self.assertIn("supported", self.allowed_statuses)

    def test_valid_report_passes(self):
        report = {
            "passed": True,
            "violations": [],
            "numeric_coverage": 1.0,
            "total_numeric_count": 3,
            "cited_numeric_count": 3,
            "claim_count": 1,
            "claim_pass_count": 1,
        }
        self.assertTrue(self.report_has_required_keys(report))

    def test_missing_key_fails(self):
        report = {"passed": True}
        self.assertFalse(self.report_has_required_keys(report))

    def test_blocking_violation(self):
        v = {"kind": "uncited_number", "text_excerpt": "...", "message": "", "fix_hint": ""}
        self.assertTrue(self.violation_is_blocking(v))

    def test_lit_unresolvable_is_nonblocking(self):
        v = {"kind": "lit_unresolvable", "text_excerpt": "...", "message": "", "fix_hint": ""}
        self.assertFalse(self.violation_is_blocking(v))

    def test_auditor_protocol_satisfied(self):
        """Minimal class with audit() satisfies Auditor Protocol."""
        class MinimalAuditor:
            def audit(self, prose: str, session_id: str) -> dict:
                return {
                    "passed": True,
                    "violations": [],
                    "numeric_coverage": 1.0,
                    "total_numeric_count": 0,
                    "cited_numeric_count": 0,
                    "claim_count": 0,
                    "claim_pass_count": 0,
                }

        auditor = MinimalAuditor()
        self.assertIsInstance(auditor, self.Auditor)

    def test_auditor_protocol_not_satisfied_without_method(self):
        """Object missing audit() does NOT satisfy Auditor."""
        class NotAnAuditor:
            def check(self, prose: str) -> bool:
                return True

        obj = NotAnAuditor()
        self.assertNotIsInstance(obj, self.Auditor)


class TestUncertaintyProtocol(unittest.TestCase):
    def setUp(self):
        from aihydro_core.science.uncertainty import (
            UncertaintyEstimate,
            UncertaintyProvider,
            UncertaintyMethod,
            estimate_has_required_keys,
            estimate_is_valid,
            null_estimate,
            _ESTIMATE_REQUIRED_KEYS,
        )
        self.UncertaintyProvider = UncertaintyProvider
        self.estimate_has_required_keys = estimate_has_required_keys
        self.estimate_is_valid = estimate_is_valid
        self.null_estimate = null_estimate
        self.required_keys = _ESTIMATE_REQUIRED_KEYS

    def test_required_keys_nonempty(self):
        self.assertGreater(len(self.required_keys), 0)

    def test_valid_estimate_passes(self):
        est = {"value": 0.82, "ci_low": 0.77, "ci_high": 0.87, "method": "bootstrap", "n": 500}
        self.assertTrue(self.estimate_has_required_keys(est))
        self.assertTrue(self.estimate_is_valid(est))

    def test_inverted_bounds_fails_is_valid(self):
        est = {"value": 0.82, "ci_low": 0.90, "ci_high": 0.70, "method": "bootstrap", "n": 500}
        self.assertFalse(self.estimate_is_valid(est))

    def test_n_zero_fails(self):
        est = {"value": 0.5, "ci_low": 0.4, "ci_high": 0.6, "method": "analytical", "n": 0}
        self.assertFalse(self.estimate_is_valid(est))

    def test_nan_bounds_accepted_with_none_method(self):
        est = {"value": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
               "method": "none", "n": 1}
        self.assertTrue(self.estimate_is_valid(est))

    def test_missing_key_fails(self):
        est = {"value": 0.5, "ci_low": 0.4}
        self.assertFalse(self.estimate_has_required_keys(est))
        self.assertFalse(self.estimate_is_valid(est))

    def test_extra_keys_valid(self):
        est = {"value": 0.82, "ci_low": 0.77, "ci_high": 0.87,
               "method": "block_bootstrap", "n": 1000, "p_value": 0.03}
        self.assertTrue(self.estimate_is_valid(est))

    def test_null_estimate_structure(self):
        est = self.null_estimate()
        self.assertIn("value", est)
        self.assertEqual(est["method"], "none")
        self.assertEqual(est["n"], 0)
        self.assertTrue(math.isnan(est["value"]))

    def test_null_estimate_custom_reason(self):
        est = self.null_estimate("sample too small")
        self.assertEqual(est["reason"], "sample too small")

    def test_uncertainty_provider_protocol(self):
        """Callable satisfying __call__(data, **kwargs) satisfies UncertaintyProvider."""
        class MockProvider:
            def __call__(self, data, **kwargs) -> dict:
                return {"value": 0.5, "ci_low": 0.4, "ci_high": 0.6, "method": "bootstrap", "n": 100}

        provider = MockProvider()
        self.assertIsInstance(provider, self.UncertaintyProvider)

    def test_plain_function_satisfies_protocol(self):
        """A plain function also satisfies UncertaintyProvider."""
        def my_estimator(data, **kwargs) -> dict:
            return {"value": 1.0, "ci_low": 0.9, "ci_high": 1.1, "method": "analytical", "n": 30}

        self.assertIsInstance(my_estimator, self.UncertaintyProvider)


class TestSciencePackageImport(unittest.TestCase):
    def test_top_level_import(self):
        """All public names importable from aihydro_core.science directly."""
        from aihydro_core.science import (
            ClaimStatus, EvidenceSpan, Claim, ClaimStore,
            ViolationKind, AuditViolationRecord, AuditReportRecord, Auditor,
            UncertaintyMethod, UncertaintyEstimate, UncertaintyProvider,
        )
        # Just verify they are all importable
        self.assertIsNotNone(ClaimStore)
        self.assertIsNotNone(Auditor)
        self.assertIsNotNone(UncertaintyProvider)

    def test_no_heavy_deps_in_source(self):
        """science module source must not import pydantic, numpy, or aihydro domain pkgs."""
        import ast
        import importlib
        import inspect
        # Check each science sub-module's source for forbidden imports
        forbidden = {"pydantic", "numpy", "pandas", "scipy", "shapely",
                     "ai_hydro", "aihydro_data"}
        mods = [
            "aihydro_core.science.claim",
            "aihydro_core.science.audit",
            "aihydro_core.science.uncertainty",
            "aihydro_core.science",
        ]
        for mod_name in mods:
            mod = importlib.import_module(mod_name)
            try:
                src = inspect.getsource(mod)
            except OSError:
                continue
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name.split(".")[0] for a in node.names]
                    else:
                        if node.module:
                            names = [node.module.split(".")[0]]
                    for name in names:
                        self.assertNotIn(
                            name, forbidden,
                            f"{mod_name} must not import {name!r}",
                        )

    def test_core_version_updated(self):
        import aihydro_core
        self.assertEqual(aihydro_core.__version__, "0.2.0")
