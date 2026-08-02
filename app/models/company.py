from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "companies"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    partner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    default_company_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    encrypted_yclients_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_yclients_user_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    admin_password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    regulation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    regulation_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    regulation_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    statistics_time: Mapped[str] = mapped_column(String(5), default="22:00", nullable=False)
    synchronization_interval_minutes: Mapped[int] = mapped_column(default=60, nullable=False)

    branches = relationship("Branch", back_populates="company", cascade="all, delete-orphan")
    kpi_rules = relationship("KpiRule", back_populates="company", cascade="all, delete-orphan")
    grade_rules = relationship("GradeRule", back_populates="company", cascade="all, delete-orphan")
