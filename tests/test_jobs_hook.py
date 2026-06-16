"""
Tests for the artifact-dir provider hook (dependency-inversion seam).

This is the mechanism that replaced core's old upward import
(`from ai_hydro.session.store import _SESSIONS_DIR`). Domain layers register a
provider DOWN into core; `_resolve_artifact_dir` consults every registered
provider. These tests pin the contract so the inverted path can't silently rot:

  1. a registered provider's candidate dir is actually consulted + returned
  2. a misbehaving provider (raises) must not break resolution
  3. registration is idempotent (no duplicate consultation)
"""
from __future__ import annotations

import json
import uuid

import pytest

import aihydro_core.jobs as jobs
from aihydro_core.jobs import register_artifact_dir_provider, _resolve_artifact_dir


@pytest.fixture(autouse=True)
def _clean_providers():
    """Snapshot + restore the global provider list around each test."""
    saved = list(jobs._ARTIFACT_DIR_PROVIDERS)
    jobs._ARTIFACT_DIR_PROVIDERS.clear()
    yield
    jobs._ARTIFACT_DIR_PROVIDERS.clear()
    jobs._ARTIFACT_DIR_PROVIDERS.extend(saved)


def test_provider_dir_is_consulted(tmp_path):
    """A provider-supplied dir containing status.json must be resolved."""
    job_id = f"job_{uuid.uuid4().hex[:8]}"          # not in the registry
    run_dir = tmp_path / "ws" / "runs" / job_id
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(json.dumps({"status": "complete"}))

    register_artifact_dir_provider(lambda jid: [tmp_path / "ws" / "runs" / jid])

    resolved = _resolve_artifact_dir(job_id)
    assert resolved == run_dir, "provider's candidate dir was not consulted"


def test_misbehaving_provider_does_not_break_resolution():
    """A provider that raises must be swallowed, not propagated."""
    def _boom(jid):
        raise RuntimeError("provider blew up")

    register_artifact_dir_provider(_boom)
    # Unknown job, no valid candidate anywhere → None, but NO exception.
    assert _resolve_artifact_dir(f"job_{uuid.uuid4().hex[:8]}") is None


def test_registration_is_idempotent():
    """Registering the same provider twice must not duplicate it."""
    def _p(jid):
        return []

    register_artifact_dir_provider(_p)
    register_artifact_dir_provider(_p)
    assert jobs._ARTIFACT_DIR_PROVIDERS.count(_p) == 1


def test_register_returns_provider_for_decorator_use():
    """register_artifact_dir_provider returns fn so it works as a decorator."""
    def _p(jid):
        return []

    assert register_artifact_dir_provider(_p) is _p
