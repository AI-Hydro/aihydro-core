"""
Uncertainty protocol for aihydro-core.

Provides the abstract contract (UncertaintyProvider Protocol, UncertaintyEstimate
vocabulary) and re-exports the concrete bootstrap implementations from the
private ``_bootstrap`` module (which requires numpy — install [science] extra).

Design
------
UncertaintyEstimate is a plain dict (not TypedDict) so domain packages can
add extra keys (e.g. "p_value", "degrees_of_freedom") without breaking the
core contract. The minimum required keys are validated by
``estimate_has_required_keys()``.

UncertaintyResult is a TypedDict (stricter; returned by the bootstrap functions)
that satisfies the UncertaintyEstimate contract.

The UncertaintyProvider Protocol is satisfied by any callable that accepts
a data object and returns an UncertaintyEstimate dict — including
``bootstrap_ci`` and ``block_bootstrap_ci`` defined in ``_bootstrap.py``.
"""
from __future__ import annotations

from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable
from typing import Literal


# ---------------------------------------------------------------------------
# Uncertainty method vocabulary
# ---------------------------------------------------------------------------

UncertaintyMethod = Literal[
    "bootstrap",        # non-parametric resampling with replacement
    "block_bootstrap",  # block-resampling for autocorrelated series
    "analytical",       # closed-form CI (e.g. normal approximation)
    "expert",           # expert elicitation (qualitative CI)
    "none",             # explicitly no uncertainty estimated
]

# Minimum required keys in every UncertaintyEstimate:
#   value   : float   — point estimate (median or mean of bootstrap distribution)
#   ci_low  : float   — lower bound of the confidence interval
#   ci_high : float   — upper bound of the confidence interval
#   method  : str     — one of UncertaintyMethod
#   n       : int     — bootstrap samples or observation count

_ESTIMATE_REQUIRED_KEYS = frozenset({"value", "ci_low", "ci_high", "method", "n"})

UncertaintyEstimate = dict  # dict[str, Any] with at least _ESTIMATE_REQUIRED_KEYS


def estimate_has_required_keys(estimate: "dict[str, Any]") -> bool:
    """Return True if the estimate dict carries all minimum-required keys."""
    return _ESTIMATE_REQUIRED_KEYS.issubset(estimate.keys())


def estimate_is_valid(estimate: "dict[str, Any]") -> bool:
    """
    Return True if the estimate is structurally valid.

    Checks:
    - All required keys present
    - ci_low <= value <= ci_high (or ci_low and ci_high are both NaN)
    - n >= 1
    """
    if not estimate_has_required_keys(estimate):
        return False
    try:
        import math
        v, lo, hi = float(estimate["value"]), float(estimate["ci_low"]), float(estimate["ci_high"])
        n = int(estimate["n"])
        if math.isnan(lo) and math.isnan(hi):
            return n >= 1
        return lo <= v <= hi and n >= 1
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# UncertaintyProvider Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class UncertaintyProvider(Protocol):
    """
    Protocol satisfied by any callable that can estimate uncertainty.

    Concrete implementations (defined below in this module):
      - ``bootstrap_ci(fn, data, **kwargs)`` — IID resampling
      - ``block_bootstrap_ci(fn, data, **kwargs)`` — for autocorrelated series

    Both return UncertaintyEstimate dicts.
    """

    def __call__(self, data: "Any", **kwargs: "Any") -> "UncertaintyEstimate":
        """
        Compute an uncertainty estimate for the given data.

        Must return a dict with at least the five required keys:
        value, ci_low, ci_high, method, n.
        """
        ...


# ---------------------------------------------------------------------------
# Null estimate (for tools that cannot compute uncertainty)
# ---------------------------------------------------------------------------

def null_estimate(reason: str = "not computed") -> "UncertaintyEstimate":
    """
    Return a sentinel UncertaintyEstimate for results with no CI.

    Use when: a tool result is qualitative, the sample is too small for
    bootstrap, or the domain is non-stochastic. The ``none`` method signals
    to the promotion gate that no CI was attempted.
    """
    import math
    return {
        "value": math.nan,
        "ci_low": math.nan,
        "ci_high": math.nan,
        "method": "none",
        "n": 0,
        "reason": reason,
    }


_BOOTSTRAP_EXPORTS = {
    "UncertaintyResult",
    "bootstrap_ci",
    "block_bootstrap_ci",
    "bootstrap_dict",
}


def __getattr__(name: str):
    """Lazily load numpy-backed bootstrap implementations on first access."""
    if name in _BOOTSTRAP_EXPORTS:
        from . import _bootstrap

        return getattr(_bootstrap, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_BOOTSTRAP_EXPORTS))


if TYPE_CHECKING:
    from ._bootstrap import (
        UncertaintyResult,
        bootstrap_ci,
        block_bootstrap_ci,
        bootstrap_dict,
    )
