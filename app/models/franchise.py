from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Franchisee(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "franchisees"

    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_blocked: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_view_owner_branches: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_message_owner_employees: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_receive_owner_statistics: Mapped[bool] = mapped_column(default=False, nullable=False)
    encrypted_yclients_user_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    company = relationship("Company")
    telegram_user = relationship("TelegramUser", foreign_keys=[telegram_user_id])
    created_by_user = relationship("TelegramUser", foreign_keys=[created_by_user_id])
    branch_accesses = relationship("FranchiseBranchAccess", back_populates="franchisee", cascade="all, delete-orphan")
    invites = relationship("FranchiseInvite", back_populates="franchisee", cascade="all, delete-orphan")


class FranchiseInvite(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "franchise_invites"

    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    franchisee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("franchisees.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(index=True, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    admin_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    company = relationship("Company")
    franchisee = relationship("Franchisee", back_populates="invites")
    created_by_user = relationship("TelegramUser")


class FranchiseBranchAccess(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "franchise_branch_accesses"
    __table_args__ = (
        UniqueConstraint("franchisee_id", "branch_id", name="uq_franchise_branch_access"),
    )

    franchisee_id: Mapped[UUID] = mapped_column(ForeignKey("franchisees.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    can_view_statistics: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_message_employees: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_manage_employees: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    franchisee = relationship("Franchisee", back_populates="branch_accesses")
    branch = relationship("Branch", back_populates="franchise_accesses")
