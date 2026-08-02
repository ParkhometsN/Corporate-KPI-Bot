"""allow multiple employee links per telegram user

Revision ID: 202608030001
Revises: 202608020004
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa

revision = "202608030001"
down_revision = "202608020004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("employees")
    for constraint in unique_constraints:
        columns = set(constraint.get("column_names") or [])
        name = constraint.get("name")
        if columns == {"telegram_user_id"} and name:
            op.drop_constraint(name, "employees", type_="unique")
            break
    indexes = {index["name"] for index in inspector.get_indexes("employees")}
    if "ix_employees_telegram_user_id" not in indexes:
        op.create_index("ix_employees_telegram_user_id", "employees", ["telegram_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("employees")}
    if "ix_employees_telegram_user_id" in indexes:
        op.drop_index("ix_employees_telegram_user_id", table_name="employees")
    unique_constraints = inspector.get_unique_constraints("employees")
    if not any(set(constraint.get("column_names") or []) == {"telegram_user_id"} for constraint in unique_constraints):
        op.create_unique_constraint("uq_employees_telegram_user_id", "employees", ["telegram_user_id"])
