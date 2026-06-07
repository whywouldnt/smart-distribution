from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_company_admin
from app.models.tenant import User
from app.crud import crud_vehicle

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

class VehicleCreate(BaseModel):
    plate: str = Field(min_length=2, max_length=20, pattern=r'^[A-Z0-9 ]+$')
    capacity_kg: float = Field(gt=0, le=50000)
    type: Literal["van", "truck", "motorcycle", "bicycle"]
    status: Literal["available", "in_use", "maintenance"] = "available"
    volume_m3: float = Field(ge=0, le=200)

class VehicleResponse(BaseModel):
    id: int
    plate: str
    capacity_kg: float
    type: str
    status: str
    volume_m3: float

    model_config = {"from_attributes": True}

@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def create_vehicle(body: VehicleCreate, db: Session = Depends(get_db), current_admin: User = Depends(get_current_company_admin)):
    # İş kuralı: Plaka daha önce kaydedilmiş mi?
    existing = crud_vehicle.get_vehicle_by_plate(db, current_admin.tenant_id, body.plate)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bu plaka ile kayıtlı bir araç zaten var.",
        )

    # Veritabanı ve kayıt işlemi (Business Logic katmanına sevk)
    return crud_vehicle.create_vehicle(
        db=db,
        tenant_id=current_admin.tenant_id,
        plate=body.plate,
        capacity_kg=body.capacity_kg,
        type=body.type,
        status=body.status,
        volume_m3=body.volume_m3
    )
