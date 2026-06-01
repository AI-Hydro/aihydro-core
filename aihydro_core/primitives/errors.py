"""
Shared error types for all aihydro-core blocks and consuming packages.
"""
from __future__ import annotations


class ToolError(Exception):
    """
    A structured error returned by any aihydro tool or block.

    Carries a machine-readable code and a teaching message — mirrors the
    reliability middleware pattern from arg_repair.py. Callers can either
    raise this or call .to_dict() to surface it as a tool response envelope.
    """

    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": True,
            "code": self.code,
            "message": self.message,
            **self.details,
        }


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
