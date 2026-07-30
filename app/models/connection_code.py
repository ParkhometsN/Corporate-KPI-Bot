from datetime import datetime
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ConnectionCodeStatus


class ConnectionCode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "connection_codes"

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[ConnectionCodeStatus] = mapped_column(
        Enum(ConnectionCodeStatus, name="connection_code_status", native_enum=False),
        default=ConnectionCodeStatus.ACTIVE,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(index=True, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    employee = relationship("Employee", back_populates="connection_codes")

