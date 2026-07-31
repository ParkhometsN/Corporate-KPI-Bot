"""add company regulation text

Revision ID: 202607290001
Revises: 202607270001
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "202607290001"
down_revision = "202607270001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("companies")}
    if "regulation_text" not in columns:
        op.add_column("companies", sa.Column("regulation_text", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("companies")}
    if "regulation_text" in columns:
        op.drop_column("companies", "regulation_text")
