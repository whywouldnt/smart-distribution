"""
Delivery (Teslimat) Endpoint'leri
===================================
Şoförün saha akışını yöneten API katmanı (Refactored)
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.tenant import User
from app.models.order import Order
from app.models.route_stop import RouteStop
from app.crud import crud_delivery

router = APIRouter(prefix="/delivery", tags=["delivery"])

# ── Pydantic Modelleri ────────────────────────────────────────────────────────

class StopDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stop_sequence: int
    order_id: int
    customer_name: Optional[str] = None
    delivery_address: str
    delivery_lat: float
    delivery_lng: float
    bottle_count: int
    empty_returns_expected: int
    weight_kg: float
    status: str

class VehicleRouteSummary(BaseModel):
    vehicle_id: int
    route_id: int
    plate: str
    driver_name: Optional[str] = None
    vehicle_type: str
    total_stops: int
    completed_stops: int

class TodayRouteResponse(BaseModel):
    route_id: int
    route_name: Optional[str]
    vehicle_id: int
    plate: Optional[str] = None
    driver_name: Optional[str] = None
    total_stops: int
    completed_stops: int
    stops: list[StopDetail]
    route_geometry: Optional[str] = None

class CompleteStopRequest(BaseModel):
    empty_returns_actual: int = 0

class CompleteStopResponse(BaseModel):
    completed_sequence: int
    next_stop: Optional[StopDetail]
    route_complete: bool
    completed_stops: int
    total_stops: int

# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _build_stop_detail(rs: RouteStop) -> StopDetail:
    order: Order = rs.order
    return StopDetail(
        stop_sequence=rs.stop_sequence,
        order_id=rs.order_id,
        customer_name=order.customer.name if order and order.customer else None,
        delivery_address=order.delivery_address if order else "—",
        delivery_lat=order.delivery_lat if order else 0.0,
        delivery_lng=order.delivery_lng if order else 0.0,
        bottle_count=order.bottle_count if order else 0,
        empty_returns_expected=order.empty_returns_expected if order else 0,
        weight_kg=order.weight_kg if order else 0.0,
        status=rs.status,
    )

# ── Endpoint'ler ──────────────────────────────────────────────────────────────

@router.get("/today-routes", response_model=list[VehicleRouteSummary])
def list_today_routes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    routes = crud_delivery.get_today_routes(db, current_user.tenant_id)

    result = []
    for r in routes:
        completed = sum(1 for rs in r.route_stops if rs.status == "completed")
        result.append(VehicleRouteSummary(
            vehicle_id=r.vehicle_id,
            route_id=r.id,
            plate=r.vehicle.plate if r.vehicle else "—",
            driver_name=r.vehicle.driver_name if r.vehicle else None,
            vehicle_type=r.vehicle.type if r.vehicle else "van",
            total_stops=len(r.route_stops),
            completed_stops=completed,
        ))
    return result

@router.get("/today-route", response_model=TodayRouteResponse)
def get_today_route(
    vehicle_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    route = crud_delivery.get_today_route_for_vehicle(db, current_user.tenant_id, vehicle_id)

    if not route:
        detail = (
            f"Araç #{vehicle_id} için bugünkü rota bulunamadı." if vehicle_id
            else "Bugüne ait optimize edilmiş rota bulunamadı. Lütfen önce 'Dağıtımı Optimize Et' butonuna basın."
        )
        raise HTTPException(status_code=404, detail=detail)

    sorted_stops = sorted(route.route_stops, key=lambda rs: rs.stop_sequence)
    completed_count = sum(1 for rs in sorted_stops if rs.status == "completed")

    return TodayRouteResponse(
        route_id=route.id,
        route_name=route.name,
        vehicle_id=route.vehicle_id,
        plate=route.vehicle.plate if route.vehicle else None,
        driver_name=route.vehicle.driver_name if route.vehicle else None,
        total_stops=len(sorted_stops),
        completed_stops=completed_count,
        stops=[_build_stop_detail(rs) for rs in sorted_stops],
        route_geometry=route.route_geometry,
    )

@router.patch("/routes/{route_id}/stops/{stop_sequence}/complete", response_model=CompleteStopResponse)
def complete_stop(
    route_id: int,
    stop_sequence: int,
    body: CompleteStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    route = crud_delivery.get_route_with_stops(db, current_user.tenant_id, route_id)
    if not route:
        raise HTTPException(status_code=404, detail=f"Rota bulunamadı: id={route_id}")

    sorted_stops = sorted(route.route_stops, key=lambda rs: rs.stop_sequence)
    
    target_stop = next((rs for rs in sorted_stops if rs.stop_sequence == stop_sequence), None)
    if not target_stop:
        raise HTTPException(status_code=404, detail="Durak bulunamadı.")

    # Sıra atlama koruması (Validation)
    for prev in sorted_stops:
        if prev.stop_sequence >= stop_sequence:
            break
        if prev.status not in ("completed", "skipped"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Durak {prev.stop_sequence} henüz tamamlanmadı. Lütfen sırayla ilerleyin.",
            )

    # İdempotency (Veritabanı Katmanına Sevk)
    if target_stop.status != "completed":
        try:
            crud_delivery.mark_stop_completed(db, target_stop)
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="Teslim kaydedilirken veritabanı hatası oluştu.")

    # Sonraki durağı belirle
    remaining = [rs for rs in sorted_stops if rs.stop_sequence > stop_sequence and rs.status not in ("completed", "skipped")]
    next_detail = _build_stop_detail(min(remaining, key=lambda rs: rs.stop_sequence)) if remaining else None

    completed_count = sum(1 for rs in sorted_stops if rs.status == "completed")
    processed_count = sum(1 for rs in sorted_stops if rs.status in ("completed", "skipped"))
    route_complete = processed_count == len(sorted_stops)

    # Rota tamamen bittiyse güncelle (CRUD Katmanına Sevk)
    if route_complete and route.status != "completed":
        try:
            crud_delivery.mark_route_completed(db, route)
        except Exception:
            db.rollback()

    return CompleteStopResponse(
        completed_sequence=stop_sequence,
        next_stop=next_detail,
        route_complete=route_complete,
        completed_stops=completed_count,
        total_stops=len(sorted_stops),
    )

@router.patch("/routes/{route_id}/stops/{stop_sequence}/skip", response_model=CompleteStopResponse)
def skip_stop(
    route_id: int,
    stop_sequence: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    route = crud_delivery.get_route_with_stops(db, current_user.tenant_id, route_id)
    if not route:
        raise HTTPException(status_code=404, detail=f"Rota bulunamadı: id={route_id}")

    sorted_stops = sorted(route.route_stops, key=lambda rs: rs.stop_sequence)
    
    target_stop = next((rs for rs in sorted_stops if rs.stop_sequence == stop_sequence), None)
    if not target_stop:
        raise HTTPException(status_code=404, detail="Durak bulunamadı.")

    # İdempotency (Veritabanı Katmanına Sevk)
    if target_stop.status not in ("completed", "skipped"):
        try:
            target_stop.status = "skipped"
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="Atlama kaydedilirken hata oluştu.")

    # Sonraki durağı belirle
    remaining = [rs for rs in sorted_stops if rs.stop_sequence > stop_sequence and rs.status not in ("completed", "skipped")]
    next_detail = _build_stop_detail(min(remaining, key=lambda rs: rs.stop_sequence)) if remaining else None

    completed_count = sum(1 for rs in sorted_stops if rs.status == "completed")
    processed_count = sum(1 for rs in sorted_stops if rs.status in ("completed", "skipped"))
    route_complete = processed_count == len(sorted_stops)

    # Rota tamamen bittiyse güncelle
    if route_complete and route.status != "completed":
        try:
            crud_delivery.mark_route_completed(db, route)
        except Exception:
            db.rollback()

    return CompleteStopResponse(
        completed_sequence=stop_sequence,
        next_stop=next_detail,
        route_complete=route_complete,
        completed_stops=completed_count,
        total_stops=len(sorted_stops),
    )
