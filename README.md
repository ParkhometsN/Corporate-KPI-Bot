# Corporate KPI Bot

Корпоративный Telegram-бот для барбершопов: админ-панель, привязка сотрудников по одноразовым кодам, обновление данных из YCLIENTS, статистика, KPI, Grade Up, услуги, товары и автоматические отчёты.

## Стек

- Python 3.12
- Aiogram 3.x
- PostgreSQL
- SQLAlchemy 2.0 Async
- Alembic
- Redis
- APScheduler
- FastAPI для внутреннего API
- Docker Compose

## Быстрый запуск через Docker

```bash
docker compose up --build
```

При старте контейнер `bot` выполнит:

```bash
alembic upgrade head
python -m app.main
```

Adminer будет доступен на `http://localhost:8081`.
Внутренний API и Swagger будут доступны на `http://localhost:8080/docs`.

## Переменные окружения

Файл `.env` уже создан локально и добавлен в `.gitignore`. Для переноса на сервер используйте `.env.example` как шаблон.

Главные переменные:

- `BOT_TOKEN` — токен Telegram-бота.
- `ADMIN_PASSWORD` — пароль входа через `/admin`.
- `DATABASE_URL` — async SQLAlchemy URL.
- `REDIS_URL` — Redis для FSM-storage и инфраструктуры.
- `JWT_SECRET_KEY` — подпись внутренних JWT.
- `ENCRYPTION_KEY` — Fernet-ключ для шифрования YCLIENTS-credential в БД.
- `YCLIENTS_PARTNER_TOKEN` — ключ приложения YCLIENTS.
- `YCLIENTS_USER_TOKEN` — User token системного пользователя YCLIENTS. Нужен для закрытых методов, включая записи/статистику/товары, если права API требуют User token.
- `YCLIENTS_PARTNER_ID` — ID партнёра.
- `YCLIENTS_DEFAULT_COMPANY_ID` — ID филиала/компании YCLIENTS по умолчанию.

## Сценарии Telegram

Администратор:

1. Открывает `/admin`.
2. При первом запуске придумывает пароль и автоматически регистрируется как первый администратор.
3. При следующих входах вводит пароль администратора.
4. Попадает в панель:
   - Филиалы
   - Настройки статистики
   - KPI
   - Настройки
   - Проверка подключения
5. Сразу после первой регистрации или в разделе `Настройки` администратор вводит YCLIENTS API key и Partner ID. Бот сохраняет credentials в БД в зашифрованном виде.
6. Раздел `Филиалы` изначально пустой. Когда администратор вводит ID первого филиала, бот подтягивает из YCLIENTS название, адрес, сотрудников, услуги и товары.

Сотрудник:

1. Открывает `/start`.
2. Вводит код подключения от администратора.
3. Получает личное меню:
   - Статистика
   - KPI
   - Grade Up
   - Услуги
   - Товары
   - Настройки

## Миграции

```bash
alembic upgrade head
```

Создать новую миграцию после изменения моделей:

```bash
alembic revision --autogenerate -m "описание изменения"
```

## Внутренний API

Получить JWT:

```bash
curl -X POST http://localhost:8080/api/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"password":"ваш ADMIN_PASSWORD"}'
```

Список филиалов:

```bash
curl http://localhost:8080/api/branches \
  -H 'Authorization: Bearer <JWT>'
```

Проверка подключения и обновление данных филиалов:

```bash
curl -X POST http://localhost:8080/api/branches/sync \
  -H 'Authorization: Bearer <JWT>'
```

## KPI

Правила по умолчанию:

- от `0 ₽` — `0%`
- от `37 000 ₽` — `2%`
- от `60 000 ₽` — `5%`

База KPI считается как:

```text
выручка по услугам + выручка по дополнительным услугам
```

Процент не применяется сразу. Он автоматически начинает применяться со следующего месяца после закрытия текущего.

## Grade Up

Правила по умолчанию:

- `1500 ₽`: средняя дневная выручка `12 500 ₽` за `2` месяца, стаж `6` месяцев.
- `1700 ₽`: средняя дневная выручка `14 500 ₽` за `2` месяца, стаж `6` месяцев.
- `1900 ₽`: средняя дневная выручка `18 000 ₽` за `3` месяца, стаж `12` месяцев.
- `2300 ₽`: средняя дневная выручка `21 000 ₽` за `3` месяца, стаж `12` месяцев.

## Production

- Поменяйте `ADMIN_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, пароль PostgreSQL и все токены перед боевым запуском.
- Не коммитьте `.env`.
- Проверьте права системного пользователя YCLIENTS: без User token часть закрытых методов API может быть недоступна.
- Запускайте контейнеры за reverse proxy с TLS, если внутренний API открыт не только локально.
- Для polling Telegram не нужен внешний webhook URL. Если нужен webhook-режим, его можно добавить отдельным entrypoint.
- APScheduler читает активные расписания из таблицы `schedules`; при первом старте создаются расписания из `.env`.

## Проверки

```bash
python -m compileall app alembic
pytest
```
