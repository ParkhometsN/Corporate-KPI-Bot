"""add employee engagement metrics

Revision ID: 202608030002
Revises: 202608030001
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa

revision = "202608030002"
down_revision = "202608030001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "daily_statistics",
        sa.Column("returning_clients_percent", sa.Numeric(5, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "daily_statistics",
        sa.Column("occupancy_percent", sa.Numeric(5, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "monthly_statistics",
        sa.Column("returning_clients_percent", sa.Numeric(5, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "monthly_statistics",
        sa.Column("occupancy_percent", sa.Numeric(5, 2), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("monthly_statistics", "occupancy_percent")
    op.drop_column("monthly_statistics", "returning_clients_percent")
    op.drop_column("daily_statistics", "occupancy_percent")
    op.drop_column("daily_statistics", "returning_clients_percent")
