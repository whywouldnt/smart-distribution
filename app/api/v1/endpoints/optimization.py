import traceback

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.deps import get_current_user, get_current_company_admin
from app.models.tenant import User
from app.schemas.optimization import (
    OptimizationResponse,
    RouteOut,
    RouteStopOut,
)
from app.services.route_optimizer import (
    fetch_available_vehicles,
    fetch_pending_orders,
    optimize_routes,
)

router = APIRouter(prefix="/optimize", tags=["optimization"])


@router.post("/run", response_model=OptimizationResponse)
async def run_optimization(
    db: AsyncSession = Depends(get_async_db),
    origin_lat: float | None = None,
    origin_lng: float | None = None,
    current_admin: User = Depends(get_current_company_admin)
):
    """
    Tüm aktif araçları ve bekleyen siparişleri alarak
    kapasite kısıtlı rota optimizasyonunu çalıştırır (Async).

    - Araç yoksa      → 400 Bad Request
    - Sipariş yoksa   → 400 Bad Request
    - Başarılıysa     → { routes, unassigned_order_ids, summary }

    Query Parametreleri:
    - origin_lat (float, optional): Şoförün anlık GPS enlemi
    - origin_lng (float, optional): Şoförün anlık GPS boylamı
    """
    # 1) Araçları kontrol et
    vehicles = await fetch_available_vehicles(db, current_admin.tenant_id)
    if not vehicles:
        raise HTTPException(
            status_code=400,
            detail="Aktif araç bulunamadı. Lütfen önce araç ekleyin "
                   "veya araç durumlarını 'available' yapın.",
        )

    # 2) Siparişleri kontrol et
    orders = await fetch_pending_orders(db, current_admin.tenant_id)
    if not orders:
        raise HTTPException(
            status_code=400,
            detail="Bugüne ait bekleyen sipariş bulunamadı. "
                   "Lütfen önce sipariş oluşturun.",
        )

    # 3) Optimizasyonu çalıştır (origin koordinatları varsa ilk araca ata)
    try:
        result = await optimize_routes(db, vehicles, orders, origin_lat, origin_lng)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Rota optimizasyonu sırasında beklenmeyen bir hata oluştu.",
        )

    # 4) Route ORM nesnelerini Pydantic schema'ya dönüştür
    routes_out: list[RouteOut] = []
    for route in result["routes"]:
        route_out = RouteOut.model_validate(route)

        # route_stops ilişkisindeki her bir stop'u schema'ya çevir
        route_out.stops = [
            RouteStopOut(
                order_id=rs.order_id,
                stop_sequence=rs.stop_sequence,
                status=rs.status,
                delivery_lat=rs.order.delivery_lat if rs.order else None,
                delivery_lng=rs.order.delivery_lng if rs.order else None,
                weight_kg=rs.order.weight_kg if rs.order else None,
                bottle_count=rs.order.bottle_count if rs.order else None,
                empty_returns_expected=rs.order.empty_returns_expected if rs.order else None,
            )
            for rs in route.route_stops
        ]
        routes_out.append(route_out)

    # 5) Yanıtı oluştur
    return OptimizationResponse(
        routes=routes_out,
        unassigned_order_ids=result["unassigned_order_ids"],
        summary=result["summary"],
    )
