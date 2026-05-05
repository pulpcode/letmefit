"""add dialogue state and async summaries

Revision ID: 5f0d3c8b8b6d
Revises: 98185fe3b1ec
Create Date: 2026-05-05 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "5f0d3c8b8b6d"
down_revision: str | None = "98185fe3b1ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("dialogue_state_json", mysql.JSON(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("dialogue_state_updated_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column(
            "summary_type",
            sa.String(length=32),
            server_default="rolling",
            nullable=False,
        ),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="succeeded",
            nullable=False,
        ),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("summary_json", mysql.JSON(), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("model_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.create_index(
        "ix_conversation_summaries_conversation_status_created",
        "conversation_summaries",
        ["conversation_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_summaries_conversation_status_created",
        table_name="conversation_summaries",
    )
    op.drop_column("conversation_summaries", "updated_at")
    op.drop_column("conversation_summaries", "model_name")
    op.drop_column("conversation_summaries", "summary_json")
    op.drop_column("conversation_summaries", "status")
    op.drop_column("conversation_summaries", "summary_type")
    op.drop_column("conversations", "dialogue_state_updated_at")
    op.drop_column("conversations", "dialogue_state_json")
