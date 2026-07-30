from datetime import date
from decimal import Decimal

from app.services.grade import progress_bar
from app.services.kpi import _next_month
from app.services.catalog import _normalize_title
from app.services.statistics import _period_bounds
from app.yclients.client import _calculate_daily_statistic


def test_next_month_regular_and_year_boundary() -> None:
    assert _next_month(date(2026, 7, 1)) == date(2026, 8, 1)
    assert _next_month(date(2026, 12, 1)) == date(2027, 1, 1)


def test_previous_month_period_bounds() -> None:
    start, end = _period_bounds("previous_month")

    assert start.day == 1
    assert start.month != date.today().month or start.year != date.today().year
    assert end.month == start.month
    assert end.year == start.year


def test_progress_bar() -> None:
    assert progress_bar(Decimal("0")) == "░░░░░░░░░░"
    assert progress_bar(Decimal("50")) == "█████░░░░░"
    assert progress_bar(Decimal("100")) == "██████████"


def test_service_title_normalization_groups_minor_variants() -> None:
    assert _normalize_title("Бритьё головы(опасной бритвой)") == _normalize_title(
        "Бритье головы (опасной бритвой)"
    )


def test_yclients_daily_statistic_calculation() -> None:
    records = [
        {
            "attendance": 1,
            "services": [{"cost": 2000}, {"cost": 500}],
            "goods": [{"cost": 700}],
        },
        {
            "attendance": 1,
            "services": [{"cost": 1500}],
        },
        {
            "attendance": -1,
            "services": [{"cost": 3000}],
        },
    ]

    stat = _calculate_daily_statistic(123, date(2026, 7, 27), records)

    assert stat.haircuts_count == 2
    assert stat.service_revenue == Decimal("3500")
    assert stat.additional_services_revenue == Decimal("500")
    assert stat.products_revenue == Decimal("700")
    assert stat.total_revenue == Decimal("4700")
    assert stat.products_sold == 1
