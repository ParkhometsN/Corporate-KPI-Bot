"""Репозитории доступа к данным."""

from app.repositories.branch import BranchRepository
from app.repositories.catalog import ProductRepository, ServiceRepository
from app.repositories.company import CompanyRepository, GradeRuleRepository, KpiRuleRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.franchise import (
    FranchiseBranchAccessRepository,
    FranchiseInviteRepository,
    FranchiseeRepository,
)
from app.repositories.schedule import ScheduleRepository
from app.repositories.statistics import (
    DailyStatisticRepository,
    EmployeeKpiRepository,
    MonthlyStatisticRepository,
)
from app.repositories.telegram_user import TelegramUserRepository

__all__ = [
    "BranchRepository",
    "CompanyRepository",
    "DailyStatisticRepository",
    "EmployeeKpiRepository",
    "EmployeeRepository",
    "FranchiseBranchAccessRepository",
    "FranchiseInviteRepository",
    "FranchiseeRepository",
    "GradeRuleRepository",
    "KpiRuleRepository",
    "MonthlyStatisticRepository",
    "ProductRepository",
    "ScheduleRepository",
    "ServiceRepository",
    "TelegramUserRepository",
]
