from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.services.admin import AdminService
from app.services.bootstrap import BootstrapService
from app.services.catalog import CatalogService
from app.services.connection import EmployeeConnectionService
from app.services.grade import GradeService
from app.services.kpi import KpiService
from app.services.notification import NotificationService
from app.services.statistics import StatisticsService
from app.services.sync import SyncService


@dataclass(slots=True)
class ServiceContainer:
    admin: AdminService
    bootstrap: BootstrapService
    catalog: CatalogService
    connection: EmployeeConnectionService
    grade: GradeService
    kpi: KpiService
    notifications: NotificationService
    statistics: StatisticsService
    sync: SyncService


def build_services(session: AsyncSession, settings: Settings) -> ServiceContainer:
    sync = SyncService(session, settings)
    statistics = StatisticsService(session, settings)
    return ServiceContainer(
        admin=AdminService(session, settings, sync),
        bootstrap=BootstrapService(session, settings),
        catalog=CatalogService(session, settings),
        connection=EmployeeConnectionService(session, settings),
        grade=GradeService(session, settings),
        kpi=KpiService(session, settings),
        notifications=NotificationService(session, settings),
        statistics=statistics,
        sync=sync,
    )
