from datetime import date, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config.logging import get_logger
from app.config.settings import Settings
from app.models import Employee
from app.repositories import ScheduleRepository
from app.services import build_services

logger = get_logger(__name__)


async def setup_scheduler(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tzinfo)
    async with session_factory() as session:
        schedules_repo = ScheduleRepository(session)
        await schedules_repo.ensure_defaults(settings)
        schedules = await schedules_repo.list_enabled()
        await session.commit()

    job_map = {
        "sync_all_branches": (
            sync_all_branches,
            {"session_factory": session_factory, "settings": settings},
        ),
        "send_daily_reports": (
            send_daily_reports,
            {"bot": bot, "session_factory": session_factory, "settings": settings},
        ),
        "send_weekly_reports": (
            send_weekly_reports,
            {"bot": bot, "session_factory": session_factory, "settings": settings},
        ),
        "send_monthly_reports": (
            send_monthly_reports,
            {"bot": bot, "session_factory": session_factory, "settings": settings},
        ),
    }
    for schedule in schedules:
        if schedule.job_id not in job_map:
            continue
        job_func, kwargs = job_map[schedule.job_id]
        if schedule.trigger_type == "interval":
            scheduler.add_job(
                job_func,
                "interval",
                minutes=schedule.interval_minutes or settings.sync_interval_minutes,
                kwargs=kwargs,
                id=schedule.job_id,
                replace_existing=True,
                max_instances=1,
            )
        elif schedule.trigger_type == "cron" and schedule.cron_expression:
            scheduler.add_job(
                job_func,
                CronTrigger.from_crontab(schedule.cron_expression, timezone=settings.tzinfo),
                kwargs=kwargs,
                id=schedule.job_id,
                replace_existing=True,
                max_instances=1,
            )
    return scheduler


async def sync_all_branches(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with session_factory() as session:
        services = build_services(session, settings)
        await services.sync.sync_company()
        await session.commit()
    logger.info("scheduled_sync_completed")


async def send_daily_reports(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await _send_period_reports(bot, session_factory, settings, period="today")


async def send_weekly_reports(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await _send_period_reports(bot, session_factory, settings, period="week")


async def send_monthly_reports(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with session_factory() as session:
        services = build_services(session, settings)
        employees = await _connected_employees(session)
        previous_month = _previous_month(date.today())
        for employee in employees:
            await bot.send_message(
                employee.telegram_user.telegram_id,
                await services.statistics.employee_stats_text(employee, "previous_month"),
            )
            await bot.send_message(
                employee.telegram_user.telegram_id,
                await services.kpi.employee_kpi_text(employee, previous_month),
            )
            await bot.send_message(
                employee.telegram_user.telegram_id,
                await services.grade.grade_text(employee),
            )
        await session.commit()
    logger.info("monthly_reports_sent")


async def _send_period_reports(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    period: str,
) -> None:
    async with session_factory() as session:
        services = build_services(session, settings)
        employees = await _connected_employees(session)
        for employee in employees:
            await bot.send_message(
                employee.telegram_user.telegram_id,
                await services.statistics.employee_stats_text(employee, period),
            )
        await session.commit()
    logger.info("period_reports_sent", period=period)


async def _connected_employees(session: AsyncSession) -> list[Employee]:
    result = await session.execute(
        select(Employee)
        .where(Employee.telegram_user_id.is_not(None), Employee.is_active.is_(True))
        .options(selectinload(Employee.telegram_user), selectinload(Employee.branch))
    )
    return list(result.scalars().all())


def _previous_month(day: date) -> date:
    first_day = day.replace(day=1)
    previous_last_day = first_day - timedelta(days=1)
    return previous_last_day.replace(day=1)
