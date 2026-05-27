"""Add reply intent, follow-up draft approval, and campaign plans.

Revision ID: 0003_reply_followup_campaigns
Revises: 0002_agent_tables
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_reply_followup_campaigns"
down_revision = "0002_agent_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    columns_by_table = {table: {column["name"] for column in inspector.get_columns(table)} for table in tables}
    if "replies" in tables and "intent" not in columns_by_table["replies"]:
        op.add_column("replies", sa.Column("intent", sa.String(), nullable=True))
    if "drafts" in tables and "notes" not in columns_by_table["drafts"]:
        op.add_column("drafts", sa.Column("notes", sa.Text(), nullable=True))
    if "follow_up_sequences" in tables and "pending_draft_id" not in columns_by_table["follow_up_sequences"]:
        op.add_column("follow_up_sequences", sa.Column("pending_draft_id", sa.String(), nullable=True))
    if "campaign_plans" not in tables:
        op.create_table(
            "campaign_plans",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("goal", sa.Text(), nullable=True),
            sa.Column("target_tags", sa.String(), nullable=True),
            sa.Column("step_1_draft", sa.Text(), nullable=True),
            sa.Column("step_2_draft", sa.Text(), nullable=True),
            sa.Column("step_3_draft", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("contacts_count", sa.Integer(), nullable=True),
            sa.Column("sent_count", sa.Integer(), nullable=True),
            sa.Column("stopped_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("campaign_plans")
    op.drop_constraint("fk_follow_up_sequences_pending_draft_id_drafts", "follow_up_sequences", type_="foreignkey")
    op.drop_column("follow_up_sequences", "pending_draft_id")
    op.drop_column("drafts", "notes")
    op.drop_column("replies", "intent")
