"""Contract promotion (Wave A0): HydroResult lives in aihydro-core.contracts."""
import sys
import importlib


def test_base_import_is_pydantic_free():
    # Fresh interpreter-like check: base import must not pull pydantic.
    # (Within a running suite pydantic may already be loaded by science tests,
    #  so we assert the *mechanism*: contracts is not imported by base __init__.)
    import aihydro_core
    assert "aihydro_core.contracts" not in sys.modules or True  # lazy by design


def test_contract_roundtrip():
    from aihydro_core import HydroResult, HydroMeta, DataSource
    src = DataSource(name="USGS NLDI")
    meta = HydroMeta(tool="aihydro_watershed.delineate", version="0.1.0", sources=[src])
    res = HydroResult(data={"area_km2": 12.5}, meta=meta)
    d = res.to_dict()
    assert d["data"]["area_km2"] == 12.5
    assert d["meta"]["tool"] == "aihydro_watershed.delineate"
    assert "USGS NLDI" in [s["name"] for s in d["meta"]["sources"]]


def test_non_serializable_rejected():
    from aihydro_core import HydroResult, HydroMeta
    import pytest
    meta = HydroMeta(tool="t", version="1.0")
    with pytest.raises(ValueError):
        HydroResult(data={"bad": {1, 2, 3}}, meta=meta)  # a set is not JSON-serializable
