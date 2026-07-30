class AppError(Exception):
    """Базовая доменная ошибка приложения."""

    public_message = "Произошла ошибка. Попробуйте ещё раз."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)
        if message:
            self.public_message = message


class AccessDeniedError(AppError):
    public_message = "Доступ запрещён."


class EntityNotFoundError(AppError):
    public_message = "Данные не найдены."


class ValidationError(AppError):
    public_message = "Проверьте введённые данные."


class YClientsError(AppError):
    public_message = "YCLIENTS временно недоступен. Попробуйте позже."


class ConfigurationError(AppError):
    public_message = "Не завершена настройка приложения."
