from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models.route import Route
from app.models.route_stop import RouteStop
from app.models.order import Order


def get_today_routes(db: Session, tenant_id: int) -> list[Route]:
    """Bugün optimize edilmiş tüm araç rotalarını getirir."""
    today_start = datetime.combine(date.today(), datetime.min.time())
    return (
        db.query(Route)
        .options(
            joinedload(Route.route_stops),
            joinedload(Route.vehicle),
        )
        .filter(Route.tenant_id == tenant_id)
        .filter(Route.created_at >= today_start)
        .filter(Route.status.in_(["optimized", "in_progress"]))
        .order_by(Route.id)
        .all()
    )


def get_today_route_for_vehicle(db: Session, tenant_id: int, vehicle_id: Optional[int] = None) -> Optional[Route]:
    """Belirtilen (veya bugünkü ilk) araca ait detaylı rotayı getirir."""
    today_start = datetime.combine(date.today(), datetime.min.time())
    query = (
        db.query(Route)
        .options(
            joinedload(Route.route_stops)
            .joinedload(RouteStop.order)
            .joinedload(Order.customer),
            joinedload(Route.vehicle),
        )
        .filter(Route.tenant_id == tenant_id)
        .filter(Route.created_at >= today_start)
        .filter(Route.status.in_(["optimized", "in_progress"]))
    )

    if vehicle_id is not None:
        query = query.filter(Route.vehicle_id == vehicle_id)

    return query.order_by(Route.id).first()


def get_route_with_stops(db: Session, tenant_id: int, route_id: int) -> Optional[Route]:
    """Belirli bir rotayı tüm durak ve sipariş detaylarıyla getirir."""
    return (
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


def mark_stop_completed(db: Session, target_stop: RouteStop) -> None:
    """Bir durağı (ve ona bağlı siparişi) teslim edildi olarak işaretler."""
    target_stop.status = "completed"
    
    order: Optional[Order] = db.get(Order, target_stop.order_id)
    if order and order.status != "delivered":
        order.status = "delivered"
        order.delivered_at = datetime.now(timezone.utc)
        
    db.commit()


def mark_route_completed(db: Session, route: Route) -> None:
    """Bir rotanın tüm durakları tamamlandığında rotayı tamamlandı işaretler."""
    route.status = "completed"
    db.commit()
