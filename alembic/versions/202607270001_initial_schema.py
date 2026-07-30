"""initial schema

Revision ID: 202607270001
Revises:
Create Date: 2026-07-27
"""

from alembic import op

from app import models  # noqa: F401
from app.database.base import Base

revision = "202607270001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

