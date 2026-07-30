from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.config.settings import Settings
from app.utils.exceptions import ConfigurationError, YClientsError
from app.yclients.types import (
    YClientsBranch,
    YClientsDailyStatistic,
    YClientsEmployee,
    YClientsProduct,
    YClientsService,
)


class YClientsApiError(YClientsError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class YClientsClient:
    def __init__(
        self,
        *,
        base_url: str,
        partner_token: str,
        user_token: str | None,
        timeout_seconds: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._partner_token = partner_token
        self._user_token = user_token
        self._timeout = httpx.Timeout(timeout_seconds)

    @classmethod
    def from_settings(cls, settings: Settings) -> "YClientsClient":
        return cls(
            base_url=settings.yclients_base_url_str,
            partner_token=settings.yclients_partner_token,
            user_token=settings.yclients_user_token,
            timeout_seconds=settings.yclients_timeout_seconds,
        )

    async def validate_connection(self, company_id: int) -> bool:
        await self.get_company(company_id)
        return True

    async def authenticate_user(self, login: str, password: str) -> str:
        if not login.strip() or not password:
            raise ConfigurationError("Введите логин и пароль YCLIENTS.")
        payload = await self._request(
            "POST",
            "auth",
            json={"login": login.strip(), "password": password},
        )
        user_token = _extract_user_token(payload)
        if user_token:
            return user_token
        raise YClientsApiError(_auth_token_missing_message(payload))

    async def get_company(self, company_id: int) -> YClientsBranch:
        data = await self._request("GET", f"company/{company_id}")
        payload = self._unwrap_data(data)
        return YClientsBranch(
            id=_to_int(payload.get("id") or company_id),
            title=str(payload.get("title") or payload.get("name") or f"Филиал {company_id}"),
            address=payload.get("address"),
        )

    async def list_branches(self, partner_id: int) -> list[YClientsBranch]:
        data = await self._request("GET", "companies", params={"group_id": partner_id})
        items = self._as_list(self._unwrap_data(data))
        return [
            YClientsBranch(
                id=_to_int(item.get("id")),
                title=str(item.get("title") or item.get("name") or f"Филиал {item.get('id')}"),
                address=item.get("address"),
            )
            for item in items
            if item.get("id") is not None
        ]

    async def list_employees(self, company_id: int) -> list[YClientsEmployee]:
        data = await self._request("GET", f"staff/{company_id}/")
        items = self._as_list(self._unwrap_data(data))
        employees: list[YClientsEmployee] = []
        for item in items:
            if item.get("id") is None or not _is_active_staff(item):
                continue
            specialization = _extract_specialization(item)
            employees.append(
                YClientsEmployee(
                    id=_to_int(item.get("id")),
                    name=str(item.get("name") or item.get("fullname") or "Без имени"),
                    specialization=specialization,
                    category_title=_extract_category(item) or specialization,
                )
            )
        return employees

    async def list_services(self, company_id: int) -> list[YClientsService]:
        data = await self._request("GET", f"services/{company_id}/")
        items = _flatten_services(self._unwrap_data(data))
        return [
            YClientsService(
                id=_to_int(item.get("id") or item.get("salon_service_id")),
                title=str(item.get("title") or item.get("booking_title") or "Услуга"),
                category=item.get("category_title") or item.get("category", {}).get("title"),
                price_min=_to_decimal(item.get("price_min") or item.get("price") or 0),
                price_max=_to_decimal(item.get("price_max") or item.get("price") or 0),
            )
            for item in items
            if item.get("id") is not None or item.get("salon_service_id") is not None
        ]

    async def list_products(self, company_id: int) -> list[YClientsProduct]:
        endpoints = (
            f"goods/{company_id}/",
            f"products/{company_id}/",
            f"storage_goods/{company_id}/",
        )
        auth_modes = (True, False) if self._user_token else (False,)
        last_error: YClientsApiError | None = None
        permission_error: YClientsApiError | None = None
        for user_required in auth_modes:
            for endpoint in endpoints:
                try:
                    data = await self._request("GET", endpoint, user_required=user_required)
                    items = self._as_list(self._unwrap_data(data))
                    return [
                        YClientsProduct(
                            id=_to_int(item.get("id") or item.get("good_id") or item.get("product_id")),
                            title=str(item.get("title") or item.get("name") or "Товар"),
                            price=_to_decimal(item.get("price") or item.get("cost") or 0),
                            stock_amount=_to_decimal(
                                item.get("amount")
                                or item.get("stock_amount")
                                or item.get("quantity")
                                or item.get("balance")
                                or 0
                            ),
                        )
                        for item in items
                        if item.get("id") is not None
                        or item.get("good_id") is not None
                        or item.get("product_id") is not None
                    ]
                except YClientsApiError as exc:
                    if exc.status_code in {401, 403}:
                        permission_error = exc
                    if exc.status_code in {401, 403, 404, 405}:
                        last_error = exc
                        continue
                    raise
        if permission_error is not None:
            raise permission_error
        if last_error is not None:
            if last_error.status_code in {404, 405}:
                return []
            raise last_error
        return []

    async def get_daily_statistics(
        self,
        *,
        company_id: int,
        employee_staff_id: int,
        statistic_date: date,
    ) -> YClientsDailyStatistic:
        data = await self._request(
            "GET",
            f"records/{company_id}",
            params={
                "staff_id": employee_staff_id,
                "start_date": statistic_date.isoformat(),
                "end_date": statistic_date.isoformat(),
            },
            user_required=True,
        )
        records = self._as_list(self._unwrap_data(data))
        return _calculate_daily_statistic(employee_staff_id, statistic_date, records)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        user_required: bool = False,
    ) -> dict[str, Any] | list[Any]:
        if user_required and not self._user_token:
            raise ConfigurationError("Для этого метода YCLIENTS нужен User token.")

        headers = {
            "Accept": "application/vnd.yclients.v2+json",
            "Content-Type": "application/json",
            "Authorization": self._authorization_header(user_required=user_required),
        }
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise YClientsApiError(f"Ошибка сети YCLIENTS: {exc}") from exc

        if response.status_code >= 400:
            raise YClientsApiError(
                f"YCLIENTS вернул HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise YClientsApiError("YCLIENTS вернул некорректный JSON.") from exc

        if isinstance(payload, dict) and payload.get("success") is False:
            meta = payload.get("meta") or {}
            message = meta.get("message") or payload.get("message") or "YCLIENTS отклонил запрос."
            raise YClientsApiError(str(message), status_code=response.status_code)
        return payload

    def _authorization_header(self, *, user_required: bool) -> str:
        if user_required and self._user_token:
            return f"Bearer {self._partner_token}, User {self._user_token}"
        return f"Bearer {self._partner_token}"

    @staticmethod
    def _unwrap_data(payload: dict[str, Any] | list[Any]) -> Any:
        if isinstance(payload, dict):
            return payload.get("data", payload)
        return payload

    @staticmethod
    def _as_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("items", "data", "records", "staff", "services", "goods", "products"):
                nested = value.get(key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
        return []


def _flatten_services(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            nested_services = item.get("services")
            if isinstance(nested_services, list):
                for service in nested_services:
                    if isinstance(service, dict):
                        service.setdefault("category_title", item.get("title"))
                        items.append(service)
            else:
                items.append(item)
        return items
    if isinstance(value, dict):
        for key in ("items", "services", "data"):
            nested = value.get(key)
            if nested is not None:
                return _flatten_services(nested)
    return []


def _extract_user_token(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("user_token", "token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("data", "user", "result"):
        nested = payload.get(key)
        token = _extract_user_token(nested)
        if token:
            return token
    return None


def _auth_token_missing_message(payload: Any) -> str:
    message = _extract_payload_message(payload)
    hint = (
        "YCLIENTS принял логин и пароль, но не вернул User token. "
        "Если у аккаунта включена двухэтапная аутентификация, используйте ручной User token "
        "или временно отключите 2FA для получения токена."
    )
    return f"{hint} Ответ YCLIENTS: {message[:200]}" if message else hint


def _extract_payload_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if isinstance(meta, dict):
        meta_message = meta.get("message")
        if meta_message:
            return str(meta_message)
    for key in ("message", "error", "error_description"):
        value = payload.get(key)
        if value:
            return str(value)
    for key in ("data", "user", "result"):
        message = _extract_payload_message(payload.get(key))
        if message:
            return message
    return None


def _extract_category(item: dict[str, Any]) -> str | None:
    for key in ("category_title", "category", "rank", "level"):
        value = item.get(key)
        if isinstance(value, dict):
            title = value.get("title") or value.get("name")
            if title:
                return str(title)
        if value:
            return str(value)
    return None


def _extract_specialization(item: dict[str, Any]) -> str | None:
    specialization = item.get("specialization")
    if specialization:
        return str(specialization)
    position = item.get("position")
    if isinstance(position, dict):
        title = position.get("title") or position.get("name")
        return str(title) if title else None
    return None


def _is_active_staff(item: dict[str, Any]) -> bool:
    for key in ("is_active", "active"):
        if key in item and not _boolish_true(item.get(key)):
            return False
    for key in (
        "deleted",
        "is_deleted",
        "dismissed",
        "is_dismissed",
        "fired",
        "is_fired",
        "archived",
        "is_archived",
    ):
        if _boolish_true(item.get(key)):
            return False
    status = str(item.get("status") or item.get("state") or "").casefold()
    return status in {"", "0", "active", "working"}


def _boolish_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "да"}
    return bool(value)


def _calculate_daily_statistic(
    employee_staff_id: int,
    statistic_date: date,
    records: Iterable[dict[str, Any]],
) -> YClientsDailyStatistic:
    records_list = list(records)
    visited_records = [record for record in records_list if _is_attended(record)]

    haircuts_count = len(visited_records)
    service_revenue = Decimal("0")
    additional_services_revenue = Decimal("0")
    products_revenue = Decimal("0")
    products_sold = 0

    for record in visited_records:
        services = _extract_record_services(record)
        if services:
            service_revenue += _service_cost(services[0])
            additional_services_revenue += sum((_service_cost(item) for item in services[1:]), Decimal("0"))
        else:
            service_revenue += _to_decimal(
                record.get("services_cost") or record.get("paid_full") or record.get("sum") or 0
            )
        goods = _extract_record_goods(record)
        products_sold += len(goods)
        products_revenue += sum((_to_decimal(item.get("cost") or item.get("price") or item.get("sum") or 0) for item in goods), Decimal("0"))

    total_revenue = service_revenue + additional_services_revenue + products_revenue
    average_check = total_revenue / haircuts_count if haircuts_count else Decimal("0")
    attendance_percent = (
        Decimal(haircuts_count) / Decimal(len(records_list)) * Decimal("100")
        if records_list
        else Decimal("0")
    )

    return YClientsDailyStatistic(
        employee_staff_id=employee_staff_id,
        statistic_date=statistic_date,
        haircuts_count=haircuts_count,
        service_revenue=service_revenue,
        additional_services_revenue=additional_services_revenue,
        total_revenue=total_revenue,
        average_check=average_check,
        attendance_percent=attendance_percent,
        products_sold=products_sold,
        products_revenue=products_revenue,
        raw_payload={"records": records_list},
    )


def _extract_record_services(record: dict[str, Any]) -> list[dict[str, Any]]:
    services = record.get("services") or record.get("visit_services") or []
    return [item for item in services if isinstance(item, dict)] if isinstance(services, list) else []


def _extract_record_goods(record: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("goods_transactions", "goods", "products"):
        value = record.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _service_cost(service: dict[str, Any]) -> Decimal:
    return _to_decimal(service.get("cost") or service.get("price") or service.get("sum") or 0)


def _is_attended(record: dict[str, Any]) -> bool:
    attendance = record.get("attendance")
    if attendance is None:
        return True
    return str(attendance) not in {"-1", "0", "not_come", "no_show", "cancelled"}


def _to_int(value: Any) -> int:
    return int(value or 0)


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")
