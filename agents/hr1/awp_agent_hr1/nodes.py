"""HR-1 graph nodes — doc 04. Sprint 7 covers HR-1a Sourcer, HR-1b
ResumeAuditor, HR-1c Shortlister (doc 12 §5 DoD: "04§5.1-2"). Sprint 8 adds
HR-1d NegotiationDesk and HR-1e TrainingPlanner (04§5.3-4). HR-1f
TicketHandler is still unscoped in doc 12 §5's sprint table (no sprint
names it) — dispatching `handle_hr_ticket`-shaped intents still isn't
wired. Same optimistic-call gating pattern as
`agents/fin1/awp_agent_fin1/nodes.py` for every gated flow here
(`shortlist_role` -> `shortlist_publish`, `prepare_negotiation` (draft path)
-> `offer_communication`, `plan_training` -> `training_plan`).
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_agent_base.state import AgentState
from awp_shared.candidate_profile import CandidateProfile
from awp_shared.errors import ValidationError
from awp_shared.schemas import TaskResult, TaskStatus

from awp_agent_hr1 import justify, negotiation, output_filter, shortlister, sourcer, training

Node = Any


def _fail_missing_token(state: AgentState, flow: str) -> None:
    state["result"] = TaskResult(
        task_id=state["task"].task_id,
        status=TaskStatus.FAILED,
        summary=f"{flow}: approval was granted but no token was returned",
    )


# --- source_candidates (Sourcer) ---


def make_source_candidates_node(llm: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        role_id = payload["role_id"]
        count = payload.get("count", 10)

        role_profile = await sourcer.get_or_build_role_profile(
            llm, mcp, role_id, payload.get("jd_text") or payload.get("jd_ref")
        )
        candidates = await sourcer.search_internal_pool(mcp, role_profile, count)

        state["scratch"]["role_profile"] = role_profile
        state["scratch"]["sourced_count"] = len(candidates)
        state["scratch"]["sourced_preview"] = [c["candidate_id"] for c in candidates[:5]]
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=f"sourced {len(candidates)} candidate(s) for role {role_id} (internal_db)",
        )
        return state

    return node


# --- audit_resume (ResumeAuditor) ---


def make_audit_resume_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        candidate_id = payload["candidate_id"]
        resume_uri = payload["resume_uri"]

        file_obj = await mcp.call("docs", "get_file", {"uri": resume_uri})
        extracted = await mcp.call(
            "hrsourcing", "extract_resume", {"file_bytes_b64": file_obj["content_base64"]}
        )
        normalized = await mcp.call(
            "hrsourcing", "normalize_profile", {"raw": extracted["text"]}
        )
        profile_dict = normalized["profile"]

        # Canonicalize against the skills_master controlled vocabulary
        # (doc 04 §2.2: "skill normalization ... to make shortlisting
        # deterministic downstream") — unmatched terms are dropped rather
        # than kept as free text, since shortlister.py's keyword_coverage
        # only matches against canonical names.
        if profile_dict.get("skills_normalized"):
            vocab = await mcp.call("erp", "query_policies", {"domain": "skills_master"})
            matches = await mcp.call(
                "hrsourcing",
                "skill_normalize",
                {"terms": profile_dict["skills_normalized"], "vocabulary": vocab["policies"]},
            )
            profile_dict["skills_normalized"] = sorted(
                {m["name"] for m in matches["matches"] if m["name"]}
            )
        profile = CandidateProfile.model_validate(profile_dict)

        existing = await mcp.call("erp", "get_candidate", {"candidate_id": candidate_id})
        merged_profile = {**existing.get("profile", {}), **profile_dict}
        await mcp.call(
            "erp",
            "upsert_candidate",
            {"record": {"id": candidate_id, "profile": merged_profile}},
        )

        state["scratch"]["audit_profile"] = profile_dict
        state["scratch"]["audit_confidence"] = normalized["confidence"]
        red_flag_count = len(profile.red_flags)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=(
                f"audited resume for candidate {candidate_id}"
                + (f" ({red_flag_count} red flag(s) — human review)" if red_flag_count else "")
            ),
        )
        return state

    return node


# --- shortlist_role (Shortlister) ---


def make_shortlist_role_node(llm: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        role_id = payload["role_id"]
        top_n = payload.get("top_n", 10)

        role = await mcp.call("erp", "get_role", {"role_id": role_id})
        role_profile = role.get("role_profile") or {}
        if not role_profile:
            raise ValidationError(
                f"role {role_id} has no cached RoleProfile — run source_candidates first"
            )

        hits = await sourcer.search_internal_pool(mcp, role_profile, top_n * 3)

        triples = []
        for hit in hits:
            candidate = await mcp.call(
                "erp", "get_candidate", {"candidate_id": hit["candidate_id"]}
            )
            profile = CandidateProfile.model_validate(candidate.get("profile", {}))
            triples.append((hit["candidate_id"], hit["score"], profile))

        ranked = shortlister.rank_candidates(triples, role_profile)[:top_n]
        profile_by_id = {cid: profile for cid, _, profile in triples}

        shortlist = []
        for sc in ranked:
            profile = profile_by_id[sc.candidate_id]
            justification = await justify.write_justification(
                llm, role_profile, profile, sc.score
            )
            shortlist.append(
                {
                    "candidate_id": sc.candidate_id,
                    "score": round(sc.score, 4),
                    "breakdown": sc.breakdown,
                    "justification": justification,
                }
            )

        approval = await mcp.call(
            "approvals",
            "request_approval",
            {
                "gate": "shortlist_publish",
                "payload": {"role_id": role_id, "shortlist": shortlist},
            },
        )
        state["scratch"]["awaiting_approval_for"] = "shortlist_role"
        state["scratch"]["approval_id"] = approval["approval_id"]
        state["scratch"]["role_id"] = role_id
        state["scratch"]["shortlist"] = shortlist
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.AWAITING_APPROVAL,
            summary=f"shortlist of {len(shortlist)} for role {role_id} awaiting recruiter approval",
        )
        return state

    return node


def make_check_shortlist_role_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_shortlist_role_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting shortlist_publish approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"shortlist approval was {status}",
            )
            return state
        if not result.get("token"):
            _fail_missing_token(state, "shortlist_role")
            return state

        role_id = state["scratch"]["role_id"]
        shortlist = state["scratch"]["shortlist"]
        await mcp.call(
            "erp",
            "push_dashboard_item",
            {
                "item": {
                    "audience_roles": ["recruiter", "hr_head"],
                    "panel": "hr_shortlist",
                    "severity": "info",
                    "title": f"Shortlist published for role {role_id}",
                    "body": f"{len(shortlist)} candidate(s) shortlisted and ready for outreach.",
                    "action_link": None,
                    "source_task_id": str(state["task"].task_id),
                }
            },
        )
        state["scratch"].pop("awaiting_approval_for", None)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=f"shortlist for role {role_id} published ({len(shortlist)} candidate(s))",
        )
        return state

    return node


# --- prepare_negotiation (NegotiationDesk) ---


def make_prepare_negotiation_node(llm: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        candidate_id = payload["candidate_id"]
        role_id = payload["role_id"]

        pack = await negotiation.build_negotiation_pack(
            llm, mcp, candidate_id, role_id, payload.get("candidate_input")
        )
        state["scratch"]["negotiation_pack"] = pack.model_dump()

        if not payload.get("draft_email"):
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.DONE,
                summary=f"negotiation pack prepared for candidate {candidate_id}",
            )
            return state

        candidate = await mcp.call("erp", "get_candidate", {"candidate_id": candidate_id})
        candidate_name = candidate.get("profile", {}).get("name") or candidate_id
        draft_text = await negotiation.draft_candidate_email(
            llm, pack, candidate_name, payload.get("offer_terms")
        )

        violations = output_filter.check_draft(draft_text, pack)
        if violations:
            # doc 09 §4.3: checked by code *before* any draft leaves the
            # agent — the draft never reaches `request_approval` at all.
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary="offer draft blocked by output filter: " + "; ".join(violations),
            )
            return state

        approval = await mcp.call(
            "approvals",
            "request_approval",
            {
                "gate": "offer_communication",
                "payload": {
                    "candidate_id": candidate_id,
                    "role_id": role_id,
                    "draft_text": draft_text,
                },
            },
        )
        state["scratch"]["awaiting_approval_for"] = "prepare_negotiation"
        state["scratch"]["approval_id"] = approval["approval_id"]
        state["scratch"]["candidate_id"] = candidate_id
        state["scratch"]["draft_text"] = draft_text
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.AWAITING_APPROVAL,
            summary=f"offer email drafted for candidate {candidate_id} awaiting hr_head approval",
        )
        return state

    return node


def make_check_prepare_negotiation_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError(
                "check_prepare_negotiation_approval reached with no approval_id"
            )

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting offer_communication approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"offer_communication approval was {status}",
            )
            return state
        if not result.get("token"):
            _fail_missing_token(state, "prepare_negotiation")
            return state

        candidate_id = state["scratch"]["candidate_id"]
        draft_text = state["scratch"]["draft_text"]
        # doc 04 §2.4: "text frozen at approval" — the exact text that was
        # shown to the approver is what gets recorded, never re-drafted.
        await mcp.call(
            "comms",
            "draft_external_email",
            {
                "candidate_id": candidate_id,
                "subject": "Offer discussion",
                "body": draft_text,
                "refs": {"approval_id": approval_id, "task_id": str(state["task"].task_id)},
            },
        )
        state["scratch"].pop("awaiting_approval_for", None)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=(
                f"offer email for candidate {candidate_id} recorded to outbox "
                "(sending is a human action)"
            ),
        )
        return state

    return node


# --- plan_training (TrainingPlanner) ---


def make_plan_training_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        emp_id = payload["emp_id"]
        quarter = payload.get("quarter", "unscheduled")

        gaps = await training.build_gap_report(mcp, emp_id)
        items = await training.match_training_plan(mcp, gaps, quarter)
        plan = training.summarize_plan(items)

        state["scratch"]["gap_report"] = [g.model_dump() for g in gaps]
        state["scratch"]["training_plan"] = plan

        approval = await mcp.call(
            "approvals",
            "request_approval",
            {"gate": "training_plan", "payload": {"emp_id": emp_id, "quarter": quarter, **plan}},
        )
        state["scratch"]["awaiting_approval_for"] = "plan_training"
        state["scratch"]["approval_id"] = approval["approval_id"]
        state["scratch"]["emp_id"] = emp_id
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.AWAITING_APPROVAL,
            summary=(
                f"training plan for employee {emp_id} ({len(items)} item(s), "
                f"{len(gaps)} gap(s)) awaiting manager approval"
            ),
        )
        return state

    return node


def make_check_plan_training_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_plan_training_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting training_plan approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"training_plan approval was {status}",
            )
            return state
        if not result.get("token"):
            _fail_missing_token(state, "plan_training")
            return state

        emp_id = state["scratch"]["emp_id"]
        plan = state["scratch"]["training_plan"]
        await mcp.call(
            "comms",
            "notify_user",
            {
                "user_id": emp_id,
                "subject": "Your training plan has been approved",
                "body": f"{len(plan['items'])} course(s), {plan['total_hours']} hour(s) total.",
                "refs": {"training_plan": plan},
            },
        )
        state["scratch"].pop("awaiting_approval_for", None)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=f"training plan for employee {emp_id} approved and notified",
        )
        return state

    return node


# --- shared respond ---


async def n_respond(state: AgentState) -> AgentState:
    if state.get("result") is not None:
        return state
    state["result"] = TaskResult(
        task_id=state["task"].task_id,
        status=TaskStatus.DONE,
        summary=f"handled {state['task'].intent}",
    )
    return state
