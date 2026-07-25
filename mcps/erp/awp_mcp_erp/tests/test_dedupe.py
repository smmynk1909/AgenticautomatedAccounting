from awp_mcp_erp.dedupe import find_duplicates


def _row(candidate_id: str, name: str, email: str | None = None, phone: str | None = None) -> dict:
    return {
        "id": candidate_id,
        "profile": {"name": name, "contact": {"email": email, "phone": phone}},
    }


def test_exact_email_match() -> None:
    existing = [_row("c1", "Asha Rao", email="asha.rao@example.com")]
    new_profile = {"name": "A. Rao", "contact": {"email": "Asha.Rao@Example.com"}}
    matches = find_duplicates(new_profile, existing)
    assert len(matches) == 1
    assert matches[0].reason == "email"
    assert matches[0].score == 1.0


def test_exact_phone_match_ignores_formatting() -> None:
    existing = [_row("c1", "Ravi Kumar", phone="+91 98765 43210")]
    new_profile = {"name": "Ravi K", "contact": {"phone": "9876543210"}}
    matches = find_duplicates(new_profile, existing)
    assert len(matches) == 1
    assert matches[0].reason == "phone"


def test_fuzzy_name_match_above_threshold() -> None:
    existing = [_row("c1", "Priyanka Sharma")]
    new_profile = {"name": "Priyanka Sharman", "contact": {}}
    matches = find_duplicates(new_profile, existing)
    assert len(matches) == 1
    assert matches[0].reason == "name_fuzzy"
    assert matches[0].score > 0.85


def test_dissimilar_name_no_match() -> None:
    existing = [_row("c1", "Priyanka Sharma")]
    new_profile = {"name": "John Smith", "contact": {}}
    matches = find_duplicates(new_profile, existing)
    assert matches == []


def test_no_existing_candidates_no_matches() -> None:
    assert find_duplicates({"name": "Anyone", "contact": {}}, []) == []
