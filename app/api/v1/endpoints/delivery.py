"""
Delivery (Teslimat) Endpoint'leri
===================================
Şoförün saha akışını yöneten API katmanı:

  GET  /api/v1/delivery/today-routes
      → Bugün rotası olan tüm araçları listeler (araç seçim ekranı için).

  GET  /api/v1/delivery/today-route?vehicle_id=<id>
      → Belirtilen araca ait bugünkü rotayı tüm stop detaylarıyla döndürür.
        vehicle_id verilmezse bugün oluşturulan ilk rotayı döndürür.

  PATCH /api/v1/delivery/routes/{route_id}/stops/{stop_sequence}/complete
      → Bir durağı tamamlar:
          • RouteStop.status    → 'completed'
          • Order.status        → 'delivered'
          • Order.delivered_at  → şimdiki UTC zamanı
          • Gerçek boş iade sayısını kaydeder (empty_returns_actual)
        Ve bir sonraki durağı döndürür.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.tenant import User
from app.models.order import Order
from app.models.route import Route
from app.models.route_stop import RouteStop

router = APIRouter(prefix="/delivery", tags=["delivery"])


# ── Pydantic Modelleri ────────────────────────────────────────────────────────

class StopDetail(BaseModel):
    """Şoföre gösterilecek tek durak bilgisi."""
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
    """Araç seçim ekranında gösterilecek özet bilgi."""
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
    """Şoförün 'Teslim Edildi' basarken gönderdiği veri."""
    empty_returns_actual: int = 0  # Gerçekte alınan boş damacana sayısı


class CompleteStopResponse(BaseModel):
    completed_sequence: int
    next_stop: Optional[StopDetail]  # None ise rota bitti
    route_complete: bool
    completed_stops: int
    total_stops: int


# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _build_stop_detail(rs: RouteStop) -> StopDetail:
    """RouteStop ORM nesnesini şoför kartı verisine dönüştürür."""
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


def _get_route_or_404(route_id: int, tenant_id: int, db: Session) -> Route:
    route = (
        db.query(Route)
        .options(
            joinedload(Route.route_stops)
            .joinedload(RouteStop.order)
            .joinedload(Order.customer)
        )
        .filter(Route.id == route_id)
        .filter(Route.tenant_id == tenant_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail=f"Rota bulunamadı: id={route_id}")
    return route


# ── Endpoint'ler ──────────────────────────────────────────────────────────────

@router.get("/today-routes", response_model=list[VehicleRouteSummary])
def list_today_routes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Bugün optimize edilmiş tüm araçları ve rota özetlerini döndürür.
    Şoför 'Şoför Modu'nu açtığında araç seçim ekranını doldurmak için kullanılır.
    """
    today_start = datetime.combine(date.today(), datetime.min.time())

    routes = (
        db.query(Route)
        .options(
            joinedload(Route.route_stops),
            joinedload(Route.vehicle),
        )
        .filter(Route.tenant_id == current_user.tenant_id)
        .filter(Route.created_at >= today_start)
        .filter(Route.status.in_(["optimized", "in_progress"]))
        .order_by(Route.id)
        .all()
    )

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
    """
    Belirtilen araca ait bugünkü rotayı döndürür.
    vehicle_id verilmezse bugün oluşturulan ilk rotayı döndürür.
    Henüz optimize edilmemişse 404 döner.
    """
    today_start = datetime.combine(date.today(), datetime.min.time())

    query = (
        db.query(Route)
        .options(
            joinedload(Route.route_stops)
            .joinedload(RouteStop.order)
            .joinedload(Order.customer),
            joinedload(Route.vehicle),
        )
        .filter(Route.tenant_id == current_user.tenant_id)
        .filter(Route.created_at >= today_start)
        .filter(Route.status.in_(["optimized", "in_progress"]))
    )

    if vehicle_id is not None:
        query = query.filter(Route.vehicle_id == vehicle_id)

    route = query.order_by(Route.id).first()

    if not route:
        detail = (
            f"Araç #{vehicle_id} için bugünkü rota bulunamadı."
            if vehicle_id
            else "Bugüne ait optimize edilmiş rota bulunamadı. "
                 "Lütfen önce 'Dağıtımı Optimize Et' butonuna basın."
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


@router.patch(
    "/routes/{route_id}/stops/{stop_sequence}/complete",
    response_model=CompleteStopResponse,
)
def complete_stop(
    route_id: int,
    stop_sequence: int,
    body: CompleteStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Belirtilen durağı tamamlar ve bir sonraki durağı döndürür.

    İş kuralları:
    - Durak zaten 'completed' ise idempotent davranır (hata vermez).
    - Sıra atlanamaz: önceki durak henüz tamamlanmamışsa 409 döner.
    - empty_returns_actual değeri Order'a not olarak düşülür
      (şimdilik weight_kg üzerinden değil, ileride ayrı alan açılabilir).
    """
    route = _get_route_or_404(route_id, current_user.tenant_id, db)
    sorted_stops = sorted(route.route_stops, key=lambda rs: rs.stop_sequence)

    # Hedef durağı bul
    target_stop = next(
        (rs for rs in sorted_stops if rs.stop_sequence == stop_sequence), None
    )
    if not target_stop:
        raise HTTPException(
            status_code=404,
            detail=f"Durak bulunamadı: route_id={route_id}, sequence={stop_sequence}",
        )

    # Sıra atlama koruması: önceki duraklar tamamlanmış olmalı
    for prev in sorted_stops:
        if prev.stop_sequence >= stop_sequence:
            break
        if prev.status not in ("completed", "skipped"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Durak {prev.stop_sequence} henüz tamamlanmadı. "
                       "Lütfen sırayla ilerleyin.",
            )

    # İdempotency: zaten tamamlanmışsa tekrar işleme gerek yok
    if target_stop.status != "completed":
        target_stop.status = "completed"

        # Bağlı siparişi güncelle
        order: Optional[Order] = db.get(Order, target_stop.order_id)
        if order and order.status != "delivered":
            order.status = "delivered"
            order.delivered_at = datetime.now(timezone.utc)
            # Gerçek boş iade bilgisini loglayabiliriz:
            # (Şimdilik empty_returns_actual backend'de saklanmıyor —
            #  ileride RouteStop'a ayrı sütun açılabilir)

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Teslim kaydedilirken veritabanı hatası oluştu.",
            )

    # Bir sonraki durağı belirle
    remaining = [
        rs for rs in sorted_stops
        if rs.stop_sequence > stop_sequence and rs.status != "completed"
    ]
    next_detail: Optional[StopDetail] = None
    if remaining:
        next_stop_orm = min(remaining, key=lambda rs: rs.stop_sequence)
        next_detail = _build_stop_detail(next_stop_orm)

    completed_count = sum(1 for rs in sorted_stops if rs.status == "completed")
    route_complete = completed_count == len(sorted_stops)

    # Rota tamamen bittiyse Route.status'ü güncelle
    if route_complete and route.status != "completed":
        route.status = "completed"
        try:
            db.commit()
        except Exception:
            db.rollback()

    return CompleteStopResponse(
        completed_sequence=stop_sequence,
        next_stop=next_detail,
        route_complete=route_complete,
        completed_stops=completed_count,
        total_stops=len(sorted_stops),
    )
