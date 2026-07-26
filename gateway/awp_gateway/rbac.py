"""Ticket-category RBAC — doc 08 §1's `query_tickets` note: "scope-filtered:
dept agents see their own categories, SUP-1 sees all; full per-caller
category ACL enforcement lands with the gateway's RBAC layer (Sprint 3)".
This module is that layer, driven by `config/routing.yaml`'s
category -> owning-agent map plus `config/roles.yaml`'s roles.
"""

from __future__ import annotations

from awp_shared.auth import Principal

_ADMIN_CATEGORIES = frozenset({"device", "access", "facilities", "records", "procurement"})
_HR_CATEGORIES = frozenset({"hr"})
_FINANCE_CATEGORIES = frozenset({"payroll", "expense"})
_OPS_CATEGORIES = frozenset({"delivery"})

# Role -> visible categories. `None` = full visibility (support fabric
# owners + cross-department oversight, doc 07 "SUP-1 has the widest read on
# tickets"; doc 00 §7 director/ceo cross-department oversight). A role
# absent from this map (e.g. `employee`, `manager`, `dept_head`) has no
# department-level visibility at all — `visible_categories` returns an empty
# set for it, and callers should fall back to a self-service filter
# (`requester_id`), not treat the empty set as "sees nothing usefully."
_ROLE_CATEGORIES: dict[str, frozenset[str] | None] = {
    "admin_head": _ADMIN_CATEGORIES,
    "admin": _ADMIN_CATEGORIES,
    "hr_head": _HR_CATEGORIES,
    "hr": _HR_CATEGORIES,
    "recruiter": _HR_CATEGORIES,
    "finance_head": _FINANCE_CATEGORIES,
    "finance": _FINANCE_CATEGORIES,
    "ops": _OPS_CATEGORIES,
    "support_lead": None,
    "support": None,
    "director": None,
    "ceo": None,
}


def visible_categories(principal: Principal) -> frozenset[str] | None:
    """`None` = unrestricted (sees every category). Otherwise the union of
    every matched role's category set — empty if no role in
    `principal.roles` carries department visibility."""
    matched: set[str] = set()
    for role in principal.roles:
        categories = _ROLE_CATEGORIES.get(role)
        if role in _ROLE_CATEGORIES and categories is None:
            return None
        if categories:
            matched |= categories
    return frozenset(matched)


# doc 03 §2.4: dashboards are role-scoped panels (CEO/Directors/Managers).
# A human can pull their own role's dashboard, or — same cross-department
# oversight convention as `_ROLE_CATEGORIES`'s `None` entries — any
# dashboard at all if they hold `director` or `ceo`.
_UNRESTRICTED_DASHBOARD_ROLES = frozenset({"director", "ceo"})


def can_view_dashboard_role(principal: Principal, role: str) -> bool:
    return role in principal.roles or bool(set(principal.roles) & _UNRESTRICTED_DASHBOARD_ROLES)
