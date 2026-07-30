from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class YClientsBranch:
    id: int
    title: str
    address: str | None


@dataclass(slots=True)
class YClientsEmployee:
    id: int
    name: str
    specialization: str | None
    category_title: str | None


@dataclass(slots=True)
class YClientsService:
    id: int
    title: str
    category: str | None
    price_min: Decimal
    price_max: Decimal


@dataclass(slots=True)
class YClientsProduct:
    id: int
    title: str
    price: Decimal
    stock_amount: Decimal
    category: str | None = None


@dataclass(slots=True)
class YClientsDailyStatistic:
    employee_staff_id: int
    statistic_date: date
    haircuts_count: int
    service_revenue: Decimal
    additional_services_revenue: Decimal
    total_revenue: Decimal
    average_check: Decimal
    attendance_percent: Decimal
    products_sold: int
    products_revenue: Decimal
    raw_payload: dict[str, Any]
