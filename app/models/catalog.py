from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProductStockStatus


class Service(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("branch_id", "yclients_service_id", name="uq_services_branch_yclients"),
    )

    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    yclients_service_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_min: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    price_max: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)

    branch = relationship("Branch", back_populates="services")


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("branch_id", "yclients_product_id", name="uq_products_branch_yclients"),
    )

    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    yclients_product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    stock_amount: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0, nullable=False)
    status: Mapped[ProductStockStatus] = mapped_column(
        Enum(ProductStockStatus, name="product_stock_status", native_enum=False),
        default=ProductStockStatus.AVAILABLE,
        nullable=False,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)

    branch = relationship("Branch", back_populates="products")

