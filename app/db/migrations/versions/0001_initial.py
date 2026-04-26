"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-26 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("rating", sa.Boolean(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "role",
            sa.Enum("ai", "user", name="message_role"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_messages_chat_id", "messages", ["chat_id"])
    op.create_index(
        "ix_messages_chat_sent_desc",
        "messages",
        ["chat_id", sa.text("sent_at DESC")],
    )
    op.create_index("ix_messages_sent_id", "messages", ["sent_at", "message_id"])

    # Trigger to keep updated_at fresh on UPDATE.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_set_updated_at
        BEFORE UPDATE ON messages
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS messages_set_updated_at ON messages")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.drop_index("ix_messages_sent_id", table_name="messages")
    op.drop_index("ix_messages_chat_sent_desc", table_name="messages")
    op.drop_index("ix_messages_chat_id", table_name="messages")
    op.drop_table("messages")
    sa.Enum(name="message_role").drop(op.get_bind(), checkfirst=False)
