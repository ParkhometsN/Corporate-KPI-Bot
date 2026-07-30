from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.grade import _find_current_and_next, _grade_period_bounds, progress_bar
from app.services.kpi import _earned_percent_from_rules, _kpi_bonus_base, _next_month
from app.services.catalog import _normalize_title
from app.services.statistics import _period_bounds
from app.yclients.client import _calculate_daily_statistic, _extract_user_token, _record_statistic_date


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


def test_grade_current_category_aliases_match_price_rules() -> None:
    rules = [
        SimpleNamespace(category_title="1500 ₽", base_price=Decimal("1500")),
        SimpleNamespace(category_title="1700 ₽", base_price=Decimal("1700")),
    ]

    current, next_rule = _find_current_and_next(rules, "Мастер")

    assert current.base_price == Decimal("1500")
    assert next_rule.base_price == Decimal("1700")


def test_grade_period_includes_current_month() -> None:
    start, end = _grade_period_bounds(2)

    assert start.day == 1
    assert end == date.today()
    assert (end.year - start.year) * 12 + end.month - start.month == 1


def test_kpi_bonus_base_uses_additional_services_and_products() -> None:
    monthly_stat = SimpleNamespace(
        additional_services_revenue=Decimal("25000"),
        products_revenue=Decimal("12000"),
    )
    rules = [
        SimpleNamespace(threshold_amount=Decimal("0"), percent=Decimal("0")),
        SimpleNamespace(threshold_amount=Decimal("37000"), percent=Decimal("2")),
        SimpleNamespace(threshold_amount=Decimal("60000"), percent=Decimal("5")),
    ]

    kpi_base = _kpi_bonus_base(monthly_stat)

    assert kpi_base == Decimal("37000")
    assert _earned_percent_from_rules(rules, kpi_base) == Decimal("2")


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


def test_yclients_daily_statistic_filters_records_by_staff_id() -> None:
    records = [
        {"attendance": 1, "staff_id": 123, "services": [{"cost": 2000}]},
        {"attendance": 1, "staff": {"id": 456}, "services": [{"cost": 5000}]},
        {"attendance": 1, "staff_id": 123, "services": [{"cost": 3000}, {"cost": 700}]},
    ]

    stat = _calculate_daily_statistic(
        123,
        date(2026, 7, 30),
        records,
        include_records_without_staff=False,
    )

    assert stat.haircuts_count == 2
    assert stat.service_revenue == Decimal("5000")
    assert stat.additional_services_revenue == Decimal("700")


def test_extract_user_token_from_auth_payload_variants() -> None:
    assert _extract_user_token({"user_token": "abc"}) == "abc"
    assert _extract_user_token({"success": True, "data": {"user_token": "def"}}) == "def"
    assert _extract_user_token({"success": True, "data": {}}) is None


def test_record_statistic_date_from_yclients_date_string() -> None:
    assert _record_statistic_date({"date": "2026-07-30 18:00:00"}) == date(2026, 7, 30)
