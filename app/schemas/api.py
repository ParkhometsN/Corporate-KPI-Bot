from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TokenRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HealthResponse(BaseModel):
    status: str
    environment: str


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    yclients_branch_id: int
    name: str
    address: str | None
    sync_status: str
    employees_count: int
    last_synced_at: datetime | None

