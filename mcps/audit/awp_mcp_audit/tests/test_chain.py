from datetime import datetime, timezone

from awp_shared.audit_mw import AuditEvent

from awp_mcp_audit.chain import event_day, merkle_root, record_hash


def _event(**overrides: object) -> AuditEvent:
    defaults: dict[str, object] = dict(
        ts=datetime(2026, 7, 25, 10, 0, 0, tzinfo=timezone.utc),
        agent_id="FIN-1",
        server="finance",
        tool="post_journal",
        input_hash="a" * 64,
        output_hash="b" * 64,
        latency_ms=12.5,
        ok=True,
    )
    defaults.update(overrides)
    return AuditEvent(**defaults)  # type: ignore[arg-type]


def test_event_day_extracts_utc_date() -> None:
    assert event_day(_event()) == "2026-07-25"


def test_record_hash_is_deterministic() -> None:
    ev = _event()
    assert record_hash(ev, seq=1) == record_hash(ev, seq=1)


def test_record_hash_changes_if_seq_changes() -> None:
    ev = _event()
    assert record_hash(ev, seq=1) != record_hash(ev, seq=2)


def test_record_hash_changes_if_any_field_changes() -> None:
    ev1 = _event(ok=True)
    ev2 = _event(ok=False)
    assert record_hash(ev1, seq=1) != record_hash(ev2, seq=1)


def test_merkle_root_empty_is_well_defined() -> None:
    assert merkle_root([]) == merkle_root([])
    assert len(merkle_root([])) == 64


def test_merkle_root_is_order_sensitive() -> None:
    h1 = record_hash(_event(tool="t1"), seq=1)
    h2 = record_hash(_event(tool="t2"), seq=2)
    assert merkle_root([h1, h2]) != merkle_root([h2, h1])


def test_merkle_root_changes_if_any_hash_changes() -> None:
    h1 = record_hash(_event(tool="t1"), seq=1)
    h2 = record_hash(_event(tool="t2"), seq=2)
    h2_tampered = record_hash(_event(tool="t2-tampered"), seq=2)
    assert merkle_root([h1, h2]) != merkle_root([h1, h2_tampered])


def test_merkle_root_handles_odd_count() -> None:
    hashes = [record_hash(_event(tool=f"t{i}"), seq=i) for i in range(3)]
    root = merkle_root(hashes)
    assert len(root) == 64
