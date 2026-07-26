"""0010_comms_outbox — mcp-comms (Sprint 3, doc 07 §4 tools list; monorepo
tree doc 12 §2 names this module `tools_outbox.py`). No real
SMTP/Slack/SMS integration exists yet (DEVIATIONS.md #10) — every
`notify_user`/`send_reminder`/`incident_broadcast` call is durably recorded
here instead of actually delivered, the same "swap the mechanism later,
keep the contract" pattern already used for the LLM gateway (Ollama vs
vLLM) and auth (dev JWT vs Keycloak).

Revision ID: 0010_comms_outbox
Revises: 0009_rls_and_views
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0010_comms_outbox"
down_revision = "0009_rls_and_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comms_outbox",
        # sa.String(36), not `pg.UUID` — see migration 0001_people's module
        # docstring for why (mcps/comms/awp_mcp_comms/tables.py's Core
        # mirror uses generic String too; `tools_notify.py` inserts
        # `str(uuid.uuid4())`).
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # notify_user|send_reminder|incident_broadcast
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("recipient_type", sa.String(20), nullable=False),  # user|role|broadcast
        sa.Column("recipient_id", sa.String(80), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("refs", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("sent_by", sa.String(40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_comms_outbox_recipient", "comms_outbox", ["recipient_type", "recipient_id"])
    op.create_index("ix_comms_outbox_kind", "comms_outbox", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_comms_outbox_kind", table_name="comms_outbox")
    op.drop_index("ix_comms_outbox_recipient", table_name="comms_outbox")
    op.drop_table("comms_outbox")
