from sqlalchemy import select

from app.config.settings import Settings
from app.models import Schedule
from app.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository[Schedule]):
    model = Schedule

    async def list_enabled(self) -> list[Schedule]:
        result = await self.session.execute(
            select(Schedule).where(Schedule.is_enabled.is_(True)).order_by(Schedule.job_id.asc())
        )
        return list(result.scalars().all())

    async def ensure_defaults(self, settings: Settings) -> list[Schedule]:
        defaults = [
            {
                "job_id": "sync_all_branches",
                "title": "Синхронизация всех филиалов",
                "trigger_type": "interval",
                "cron_expression": None,
                "interval_minutes": settings.sync_interval_minutes,
            },
            {
                "job_id": "send_daily_reports",
                "title": "Ежедневные отчёты",
                "trigger_type": "cron",
                "cron_expression": settings.daily_report_cron,
                "interval_minutes": None,
            },
            {
                "job_id": "send_weekly_reports",
                "title": "Еженедельные отчёты",
                "trigger_type": "cron",
                "cron_expression": settings.weekly_report_cron,
                "interval_minutes": None,
            },
            {
                "job_id": "send_monthly_reports",
                "title": "Ежемесячные отчёты",
                "trigger_type": "cron",
                "cron_expression": settings.monthly_report_cron,
                "interval_minutes": None,
            },
        ]
        schedules: list[Schedule] = []
        for item in defaults:
            result = await self.session.execute(
                select(Schedule).where(Schedule.job_id == item["job_id"])
            )
            schedule = result.scalar_one_or_none()
            if schedule is None:
                schedule = Schedule(
                    job_id=item["job_id"],
                    title=item["title"],
                    trigger_type=item["trigger_type"],
                    cron_expression=item["cron_expression"],
                    interval_minutes=item["interval_minutes"],
                    timezone=settings.timezone,
                )
                self.session.add(schedule)
            schedules.append(schedule)
        await self.session.flush()
        return schedules
