from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Employee
from app.services.statistics import canonical_period, period_kind, shifted_period
from app.utils.telegram_formatting import shorten


def developer_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Панель руководителя", callback_data="dev:admin")],
            [InlineKeyboardButton(text="Войти как барбер", callback_data="dev:employees")],
            [InlineKeyboardButton(text="Войти как франчайзи", callback_data="dev:franchisees")],
            [InlineKeyboardButton(text="Выйти из dev-режима", callback_data="dev:logout")],
        ]
    )


def developer_franchisees_keyboard(franchisees: list) -> InlineKeyboardMarkup:
    rows = []
    for franchisee in franchisees[:80]:
        telegram = ""
        if franchisee.telegram_user and franchisee.telegram_user.username:
            telegram = f" @{franchisee.telegram_user.username}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{shorten(franchisee.title, 30)}{telegram}",
                    callback_data=f"dev:franchisee:{franchisee.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="dev:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def developer_employees_keyboard(employees: list[Employee]) -> InlineKeyboardMarkup:
    rows = []
    for employee in employees[:80]:
        branch = employee.branch.name if employee.branch else "без филиала"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{shorten(employee.full_name, 24)} · {shorten(branch, 24)}",
                    callback_data=f"dev:employee:{employee.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="dev:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def developer_employee_keyboard(employee: Employee) -> InlineKeyboardMarkup:
    employee_id = str(employee.id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data=f"dev:stats:month:{employee_id}")],
            [InlineKeyboardButton(text="KPI", callback_data=f"dev:kpi:{employee_id}")],
            [InlineKeyboardButton(text="Grade Up", callback_data=f"dev:grade:{employee_id}")],
            [InlineKeyboardButton(text="Услуги", callback_data=f"dev:services:{employee_id}")],
            [InlineKeyboardButton(text="Товары", callback_data=f"dev:products:{employee_id}")],
            [InlineKeyboardButton(text="Регламент", callback_data=f"dev:regulation:{employee_id}")],
            [InlineKeyboardButton(text="Назад к барберам", callback_data="dev:employees")],
        ]
    )


def developer_employee_stats_keyboard(
    employees: list[Employee],
    selected_period: str,
    *,
    scope: str = "e",
    scope_id: str | None = None,
) -> InlineKeyboardMarkup:
    current = canonical_period(selected_period)
    kind = period_kind(current)
    root_employee = employees[0]
    scope_id = scope_id or str(root_employee.id)

    def marker(expected_kind: str) -> str:
        return "✅ " if kind == expected_kind else ""

    def data(period: str) -> str:
        return f"devs:{period}:{scope}:{scope_id}"

    rows = [
        [
            InlineKeyboardButton(text="‹", callback_data=data(shifted_period(current, -1))),
            InlineKeyboardButton(text="Обновить", callback_data=data(current)),
            InlineKeyboardButton(text="›", callback_data=data(shifted_period(current, 1))),
        ],
        [
            InlineKeyboardButton(text=f"{marker('day')}День", callback_data=data("today")),
            InlineKeyboardButton(text=f"{marker('week')}Неделя", callback_data=data("week")),
            InlineKeyboardButton(text=f"{marker('month')}Месяц", callback_data=data("month")),
        ],
    ]
    if len(employees) > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text=("✅ Все филиалы" if scope == "a" else "Все филиалы"),
                    callback_data=f"devs:{current}:a:{root_employee.id}",
                )
            ]
        )
        for employee in employees:
            selected = scope == "e" and scope_id == str(employee.id)
            branch_name = employee.branch.name if employee.branch else employee.full_name
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{'✅ ' if selected else ''}{shorten(branch_name, 44)}",
                        callback_data=f"devs:{current}:e:{employee.id}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="Назад к барберу", callback_data=f"dev:employee:{scope_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
