"""add returning client counts

Revision ID: 202608030003
Revises: 202608030002
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa

revision = "202608030003"
down_revision = "202608030002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "daily_statistics",
        sa.Column("client_records_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "daily_statistics",
        sa.Column("returning_clients_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "monthly_statistics",
        sa.Column("client_records_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "monthly_statistics",
        sa.Column("returning_clients_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("monthly_statistics", "returning_clients_count")
    op.drop_column("monthly_statistics", "client_records_count")
    op.drop_column("daily_statistics", "returning_clients_count")
    op.drop_column("daily_statistics", "client_records_count")
