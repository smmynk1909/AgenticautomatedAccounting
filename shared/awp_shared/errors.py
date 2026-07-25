"""Typed exceptions mapping 1:1 onto ErrorInfo.code (doc 08 §0, doc 11 §1.5).

MCP servers raise these; `mcpc.MCP.call` catches the JSON error envelope on
the wire and re-raises the matching typed exception client-side, so agent
code can `except PermissionDeniedError` instead of string-matching codes.
"""

from __future__ import annotations

from typing import Any

from awp_shared.schemas import ErrorCode, ErrorInfo


class AwpError(Exception):
    code: ErrorCode = "INTERNAL"
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_error_info(self) -> ErrorInfo:
        return ErrorInfo(
            code=self.code, message=self.message, retryable=self.retryable, details=self.details
        )

    @classmethod
    def from_error_info(cls, info: ErrorInfo) -> "AwpError":
        return _CODE_TO_EXC.get(info.code, InternalError)(info.message, details=info.details)


class ValidationError(AwpError):
    code: ErrorCode = "VALIDATION"
    retryable = False


class NotFoundError(AwpError):
    code: ErrorCode = "NOT_FOUND"
    retryable = False


class PermissionDeniedError(AwpError):
    code: ErrorCode = "PERMISSION_DENIED"
    retryable = False


class ConflictError(AwpError):
    code: ErrorCode = "CONFLICT"
    retryable = False


class ApprovalRequiredError(AwpError):
    code: ErrorCode = "APPROVAL_REQUIRED"
    retryable = False


class UpstreamError(AwpError):
    code: ErrorCode = "UPSTREAM"
    retryable = True


class InternalError(AwpError):
    code: ErrorCode = "INTERNAL"
    retryable = False


class AwpTimeoutError(AwpError):
    code: ErrorCode = "TIMEOUT"
    retryable = True


_CODE_TO_EXC: dict[ErrorCode, type[AwpError]] = {
    "VALIDATION": ValidationError,
    "NOT_FOUND": NotFoundError,
    "PERMISSION_DENIED": PermissionDeniedError,
    "CONFLICT": ConflictError,
    "APPROVAL_REQUIRED": ApprovalRequiredError,
    "UPSTREAM": UpstreamError,
    "INTERNAL": InternalError,
    "TIMEOUT": AwpTimeoutError,
}
