from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "production"
    log_level: str = "INFO"
    timezone: str = "Europe/Moscow"

    bot_token: str
    admin_password: str
    telegram_request_timeout_seconds: int = 120
    telegram_polling_timeout_seconds: int = 25
    telegram_proxy_url: str | None = None

    database_url: str
    postgres_db: str = "kpi_bot"
    postgres_user: str = "kpi_bot"
    postgres_password: str

    redis_url: str = "redis://redis:6379/0"
    fsm_storage: str = "redis"

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    encryption_key: str

    yclients_base_url: AnyHttpUrl = Field(default="https://api.yclients.com/api/v1")
    yclients_partner_token: str
    yclients_user_token: str | None = None
    yclients_partner_id: int
    yclients_default_company_id: int
    yclients_timeout_seconds: int = 30
    yclients_catalog_cache_ttl_seconds: int = 300
    yclients_statistics_cache_ttl_seconds: int = 300
    yclients_product_max_pages: int = 8

    default_company_title: str = "Барбершоп"
    low_stock_threshold: int = 3
    connection_code_ttl_minutes: int = 15
    sync_interval_minutes: int = 60
    daily_report_cron: str = "0 10 * * *"
    weekly_report_cron: str = "0 11 * * MON"
    monthly_report_cron: str = "0 12 1 * *"

    internal_api_enabled: bool = True
    internal_api_host: str = "0.0.0.0"
    internal_api_port: int = 8080

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("telegram_proxy_url", "yclients_user_token", mode="before")
    @classmethod
    def empty_token_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("fsm_storage")
    @classmethod
    def validate_fsm_storage(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"redis", "memory"}:
            raise ValueError("FSM_STORAGE должен быть redis или memory.")
        return value

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def yclients_base_url_str(self) -> str:
        return str(self.yclients_base_url).rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
