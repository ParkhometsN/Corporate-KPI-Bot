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
    op.add_column("companies", sa.Column("regulation_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "regulation_text")
