"""add franchise access

Revision ID: 202608020001
Revises: 202607290001
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models.franchise import FranchiseBranchAccess, FranchiseInvite, Franchisee

revision = "202608020001"
down_revision = "202607290001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    branch_columns = {column["name"] for column in inspector.get_columns("branches")}
    if "owner_telegram_user_id" not in branch_columns:
        op.add_column(
            "branches",
            sa.Column("owner_telegram_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_index("ix_branches_owner_telegram_user_id", "branches", ["owner_telegram_user_id"])
        op.create_foreign_key(
            "fk_branches_owner_telegram_user_id_telegram_users",
            "branches",
            "telegram_users",
            ["owner_telegram_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    Franchisee.__table__.create(bind=bind, checkfirst=True)
    FranchiseInvite.__table__.create(bind=bind, checkfirst=True)
    FranchiseBranchAccess.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name in ("franchise_branch_accesses", "franchise_invites", "franchisees"):
        if table_name in tables:
            op.drop_table(table_name)
    branch_columns = {column["name"] for column in sa.inspect(bind).get_columns("branches")}
    if "owner_telegram_user_id" in branch_columns:
        op.drop_constraint("fk_branches_owner_telegram_user_id_telegram_users", "branches", type_="foreignkey")
        op.drop_index("ix_branches_owner_telegram_user_id", table_name="branches")
        op.drop_column("branches", "owner_telegram_user_id")
