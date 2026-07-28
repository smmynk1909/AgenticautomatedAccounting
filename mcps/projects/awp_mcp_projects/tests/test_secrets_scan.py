"""doc 05 §5.3: "secrets scanner blocks 100% of seeded credentials" — this
is that assertion, at the unit level, for every credential shape the
scanner claims to catch. `scripts/gitea_seed/config_sample.py` (the live-
verification fixture) uses the exact same synthetic AWS/GitHub values
tested here.
"""

from awp_mcp_projects.secrets_scan import redact_text, scan_text

_SEEDED_CREDENTIALS = {
    "aws_access_key_id": 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"',
    "aws_secret_access_key": 'AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"',
    "github_token": 'GITHUB_TOKEN = "ghp_1234567890abcdef1234567890abcdefEXAMPLE"',
    "slack_token": 'SLACK_TOKEN = "xoxb-1234567890-abcdefghijklmnop"',
    "private_key_header": "-----BEGIN RSA PRIVATE KEY-----",
    "generic_secret_assignment": 'api_key = "sk_live_abcdefghijklmnopqrstuvwx"',
}


def test_scan_text_catches_every_seeded_credential_shape() -> None:
    for kind, sample in _SEEDED_CREDENTIALS.items():
        findings = scan_text(sample)
        assert findings, f"expected a finding for {kind!r} in {sample!r}"


def test_scan_text_reports_correct_line_number() -> None:
    text = "line one\nline two\nAKIAIOSFODNN7EXAMPLE\n"
    findings = scan_text(text)
    assert findings[0].line == 3


def test_scan_text_clean_code_has_no_findings() -> None:
    text = "def add(a: int, b: int) -> int:\n    return a + b\n"
    assert scan_text(text) == []


def test_scan_text_preview_never_exposes_full_secret() -> None:
    findings = scan_text('AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"')
    for f in findings:
        assert "AKIAIOSFODNN7EXAMPLE" not in f.match_preview


def test_redact_text_removes_every_seeded_credential() -> None:
    for sample in _SEEDED_CREDENTIALS.values():
        redacted = redact_text(sample)
        assert "AKIA" not in redacted
        assert "ghp_" not in redacted
        assert "xoxb-" not in redacted
        assert "BEGIN RSA PRIVATE KEY" not in redacted


def test_redact_text_leaves_clean_code_untouched() -> None:
    text = "def add(a: int, b: int) -> int:\n    return a + b\n"
    assert redact_text(text) == text


def test_scan_text_finds_all_seeded_config_sample_credentials() -> None:
    # Mirrors scripts/gitea_seed/config_sample.py exactly — the live
    # verification fixture must actually be catchable by this scanner.
    text = (
        'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'
        'AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n'
        'GITHUB_TOKEN = "ghp_1234567890abcdef1234567890abcdefEXAMPLE"\n'
    )
    findings = scan_text(text)
    kinds = {f.kind for f in findings}
    assert "aws_access_key_id" in kinds
    assert "github_token" in kinds
