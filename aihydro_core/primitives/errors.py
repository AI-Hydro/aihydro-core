"""
Shared error types for all aihydro-core blocks and consuming packages.
"""
from __future__ import annotations


class ToolError(Exception):
    """
    A structured error returned by any aihydro tool or block.

    Unified superset of the original core (code/message/details) and the
    tool-facing (code/message/tool/recovery/alternatives) signatures.
    ``tool``, ``recovery``, and ``alternatives`` are keyword-only so the
    positional ``(code, message, details)`` form keeps working unchanged.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict | None = None,
        *,
        tool: str | None = None,
        recovery: str | None = None,
        alternatives: list[str] | None = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.tool = tool
        self.recovery = recovery
        self.alternatives = alternatives or []
        super().__init__(message)

    def to_dict(self) -> dict:
        d: dict = {
            "error": True,
            "code": self.code,
            "message": self.message,
            **self.details,
        }
        if self.tool is not None:
            d["tool"] = self.tool
        if self.recovery is not None:
            d["recovery"] = self.recovery
        if self.alternatives:
            d["alternatives"] = self.alternatives
        return d


class FeatureNotFoundError(ToolError):
    """
    Raised when a feature_id / name / ref cannot be resolved by FeatureRegistry.

    Message always tells the agent what to do next (register the feature, or
    call list_features to see available ids).
    """

    def __init__(self, ref: str, available: list[str] | None = None):
        hint = ""
        if available is not None:
            if available:
                hint = f" Available feature ids: {available}."
            else:
                hint = " No features registered yet — call register_feature() or delineate_watershed() first."
        super().__init__(
            code="FEATURE_NOT_FOUND",
            message=f"No feature found for ref={ref!r}.{hint}",
        )
        self.ref = ref
        self.available = available


class StoreError(ToolError):
    """Raised by Store implementations for persistence-layer errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(code="STORE_ERROR", message=message, details=details)
