from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SyncStatus


class Branch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("company_id", "yclients_branch_id", name="uq_branches_company_yclients"),
    )

    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    owner_telegram_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    yclients_branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status", native_enum=False),
        default=SyncStatus.NEW,
        nullable=False,
    )
    employees_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    company = relationship("Company", back_populates="branches")
    owner_telegram_user = relationship("TelegramUser", foreign_keys=[owner_telegram_user_id])
    employees = relationship("Employee", back_populates="branch", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="branch", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="branch", cascade="all, delete-orphan")
    franchise_accesses = relationship("FranchiseBranchAccess", back_populates="branch", cascade="all, delete-orphan")
