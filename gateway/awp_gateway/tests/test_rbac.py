"""RBAC matrix test — doc 12 §6 exit checklist item "RBAC matrix test
100%," previously an honest, documented gap (`deploy/runbooks/go-live-checklist.md`).

Every table below is written independently of `awp_gateway.rbac`'s own
internals (never imports `_ROLE_CATEGORIES` etc.) and enumerates every
role `config/roles.yaml` actually defines — not a hardcoded snapshot —
against every resource `rbac.py` gates: ticket categories
(`config/routing.yaml`), dashboards (one per role), and the payroll
view. A future edit that silently narrows or widens any role's access,
or a new role added to `config/roles.yaml` with no corresponding
decision made here, fails this test rather than shipping unnoticed.
"""

from __future__ import annotations

from awp_shared.auth import Principal
from awp_shared.config import load_config

from awp_gateway.rbac import can_view_dashboard_role, can_view_payroll, visible_categories

_ALL_ROLES: list[str] = [r["role"] for r in load_config("roles")]

# doc 07 §3.2's routing table's non-`confidential_subcategories` keys —
# every real ticket category an owning agent (or human queue) handles.
_ALL_CATEGORIES: list[str] = [
    k for k in load_config("routing") if k != "confidential_subcategories"
]

# --- Ticket category visibility --------------------------------------------
#
# Independently authored from doc 07 §3.2 (routing/ownership) + doc 00 §7
# (director/ceo cross-department oversight) + doc 07 §3's "SUP-1 has the
# widest read on tickets" — the same citations `rbac.py` itself carries,
# encoded here as data instead of imported as code.

_UNRESTRICTED_ROLES = frozenset({"support_lead", "support", "director", "ceo"})

_DEPARTMENT_CATEGORIES: dict[str, frozenset[str]] = {
    "admin_head": frozenset({"device", "access", "facilities", "records", "procurement"}),
    "admin": frozenset({"device", "access", "facilities", "records", "procurement"}),
    "hr_head": frozenset({"hr"}),
    "hr": frozenset({"hr"}),
    "recruiter": frozenset({"hr"}),
    "finance_head": frozenset({"payroll", "expense"}),
    "finance": frozenset({"payroll", "expense"}),
    "ops": frozenset({"delivery"}),
}

# Roles doc 07/09 never grant a department-level ticket view — self-service
# only (own tickets via `requester_id`, enforced by the router, not this
# module). Explicit here so a role silently missing from *both* this set
# and `_DEPARTMENT_CATEGORIES` is caught by the completeness check below.
_NO_DEPARTMENT_VISIBILITY_ROLES = frozenset({"manager", "employee", "dept_head"})


def test_every_config_role_has_a_ticket_visibility_decision() -> None:
    accounted_for = (
        _UNRESTRICTED_ROLES | set(_DEPARTMENT_CATEGORIES) | _NO_DEPARTMENT_VISIBILITY_ROLES
    )
    missing = set(_ALL_ROLES) - accounted_for
    assert not missing, (
        f"role(s) {missing} exist in config/roles.yaml but have no ticket-visibility "
        "decision in this test — add one before shipping, don't let it default silently"
    )


def test_ticket_category_visibility_matrix() -> None:
    for role in _ALL_ROLES:
        principal = Principal(sub=f"test-{role}", kind="user", roles=[role])
        visible = visible_categories(principal)

        if role in _UNRESTRICTED_ROLES:
            assert visible is None, (
                f"{role} should see every category (unrestricted), got {visible}"
            )
            continue

        expected = _DEPARTMENT_CATEGORIES.get(role, frozenset())
        assert visible == expected, f"{role}: expected {expected}, got {visible}"

        # Every category this role should NOT see stays hidden — the
        # positive assertion above already implies this for a frozenset
        # equality check, but spelled out per-category for a matrix test's
        # actual point: catching one wrong cell, not just a wrong row sum.
        for category in _ALL_CATEGORIES:
            expected_visible = category in expected
            actual_visible = category in visible if visible is not None else True
            assert actual_visible == expected_visible, (
                f"role={role!r} category={category!r}: "
                f"expected visible={expected_visible}, got {actual_visible}"
            )


def test_categories_with_no_owning_department_role_are_unrestricted_only() -> None:
    # it_support/cross_functional/unknown route to a human queue or ORCH-0,
    # not any of the four department role groups — confirm no department
    # role accidentally gained visibility into them.
    owned_categories = frozenset().union(*_DEPARTMENT_CATEGORIES.values())
    unowned = set(_ALL_CATEGORIES) - owned_categories
    assert unowned == {"it_support", "cross_functional", "unknown"}

    for role, categories in _DEPARTMENT_CATEGORIES.items():
        assert not (categories & unowned), f"{role} should not see any of {unowned}"


# --- Dashboard visibility ----------------------------------------------------


def test_every_config_role_dashboard_visibility_matrix() -> None:
    # Every (viewer_role, dashboard_role) pair: visible iff same role, or
    # the viewer holds an unrestricted-dashboard role (director/ceo).
    unrestricted_dashboard_roles = frozenset({"director", "ceo"})
    for viewer_role in _ALL_ROLES:
        principal = Principal(sub=f"test-{viewer_role}", kind="user", roles=[viewer_role])
        for dashboard_role in _ALL_ROLES:
            expected = dashboard_role == viewer_role or viewer_role in unrestricted_dashboard_roles
            actual = can_view_dashboard_role(principal, dashboard_role)
            assert actual == expected, (
                f"viewer={viewer_role!r} dashboard={dashboard_role!r}: "
                f"expected {expected}, got {actual}"
            )


# --- Payroll view --------------------------------------------------------


def test_payroll_view_matrix() -> None:
    # doc 06 §4 rule 4 + the payroll_run gate's own approver_roles
    # (config/gates.yaml) plus ceo (cross-department oversight, same
    # convention as everywhere else in this module).
    expected_payroll_viewers = frozenset({"finance_head", "director", "ceo"})
    for role in _ALL_ROLES:
        principal = Principal(sub=f"test-{role}", kind="user", roles=[role])
        expected = role in expected_payroll_viewers
        actual = can_view_payroll(principal)
        assert actual == expected, (
            f"role={role!r}: expected can_view_payroll={expected}, got {actual}"
        )


# --- Multi-role principals (realistic — dev_users.yaml seeds several,
# e.g. recruiter+hr) — the union/OR semantics, not just single-role cells.


def test_multi_role_principal_gets_the_union_of_each_roles_access() -> None:
    principal = Principal(sub="test-multi", kind="user", roles=["recruiter", "hr"])
    assert visible_categories(principal) == frozenset({"hr"})

    principal2 = Principal(sub="test-multi-2", kind="user", roles=["ops", "manager"])
    assert visible_categories(principal2) == frozenset({"delivery"})


def test_multi_role_principal_with_one_unrestricted_role_is_fully_unrestricted() -> None:
    principal = Principal(sub="test-multi-3", kind="user", roles=["hr", "director"])
    assert visible_categories(principal) is None
