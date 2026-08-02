"""add regulation files and connection message

Revision ID: 202608020002
Revises: 202608020001
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa

revision = "202608020002"
down_revision = "202608020001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    company_columns = {column["name"] for column in inspector.get_columns("companies")}
    if "regulation_file_id" not in company_columns:
        op.add_column("companies", sa.Column("regulation_file_id", sa.Text(), nullable=True))
    if "regulation_file_name" not in company_columns:
        op.add_column("companies", sa.Column("regulation_file_name", sa.String(length=255), nullable=True))

    code_columns = {column["name"] for column in inspector.get_columns("connection_codes")}
    if "admin_chat_id" not in code_columns:
        op.add_column("connection_codes", sa.Column("admin_chat_id", sa.BigInteger(), nullable=True))
    if "admin_message_id" not in code_columns:
        op.add_column("connection_codes", sa.Column("admin_message_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    code_columns = {column["name"] for column in inspector.get_columns("connection_codes")}
    if "admin_message_id" in code_columns:
        op.drop_column("connection_codes", "admin_message_id")
    if "admin_chat_id" in code_columns:
        op.drop_column("connection_codes", "admin_chat_id")

    company_columns = {column["name"] for column in inspector.get_columns("companies")}
    if "regulation_file_name" in company_columns:
        op.drop_column("companies", "regulation_file_name")
    if "regulation_file_id" in company_columns:
        op.drop_column("companies", "regulation_file_id")
