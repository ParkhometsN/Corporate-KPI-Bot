from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.bot.handlers.employee import _normalize_button_text
from app.services.catalog import (
    _employee_grade_position,
    _normalize_title,
    _product_catalog_chunks,
    _product_sort_key,
    _prices_for_grade,
    _visible_products,
    _wrap_text,
    _wrap_tokens,
)
from app.services.grade import _find_current_and_next, _grade_period_bounds, progress_bar
from app.services.kpi import _earned_percent_from_rules, _kpi_bonus_base, _next_month
from app.services.statistics import _period_bounds, _stat_has_activity
from app.yclients.client import (
    _calculate_daily_statistic,
    _extract_user_token,
    _product_from_item,
    _products_page_signature,
    _record_statistic_date,
)
from app.yclients.types import YClientsProduct


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


def test_catalog_grade_position_prefers_specific_grade_title() -> None:
    rules = [
        SimpleNamespace(category_title="Мастер", base_price=Decimal("1500")),
        SimpleNamespace(category_title="Старший мастер", base_price=Decimal("1700")),
        SimpleNamespace(category_title="Эксперт", base_price=Decimal("1900")),
        SimpleNamespace(category_title="Старший эксперт", base_price=Decimal("2300")),
    ]

    assert _employee_grade_position(SimpleNamespace(category_title="Старший Мастер"), rules) == (
        1,
        Decimal("1700"),
    )
    assert _employee_grade_position(SimpleNamespace(category_title="Старший Эксперт"), rules) == (
        3,
        Decimal("2300"),
    )


def test_catalog_grade_price_does_not_fall_below_base_when_higher_variant_exists() -> None:
    prices = {
        (Decimal("900"), Decimal("900")),
        (Decimal("1500"), Decimal("1500")),
        (Decimal("1900"), Decimal("1900")),
    }

    assert _prices_for_grade(prices, grade_index=1, base_price=Decimal("1700")) == [
        (Decimal("1900"), Decimal("1900"))
    ]


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


def test_daily_report_activity_ignores_empty_days() -> None:
    assert not _stat_has_activity(
        SimpleNamespace(
            haircuts_count=0,
            service_revenue=Decimal("0"),
            additional_services_revenue=Decimal("0"),
            total_revenue=Decimal("0"),
            products_sold=0,
            products_revenue=Decimal("0"),
        )
    )
    assert _stat_has_activity(
        SimpleNamespace(
            haircuts_count=0,
            service_revenue=Decimal("0"),
            additional_services_revenue=Decimal("400"),
            total_revenue=Decimal("400"),
            products_sold=0,
            products_revenue=Decimal("0"),
        )
    )


def test_service_title_normalization_groups_minor_variants() -> None:
    assert _normalize_title("Бритьё головы(опасной бритвой)") == _normalize_title(
        "Бритье головы (опасной бритвой)"
    )


def test_yclients_daily_statistic_calculation() -> None:
    records = [
        {
            "attendance": 1,
            "client": {"is_new": True},
            "occupancy_percent": "0.4",
            "services": [{"cost": 2000}, {"cost": 500}],
            "goods": [{"cost": 700}],
        },
        {
            "attendance": 1,
            "client": {"is_new": False},
            "analytics": {"filling_percent": 60},
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
    assert stat.returning_clients_percent == Decimal("50.0")
    assert stat.occupancy_percent == Decimal("50.0")


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


def test_yclients_daily_statistic_classifies_additional_services_by_title() -> None:
    records = [
        {
            "attendance": 1,
            "staff_id": 123,
            "services": [
                {"title": "Стрижка", "cost": 1500},
                {"title": "Оформление бороды", "cost": 1200},
                {"title": "Воск", "cost": 400},
            ],
        },
    ]

    stat = _calculate_daily_statistic(
        123,
        date(2026, 8, 2),
        records,
        include_records_without_staff=False,
    )

    assert stat.service_revenue == Decimal("2700")
    assert stat.additional_services_revenue == Decimal("400")


def test_extract_user_token_from_auth_payload_variants() -> None:
    assert _extract_user_token({"user_token": "abc"}) == "abc"
    assert _extract_user_token({"success": True, "data": {"user_token": "def"}}) == "def"
    assert _extract_user_token({"success": True, "data": {}}) is None


def test_record_statistic_date_from_yclients_date_string() -> None:
    assert _record_statistic_date({"date": "2026-07-30 18:00:00"}) == date(2026, 7, 30)


def test_product_page_signature_uses_good_id() -> None:
    first_page = [{"good_id": 1}, {"good_id": 2}]
    second_page = [{"good_id": 3}, {"good_id": 4}]

    assert _products_page_signature(first_page) != _products_page_signature(second_page)


def test_product_stock_uses_actual_amounts() -> None:
    product = _product_from_item(
        {
            "good_id": 22186850,
            "title": "Volcano Увлажняющий крем 50 мл",
            "cost": 3200,
            "category": "VOLCANO",
            "actual_amounts": [{"amount": 1}, {"amount": "2.5"}],
        }
    )

    assert product is not None
    assert product.stock_amount == Decimal("3.5")
    assert product.category == "VOLCANO"


def test_products_sort_stock_goods_before_certificates() -> None:
    products = [
        YClientsProduct(1, "Сертификат «Стрижка»", Decimal("1400"), Decimal("0"), "Сертификаты"),
        YClientsProduct(2, "Reuzel Зеленый 113гр", Decimal("2000"), Decimal("0"), "REUZEL"),
        YClientsProduct(3, "Volcano Увлажняющий крем 50 мл", Decimal("3200"), Decimal("2"), "VOLCANO"),
    ]

    sorted_titles = [product.title for product in sorted(products, key=_product_sort_key)]

    assert sorted_titles == [
        "Reuzel Зеленый 113гр",
        "Volcano Увлажняющий крем 50 мл",
        "Сертификат «Стрижка»",
    ]


def test_visible_products_excludes_certificates_and_out_of_stock() -> None:
    products = [
        YClientsProduct(1, "Сертификат «Стрижка»", Decimal("1400"), Decimal("5"), "Сертификаты"),
        YClientsProduct(2, "Reuzel Зеленый 113гр", Decimal("2000"), Decimal("0"), "REUZEL"),
        YClientsProduct(3, "Volcano Увлажняющий крем 50 мл", Decimal("3200"), Decimal("2"), "VOLCANO"),
    ]

    visible_titles = [product.title for product in _visible_products(products)]

    assert visible_titles == ["Volcano Увлажняющий крем 50 мл"]


def test_product_catalog_chunks_split_without_hidden_tail() -> None:
    products = [
        YClientsProduct(index, f"Nishman Товар {index}", Decimal("1000"), Decimal("1"), "NISHMAN")
        for index in range(1, 8)
    ]

    chunks = _product_catalog_chunks(products, max_chars=120)
    text = "\n".join(line for chunk in chunks for line in chunk)

    assert len(chunks) > 1
    assert "ещё товаров" not in text
    assert "Nishman Товар 7" in text


def test_wrap_text_respects_indented_width() -> None:
    lines = _wrap_text(
        "Стрижка + Оформление бороды + Камуфляж",
        24,
        first_indent="  ",
        next_indent="  ",
    )

    assert all(len(line) <= 24 for line in lines)
    assert lines[0].startswith("  ")


def test_wrap_tokens_keeps_money_values_together() -> None:
    lines = _wrap_tokens(
        ["700 ₽", "1 200 ₽", "2 300 ₽", "3 000 ₽"],
        28,
        indent="  ",
    )

    assert all("3\n" not in line for line in lines)
    assert any("3 000 ₽" in line for line in lines)


def test_employee_settings_button_text_normalization() -> None:
    assert _normalize_button_text("Настройки") == "настройки"
    assert _normalize_button_text("⚙ Настройки") == "настройки"
    assert _normalize_button_text("⚙️ Настройки") == "настройки"
    assert _normalize_button_text("📊 Статистика") == "статистика"
    assert _normalize_button_text("🎯 KPI") == "kpi"
    assert _normalize_button_text("📈 Grade Up") == "grade up"
    assert _normalize_button_text("💇 Услуги") == "услуги"
    assert _normalize_button_text("🧴 Товары") == "товары"
