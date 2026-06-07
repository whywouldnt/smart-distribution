import random

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_company_admin
from app.models.tenant import User
from app.models.customer import Customer
from app.models.order import Order

from app.crud import crud_customer

router = APIRouter(prefix="/customers", tags=["customers"])

class CustomerCreate(BaseModel):
    name: str
    address: str
    lat: float
    lng: float

class CustomerResponse(BaseModel):
    id: int
    name: str
    address: str
    lat: float
    lng: float

    model_config = {"from_attributes": True}

@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    body: CustomerCreate, 
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_company_admin)
):
    # Sadece İş Kuralları ve Veri Doğrulama (Validation)
    if not (-90 <= body.lat <= 90):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enlem (lat) -90 ile 90 arasında olmalıdır.",
        )
    if not (-180 <= body.lng <= 180):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Boylam (lng) -180 ile 180 arasında olmalıdır.",
        )

    # Veritabanı ve İş Mantığı (Business Logic) ayrıştırıldı!
    try:
        return crud_customer.create_customer_with_order(
            db=db,
            tenant_id=current_admin.tenant_id,
            name=body.name,
            address=body.address,
            lat=body.lat,
            lng=body.lng
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Müşteri kaydedilirken veritabanı hatası oluştu.",
        )
