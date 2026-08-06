from app.models import Role

_DEVELOPER_SESSION_IDS: set[int] = set()
_DEVELOPER_PREVIOUS_ROLES: dict[int, Role | None] = {}
_DEVELOPER_IMPERSONATION_TARGETS: dict[int, int] = {}


def start_session(telegram_id: int, previous_role: Role | None) -> None:
    _DEVELOPER_PREVIOUS_ROLES.setdefault(telegram_id, previous_role)
    _DEVELOPER_SESSION_IDS.add(telegram_id)


def end_session(telegram_id: int) -> Role | None:
    _DEVELOPER_SESSION_IDS.discard(telegram_id)
    _DEVELOPER_IMPERSONATION_TARGETS.pop(telegram_id, None)
    return _DEVELOPER_PREVIOUS_ROLES.pop(telegram_id, None)


def is_developer_session(telegram_id: int) -> bool:
    return telegram_id in _DEVELOPER_SESSION_IDS


def set_impersonation(telegram_id: int, target_telegram_id: int | None) -> None:
    if target_telegram_id is None:
        _DEVELOPER_IMPERSONATION_TARGETS.pop(telegram_id, None)
        return
    _DEVELOPER_IMPERSONATION_TARGETS[telegram_id] = target_telegram_id


def effective_telegram_id(telegram_id: int) -> int:
    if telegram_id not in _DEVELOPER_SESSION_IDS:
        return telegram_id
    return _DEVELOPER_IMPERSONATION_TARGETS.get(telegram_id, telegram_id)
