from fastapi import APIRouter, Depends

from app.api.dependencies import get_settings_from_app
from app.config.settings import Settings
from app.schemas.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings_from_app)) -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment)

