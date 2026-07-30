from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    EMPLOYEE = "employee"


class SyncStatus(StrEnum):
    NEW = "new"
    SYNCED = "synced"
    ERROR = "error"


class ConnectionCodeStatus(StrEnum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"


class ProductStockStatus(StrEnum):
    AVAILABLE = "available"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"

