from sqlalchemy import BigInteger, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Role


class TelegramUser(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "telegram_users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", native_enum=False),
        default=Role.EMPLOYEE,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    employee = relationship("Employee", back_populates="telegram_user", uselist=False)
    notifications = relationship(
        "NotificationSettings",
        back_populates="telegram_user",
        cascade="all, delete-orphan",
        uselist=False,
    )

