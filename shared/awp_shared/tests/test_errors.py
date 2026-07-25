import pytest

from awp_shared.errors import AwpError, PermissionDeniedError, ValidationError


def test_to_error_info_round_trip() -> None:
    exc = ValidationError("bad payload", details={"field": "emp_id"})
    info = exc.to_error_info()
    assert info.code == "VALIDATION"
    assert info.retryable is False
    assert info.details == {"field": "emp_id"}

    restored = AwpError.from_error_info(info)
    assert isinstance(restored, ValidationError)
    assert restored.message == "bad payload"


def test_unknown_code_falls_back_to_internal_error() -> None:
    from awp_shared.schemas import ErrorInfo

    # model_construct bypasses Literal validation so we can simulate a code
    # this codebase doesn't know about (e.g. from a future server version).
    info = ErrorInfo.model_construct(
        code="NOT_A_REAL_CODE", message="x", retryable=False, details={}
    )
    restored = AwpError.from_error_info(info)
    assert restored.code == "INTERNAL"


def test_permission_denied_is_not_retryable() -> None:
    with pytest.raises(PermissionDeniedError) as excinfo:
        raise PermissionDeniedError("nope")
    assert excinfo.value.retryable is False
