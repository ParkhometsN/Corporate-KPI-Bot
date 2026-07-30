from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings_from_app
from app.config.settings import Settings
from app.repositories import CompanyRepository
from app.schemas.api import TokenRequest, TokenResponse
from app.services.security import JwtService, PasswordService

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def create_token(
    payload: TokenRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_from_app),
) -> TokenResponse:
    company = await CompanyRepository(session).get_default()
    if company is None or not PasswordService().verify_password(payload.password, company.admin_password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный пароль.")
    token = JwtService(settings).create_access_token("internal-admin", {"role": "admin"})
    return TokenResponse(access_token=token)

