from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.models import Branch, Employee


def admin_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Филиалы"), KeyboardButton(text="Статистика команды")],
            [KeyboardButton(text="Действия для барберов"), KeyboardButton(text="Регламент компании")],
            [KeyboardButton(text="Франчайзи"), KeyboardButton(text="Настройки руководителя")],
            [KeyboardButton(text="Проверка подключения")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Панель руководителя",
    )


def available_branches_keyboard(available_branches: list, existing_branch_ids: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for branch in available_branches[:30]:
        if branch.id in existing_branch_ids:
            rows.append(
                [InlineKeyboardButton(text=f"✅ {branch.title}", callback_data=f"available_branch:exists:{branch.id}")]
            )
        else:
            rows.append(
                [InlineKeyboardButton(text=f"Добавить: {branch.title}", callback_data=f"available_branch:add:{branch.id}")]
            )
    rows.append([InlineKeyboardButton(text="Ввести ID вручную", callback_data="admin:add_branch")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Обновить YCLIENTS", callback_data="admin:setup_yclients")],
            [InlineKeyboardButton(text="Войти в YCLIENTS", callback_data="admin:yclients_login")],
            [InlineKeyboardButton(text="Обновить User token", callback_data="admin:setup_user_token")],
            [InlineKeyboardButton(text="Настройка KPI", callback_data="admin:kpi")],
            [InlineKeyboardButton(text="Настройка Grade Up", callback_data="admin:grade")],
            [InlineKeyboardButton(text="Руководители филиалов", callback_data="admin:franchisees")],
            [InlineKeyboardButton(text="Регламент", callback_data="admin:regulation")],
            [InlineKeyboardButton(text="Сброс до регистрации", callback_data="admin:reset")],
            [InlineKeyboardButton(text="Назад", callback_data="admin:dashboard")],
        ]
    )


def yclients_login_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:yclients_login_cancel")],
        ]
    )


def admin_regulation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить регламент", callback_data="admin:regulation_edit")],
            [InlineKeyboardButton(text="Назад", callback_data="admin:dashboard")],
        ]
    )


def admin_regulation_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:regulation_cancel")],
        ]
    )


def admin_kpi_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить правила KPI", callback_data="admin:kpi_edit")],
            [InlineKeyboardButton(text="Назад", callback_data="admin:dashboard")],
        ]
    )


def admin_kpi_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:kpi_cancel")],
        ]
    )


def admin_grade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить правила Grade Up", callback_data="admin:grade_edit")],
            [InlineKeyboardButton(text="Назад", callback_data="admin:dashboard")],
        ]
    )


def admin_grade_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:grade_cancel")],
        ]
    )


def admin_reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, сбросить", callback_data="admin:reset_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:settings")],
        ]
    )


def broadcast_branch_keyboard(branches: list[Branch]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Все филиалы", callback_data="broadcast:branch:all")]]
    rows.extend(
        [InlineKeyboardButton(text=branch.name, callback_data=f"broadcast:branch:{branch.id}")]
        for branch in branches
    )
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить сообщение", callback_data="broadcast:action:message")],
            [InlineKeyboardButton(text="Статистика за текущий месяц", callback_data="broadcast:action:stats")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
        ]
    )


def broadcast_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить", callback_data=f"broadcast:confirm:{action}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
        ]
    )


def broadcast_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
        ]
    )


def branches_keyboard(branches: list[Branch]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=branch.name, callback_data=f"branch:{branch.id}")]
        for branch in branches
    ]
    rows.append([InlineKeyboardButton(text="Показать доступные филиалы", callback_data="admin:available_branches")])
    rows.append([InlineKeyboardButton(text="Добавить филиал", callback_data="admin:add_branch")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def branch_dashboard_keyboard(branch_id: UUID) -> InlineKeyboardMarkup:
    branch = str(branch_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сотрудники", callback_data=f"branch:employees:{branch}")],
            [InlineKeyboardButton(text="Статистика", callback_data=f"branch:stats:month:{branch}")],
            [InlineKeyboardButton(text="✅ Проверка подключения", callback_data=f"branch:check:{branch}")],
            [InlineKeyboardButton(text="Удалить филиал", callback_data=f"branch:delete:{branch}")],
            [InlineKeyboardButton(text="Назад", callback_data="admin:branches")],
        ]
    )


def branch_delete_confirm_keyboard(branch_id: UUID) -> InlineKeyboardMarkup:
    branch = str(branch_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить филиал", callback_data=f"branch:delete_confirm:{branch}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"branch:{branch}")],
        ]
    )


def employees_keyboard(branch_id: UUID, employees: list[Employee]) -> InlineKeyboardMarkup:
    rows = []
    for employee in employees:
        if employee.telegram_user:
            username = f" @{employee.telegram_user.username}" if employee.telegram_user.username else ""
            text = f"✅ {employee.full_name}{username}"
        else:
            text = f"❌ {employee.full_name}"
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f"employee:{employee.id}")]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"branch:{branch_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def employee_admin_keyboard(employee: Employee) -> InlineKeyboardMarkup:
    employee_id = str(employee.id)
    rows = []
    if employee.telegram_user_id:
        rows.extend(
            [
                [InlineKeyboardButton(text="Смотреть статистику", callback_data=f"employee:stats:{employee_id}")],
                [InlineKeyboardButton(text="Переподключить Telegram", callback_data=f"employee:code:{employee_id}")],
                [InlineKeyboardButton(text="Отключить", callback_data=f"employee:disconnect:{employee_id}")],
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="Подключить сотрудника", callback_data=f"employee:code:{employee_id}")]
        )
    rows.append([InlineKeyboardButton(text="Назад к филиалам", callback_data="admin:branches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_employees_keyboard(branch_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад к сотрудникам", callback_data=f"branch:employees:{branch_id}")],
        ]
    )


def branch_stats_period_keyboard(branch_id: UUID, selected_period: str) -> InlineKeyboardMarkup:
    branch = str(branch_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _period_buttons("branch:stats", branch, selected_period),
            [InlineKeyboardButton(text="Назад к филиалу", callback_data=f"branch:{branch}")],
        ]
    )


def team_stats_period_keyboard(selected_period: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            _period_buttons("admin:team_stats", None, selected_period),
            [InlineKeyboardButton(text="Назад", callback_data="admin:dashboard")],
        ]
    )


def _period_buttons(prefix: str, branch: str | None, selected_period: str) -> list[InlineKeyboardButton]:
    periods = (("today", "День"), ("week", "Неделя"), ("month", "Месяц"))
    buttons = []
    for period, title in periods:
        marker = "✅ " if period == selected_period else ""
        callback_data = f"{prefix}:{period}:{branch}" if branch else f"{prefix}:{period}"
        buttons.append(InlineKeyboardButton(text=f"{marker}{title}", callback_data=callback_data))
    return buttons


def franchisees_keyboard(franchisees: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_franchisee_button_text(franchisee), callback_data=f"franchise:{franchisee.id}")]
        for franchisee in franchisees
    ]
    rows.append([InlineKeyboardButton(text="Создать ссылку подключения", callback_data="franchise:invite")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def franchisee_keyboard(franchisee, branches: list[Branch]) -> InlineKeyboardMarkup:
    franchisee_id = str(franchisee.id)
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ Видит филиалы руководителя" if franchisee.can_view_owner_branches else "❌ Видит филиалы руководителя"),
                callback_data=f"frt:v:{franchisee_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=("✅ Может писать сотрудникам" if franchisee.can_message_owner_employees else "❌ Может писать сотрудникам"),
                callback_data=f"frt:m:{franchisee_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=("✅ Получает статистику" if franchisee.can_receive_owner_statistics else "❌ Получает статистику"),
                callback_data=f"frt:s:{franchisee_id}",
            )
        ],
    ]
    rows.extend(_franchise_branch_rows(franchisee, branches))
    rows.append(
        [
            InlineKeyboardButton(
                text="Разблокировать" if franchisee.is_blocked else "Заблокировать",
                callback_data=f"franchise:{'unblock' if franchisee.is_blocked else 'block'}:{franchisee_id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="Удалить", callback_data=f"franchise:delete:{franchisee_id}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin:franchisees")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def franchise_delete_confirm_keyboard(franchisee_id: UUID) -> InlineKeyboardMarkup:
    value = str(franchisee_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"franchise:delete_confirm:{value}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"franchise:{value}")],
        ]
    )


def _franchisee_button_text(franchisee) -> str:
    marker = "❌" if franchisee.is_blocked else "✅"
    username = f" @{franchisee.telegram_user.username}" if franchisee.telegram_user and franchisee.telegram_user.username else ""
    return f"{marker} {franchisee.title}{username}"


def _franchise_branch_rows(franchisee, branches: list[Branch]) -> list[list[InlineKeyboardButton]]:
    access_by_branch = {access.branch_id: access for access in franchisee.branch_accesses}
    rows: list[list[InlineKeyboardButton]] = []
    for index, branch in enumerate(branches[:20]):
        access = access_by_branch.get(branch.id)
        view = bool(access and access.is_active and access.can_view_statistics)
        message = bool(access and access.is_active and access.can_message_employees)
        manage = bool(access and access.is_active and access.can_manage_employees)
        rows.append([InlineKeyboardButton(text=f"{branch.name}", callback_data=f"franchise:{franchisee.id}")])
        rows.append(
            [
                InlineKeyboardButton(text=("✅ Стат." if view else "❌ Стат."), callback_data=f"frb:v:{franchisee.id}:{index}"),
                InlineKeyboardButton(text=("✅ Сообщ." if message else "❌ Сообщ."), callback_data=f"frb:m:{franchisee.id}:{index}"),
                InlineKeyboardButton(text=("✅ Управл." if manage else "❌ Управл."), callback_data=f"frb:g:{franchisee.id}:{index}"),
            ]
        )
    return rows
