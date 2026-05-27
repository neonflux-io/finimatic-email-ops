"""Add agent_sessions and pending_email_actions tables

Revision ID: 0002_agent_tables
Revises: 0001_initial
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_agent_tables"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "agent_sessions" in existing and "pending_email_actions" in existing:
        return
    if "agent_sessions" not in existing:
        op.create_table(
            "agent_sessions",
            sa.Column("id", sa.Text, primary_key=True),
            sa.Column("session_token_hash", sa.Text, nullable=False, unique=True),
            sa.Column("current_goal", sa.Text),
            sa.Column("slots", sa.Text),
            sa.Column("active_contact_id", sa.Text, sa.ForeignKey("contacts.id")),
            sa.Column("pending_action_id", sa.Text),
            sa.Column("context_summary", sa.Text),
            sa.Column("context_loaded_at", sa.Text),
            sa.Column("contact_name_map", sa.Text),
            sa.Column("turn_history", sa.Text),
            sa.Column("current_channel", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("expires_at", sa.DateTime, nullable=False),
        )
    if "pending_email_actions" not in existing:
        op.create_table(
            "pending_email_actions",
            sa.Column("id", sa.Text, primary_key=True),
            sa.Column("session_id", sa.Text, sa.ForeignKey("agent_sessions.id"), nullable=False),
            sa.Column("action_type", sa.Text, nullable=False, server_default="email_send_draft"),
            sa.Column("capability", sa.Text, nullable=False, server_default="email_send_draft"),
            sa.Column("draft_id", sa.Text, sa.ForeignKey("drafts.id"), nullable=False),
            sa.Column("contact_id", sa.Text, sa.ForeignKey("contacts.id"), nullable=False),
            sa.Column("params_hash", sa.Text, nullable=False),
            sa.Column("source_label", sa.Text, nullable=False, server_default="Email Provider"),
            sa.Column("confirmation_prompt", sa.Text, nullable=False),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("consumed", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("consumed_at", sa.DateTime),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        )


def downgrade() -> None:
    op.drop_table("pending_email_actions")
    op.drop_table("agent_sessions")
