from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes import auth, branches, health
from app.config.settings import Settings


def create_api_app(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> FastAPI:
    app = FastAPI(
        title="Corporate KPI Bot Internal API",
        description="Внутренний API корпоративного Telegram KPI-бота.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(branches.router)
    return app

