from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings_from_app, require_internal_admin
from app.config.settings import Settings
from app.repositories import CompanyRepository
from app.schemas.api import BranchResponse
from app.services import build_services

router = APIRouter(prefix="/api/branches", tags=["branches"])


@router.get("", response_model=list[BranchResponse])
async def list_branches(
    _: dict = Depends(require_internal_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_from_app),
) -> list[BranchResponse]:
    services = build_services(session, settings)
    branches = await services.admin.list_branches()
    return [BranchResponse.model_validate(branch) for branch in branches]


@router.post("/sync", response_model=list[BranchResponse])
async def sync_branches(
    _: dict = Depends(require_internal_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_from_app),
) -> list[BranchResponse]:
    services = build_services(session, settings)
    company = await CompanyRepository(session).get_default()
    branches = await services.sync.sync_company(company)
    return [BranchResponse.model_validate(branch) for branch in branches]

