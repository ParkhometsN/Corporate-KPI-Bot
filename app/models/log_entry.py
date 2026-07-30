from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LogEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "logs"

    level: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    event: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

