"""expand telegram user role

Revision ID: 202608020004
Revises: 202608020003
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa

revision = "202608020004"
down_revision = "202608020003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("telegram_users")}
    role_column = columns.get("role")
    if role_column is None:
        return
    length = getattr(role_column["type"], "length", None)
    if length is None or length < 32:
        op.alter_column(
            "telegram_users",
            "role",
            existing_type=sa.String(length=length or 8),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    op.alter_column(
        "telegram_users",
        "role",
        existing_type=sa.String(length=32),
        type_=sa.String(length=8),
        existing_nullable=False,
    )
