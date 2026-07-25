import pytest


@pytest.fixture(autouse=True)
def _dev_auth_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWP_DEV_JWT_SECRET", "test-service-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_APPROVAL_JWT_SECRET", "test-approval-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_JWT_ISSUER", "awp-test")
    # config/models.yaml interpolates ${MODEL_GATEWAY_URL} — needed by any
    # test that exercises full config validation (e.g. validate_all()).
    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://localhost:11434/v1")
