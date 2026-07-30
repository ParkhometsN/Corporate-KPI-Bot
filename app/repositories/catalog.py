from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.models import Product, ProductStockStatus, Service
from app.repositories.base import BaseRepository


class ServiceRepository(BaseRepository[Service]):
    model = Service

    async def list_by_branch(self, branch_id: UUID) -> list[Service]:
        result = await self.session.execute(
            select(Service)
            .where(Service.branch_id == branch_id, Service.is_active.is_(True))
            .order_by(Service.category.asc(), Service.title.asc())
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        branch_id: UUID,
        yclients_service_id: int,
        title: str,
        category: str | None,
        price_min: Decimal,
        price_max: Decimal,
    ) -> Service:
        result = await self.session.execute(
            select(Service).where(
                Service.branch_id == branch_id,
                Service.yclients_service_id == yclients_service_id,
            )
        )
        service = result.scalar_one_or_none()
        if service is None:
            service = Service(
                branch_id=branch_id,
                yclients_service_id=yclients_service_id,
                title=title,
                category=category,
                price_min=price_min,
                price_max=price_max,
            )
            self.session.add(service)
        else:
            service.title = title
            service.category = category
            service.price_min = price_min
            service.price_max = price_max
            service.is_active = True
        service.last_synced_at = datetime.now()
        await self.session.flush()
        return service

    async def deactivate_missing_services(self, branch_id: UUID, active_service_ids: set[int]) -> int:
        statement = select(Service).where(Service.branch_id == branch_id, Service.is_active.is_(True))
        if active_service_ids:
            statement = statement.where(Service.yclients_service_id.not_in(active_service_ids))
        result = await self.session.execute(statement)
        missing_services = list(result.scalars().all())
        for service in missing_services:
            service.is_active = False
            service.last_synced_at = datetime.now()
        await self.session.flush()
        return len(missing_services)


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def list_by_branch(self, branch_id: UUID, query: str | None = None) -> list[Product]:
        statement = select(Product).where(Product.branch_id == branch_id)
        if query:
            statement = statement.where(func.lower(Product.title).contains(query.lower()))
        result = await self.session.execute(statement.order_by(Product.title.asc()))
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        branch_id: UUID,
        yclients_product_id: int,
        title: str,
        price: Decimal,
        stock_amount: Decimal,
        low_stock_threshold: int,
    ) -> Product:
        result = await self.session.execute(
            select(Product).where(
                Product.branch_id == branch_id,
                Product.yclients_product_id == yclients_product_id,
            )
        )
        product = result.scalar_one_or_none()
        status = self._detect_status(stock_amount, low_stock_threshold)
        if product is None:
            product = Product(
                branch_id=branch_id,
                yclients_product_id=yclients_product_id,
                title=title,
                price=price,
                stock_amount=stock_amount,
                status=status,
            )
            self.session.add(product)
        else:
            product.title = title
            product.price = price
            product.stock_amount = stock_amount
            product.status = status
        product.last_synced_at = datetime.now()
        await self.session.flush()
        return product

    @staticmethod
    def _detect_status(stock_amount: Decimal, low_stock_threshold: int) -> ProductStockStatus:
        if stock_amount <= 0:
            return ProductStockStatus.OUT_OF_STOCK
        if stock_amount <= low_stock_threshold:
            return ProductStockStatus.LOW_STOCK
        return ProductStockStatus.AVAILABLE
