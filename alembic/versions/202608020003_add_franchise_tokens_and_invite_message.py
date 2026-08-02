"""add franchise tokens and invite message

Revision ID: 202608020003
Revises: 202608020002
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa

revision = "202608020003"
down_revision = "202608020002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    franchisee_columns = {column["name"] for column in inspector.get_columns("franchisees")}
    if "encrypted_yclients_user_token" not in franchisee_columns:
        op.add_column("franchisees", sa.Column("encrypted_yclients_user_token", sa.Text(), nullable=True))

    invite_columns = {column["name"] for column in inspector.get_columns("franchise_invites")}
    if "admin_chat_id" not in invite_columns:
        op.add_column("franchise_invites", sa.Column("admin_chat_id", sa.BigInteger(), nullable=True))
    if "admin_message_id" not in invite_columns:
        op.add_column("franchise_invites", sa.Column("admin_message_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    invite_columns = {column["name"] for column in inspector.get_columns("franchise_invites")}
    if "admin_message_id" in invite_columns:
        op.drop_column("franchise_invites", "admin_message_id")
    if "admin_chat_id" in invite_columns:
        op.drop_column("franchise_invites", "admin_chat_id")

    franchisee_columns = {column["name"] for column in inspector.get_columns("franchisees")}
    if "encrypted_yclients_user_token" in franchisee_columns:
        op.drop_column("franchisees", "encrypted_yclients_user_token")
