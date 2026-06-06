import random

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.tenant import User
from app.models.customer import Customer
from app.models.order import Order

router = APIRouter(prefix="/customers", tags=["customers"])

BOTTLE_WEIGHT_KG = 19


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
    current_user: User = Depends(get_current_user)
):
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

    try:
        customer = Customer(
            tenant_id=current_user.tenant_id,
            name=body.name,
            address=body.address,
            lat=body.lat,
            lng=body.lng,
        )
        db.add(customer)
        db.flush()  # customer.id'yi Order'dan önce al

        bottle_count = random.randint(1, 3)
        empty_returns = random.randint(0, bottle_count)
        order = Order(
            tenant_id=current_user.tenant_id,
            customer_id=customer.id,
            status="pending",
            bottle_count=bottle_count,
            empty_returns_expected=empty_returns,
            weight_kg=round(bottle_count * BOTTLE_WEIGHT_KG, 1),
            volume_m3=round(bottle_count * 0.025, 3),
            delivery_lat=body.lat,
            delivery_lng=body.lng,
            delivery_address=body.address,
        )
        db.add(order)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Müşteri kaydedilirken veritabanı hatası oluştu.",
        )

    db.refresh(customer)
    return customer
