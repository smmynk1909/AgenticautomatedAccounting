"""0013_codeassist — Sprint 10, doc 05 §2.4 / doc 08 §8's CodeAssist
support: `projects.repo_slug` (which Gitea `owner/name` a project's repo
lives at — nullable, not every project has a linked repo) and
`patch_artifacts` (doc 08 §8's `suggest_patch` — a stored artifact for
human application, never a direct commit). `sa.String(36)` id columns from
the start (DEVIATIONS.md #11's lesson, not rediscovered).

Revision ID: 0013_codeassist
Revises: 0012_fix_projects_work_uuid
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_codeassist"
down_revision = "0012_fix_projects_work_uuid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("repo_slug", sa.String(200), nullable=True))

    op.create_table(
        "patch_artifacts",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("repo_slug", sa.String(200), nullable=False),
        sa.Column("base_ref", sa.String(100), nullable=False),
        sa.Column("patch_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("proposed_by", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_patch_artifacts_repo", "patch_artifacts", ["repo_slug"])


def downgrade() -> None:
    op.drop_index("ix_patch_artifacts_repo", table_name="patch_artifacts")
    op.drop_table("patch_artifacts")
    op.drop_column("projects", "repo_slug")
