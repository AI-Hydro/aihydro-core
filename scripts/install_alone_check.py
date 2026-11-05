"""Install-alone task for aihydro-core.

Run by ``.github/workflows/install-alone.yml`` with the *venv's* interpreter,
from a directory outside the checkout, after installing ONLY the built wheel
(``aihydro-core[science]``) and its PyPI dependencies. No sibling AI-Hydro
package is present, and every socket connection is refused.

Task: seal a result the way a downstream package would.
  1. canonical digest of a record is key-order independent and equals the
     SHA-256 of the canonical JSON bytes (recomputed here with hashlib);
  2. a ``HydroResult`` validates and round-trips through ``to_dict``;
  3. an IID bootstrap CI of the mean is reproducible for a fixed seed.
"""
from __future__ import annotations

import hashlib
import socket
import sys


def _block_network() -> None:
    def refuse(*_a, **_k):
        raise RuntimeError("network access attempted during an install-alone check")

    socket.socket.connect = refuse  # type: ignore[assignment]
    socket.create_connection = refuse  # type: ignore[assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]


def main() -> int:
    _block_network()
    import aihydro_core

    where = aihydro_core.__file__
    assert "site-packages" in where, f"imported from a source tree, not the wheel: {where}"

    from aihydro_core.records.canonical import canonical_json, digest

    a = {"gauge": "01638500", "q_mean": 12.5, "years": [2001, 2002]}
    b = {"years": [2001, 2002], "q_mean": 12.5, "gauge": "01638500"}
    assert digest(a) == digest(b), "digest depends on key order"
    assert digest(a) == "sha256:" + hashlib.sha256(canonical_json(a)).hexdigest()
    assert digest(a) != digest({**a, "q_mean": 12.6})

    from aihydro_core import HydroMeta, HydroResult

    meta = HydroMeta(tool="install_alone_check", version="0")
    res = HydroResult(data={"q_mean": 12.5}, meta=meta)
    assert res.to_dict()["data"] == {"q_mean": 12.5}

    import numpy as np
    from aihydro_core.science._bootstrap import bootstrap_ci

    x = np.arange(1.0, 101.0)
    r1 = bootstrap_ci(np.mean, x, n=200, random_state=7)
    r2 = bootstrap_ci(np.mean, x, n=200, random_state=7)
    assert r1 == r2, "bootstrap not reproducible for a fixed seed"
    assert r1["ci_low"] < float(x.mean()) < r1["ci_high"], r1

    print(f"aihydro-core {aihydro_core.__version__}: install-alone task OK ({where})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
