from aiogram import Router

from app.bot.handlers import admin, common, developer, employee


def setup_router() -> Router:
    router = Router(name="root")
    router.include_router(developer.router)
    router.include_router(common.router)
    router.include_router(employee.router)
    router.include_router(admin.router)
    return router
