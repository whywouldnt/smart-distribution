"""
Dashboard & Liste Endpoint'leri
================================
Yeni UI'ın ihtiyaç duyduğu verileri döndürür:
  - GET /api/v1/dashboard/stats     → Özet KPI kartları
  - GET /api/v1/dashboard/customers → Müşteri + aktif sipariş listesi
  - GET /api/v1/dashboard/vehicles  → Araç listesi ve durum
  - GET /api/v1/dashboard/orders    → Bekleyen sipariş listesi
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.tenant import User
from app.models.customer import Customer
from app.models.order import Order
from app.models.route import Route
from app.models.vehicle import Vehicle

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ── Pydantic Response Modelleri ───────────────────────────────────────────────

class StatsResponse(BaseModel):
    total_customers: int
    pending_orders: int
    available_vehicles: int
    todays_routes: int
    total_bottles_pending: int


class CustomerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    address: str
    lat: float
    lng: float
    pending_orders: int


class OrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    delivery_address: str
    bottle_count: int
    empty_returns_expected: int
    weight_kg: float
    status: str
    priority: int


class VehicleListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate: str
    capacity_kg: float
    type: str
    status: str
    driver_name: Optional[str] = None


# ── Endpoint'ler ──────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """KPI özet kartlarını döndürür."""
    total_customers = db.query(func.count(Customer.id)).filter(Customer.tenant_id == current_user.tenant_id).scalar() or 0

    pending_orders = (
        db.query(func.count(Order.id))
        .filter(Order.tenant_id == current_user.tenant_id)
        .filter(Order.status == "pending")
        .scalar() or 0
    )

    total_bottles_pending = (
        db.query(func.sum(Order.bottle_count))
        .filter(Order.tenant_id == current_user.tenant_id)
        .filter(Order.status == "pending")
        .scalar() or 0
    )

    available_vehicles = (
        db.query(func.count(Vehicle.id))
        .filter(Vehicle.tenant_id == current_user.tenant_id)
        .filter(Vehicle.status == "available")
        .scalar() or 0
    )

    today_start = datetime.combine(date.today(), datetime.min.time())
    todays_routes = (
        db.query(func.count(Route.id))
        .filter(Route.tenant_id == current_user.tenant_id)
        .filter(Route.created_at >= today_start)
        .scalar() or 0
    )

    return StatsResponse(
        total_customers=total_customers,
        pending_orders=pending_orders,
        available_vehicles=available_vehicles,
        todays_routes=todays_routes,
        total_bottles_pending=total_bottles_pending,
    )


@router.get("/customers", response_model=List[CustomerListItem])
def list_customers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Müşterileri bekleyen sipariş sayısıyla döndürür."""
    customers_with_counts = (
        db.query(Customer, func.count(Order.id).label("pending_count"))
        .outerjoin(Order, (Order.customer_id == Customer.id) & (Order.status == "pending"))
        .filter(Customer.tenant_id == current_user.tenant_id)
        .group_by(Customer.id)
        .order_by(Customer.name)
        .all()
    )
    result = []
    for c, pending in customers_with_counts:
        result.append(
            CustomerListItem(
                id=c.id,
                name=c.name,
                address=c.address,
                lat=c.lat,
                lng=c.lng,
                pending_orders=pending,
            )
        )
    return result


@router.get("/orders", response_model=List[OrderListItem])
def list_pending_orders(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Bekleyen siparişleri müşteri adıyla döndürür."""
    orders = (
        db.query(Order)
        .options(joinedload(Order.customer))
        .filter(Order.tenant_id == current_user.tenant_id)
        .filter(Order.status == "pending")
        .order_by(Order.priority.desc(), Order.id)
        .all()
    )
    result = []
    for o in orders:
        result.append(
            OrderListItem(
                id=o.id,
                customer_id=o.customer_id,
                customer_name=o.customer.name if o.customer else None,
                delivery_address=o.delivery_address,
                bottle_count=o.bottle_count,
                empty_returns_expected=o.empty_returns_expected,
                weight_kg=o.weight_kg,
                status=o.status,
                priority=o.priority,
            )
        )
    return result


@router.get("/vehicles", response_model=List[VehicleListItem])
def list_vehicles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Tüm araçları döndürür."""
    vehicles = db.query(Vehicle).filter(Vehicle.tenant_id == current_user.tenant_id).order_by(Vehicle.plate).all()
    return [
        VehicleListItem(
            id=v.id,
            plate=v.plate,
            capacity_kg=v.capacity_kg,
            type=v.type,
            status=v.status,
            driver_name=v.driver_name,
        )
        for v in vehicles
    ]
