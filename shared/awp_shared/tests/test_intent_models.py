from awp_shared.config import load_config
from awp_shared.intent_models import INTENT_PAYLOAD_MODELS, get_payload_model


def test_every_intent_in_config_has_a_registered_payload_model() -> None:
    """Regression guard: catches drift between config/intents.yaml and intent_models.py."""
    load_config.cache_clear()
    intents = load_config("intents")
    for entry in intents:
        model = get_payload_model(entry["intent"])
        assert model.__name__ == entry["payload_model"], (
            f"{entry['intent']}: config says {entry['payload_model']!r}, "
            f"registry has {model.__name__!r}"
        )


def test_no_orphan_payload_models() -> None:
    """Every registered model should back a real intent (catches stale entries)."""
    load_config.cache_clear()
    intents = load_config("intents")
    known_intents = {entry["intent"] for entry in intents}
    assert set(INTENT_PAYLOAD_MODELS) == known_intents
