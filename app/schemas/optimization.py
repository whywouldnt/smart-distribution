from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ------------------------------------------------------------------
#  RouteStop Schema
# ------------------------------------------------------------------
class RouteStopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    stop_sequence: int
    status: str
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    weight_kg: Optional[float] = None
    bottle_count: Optional[int] = None
    empty_returns_expected: Optional[int] = None


# ------------------------------------------------------------------
#  Route Schema
# ------------------------------------------------------------------
class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int
    name: Optional[str] = None
    total_distance_km: Optional[float] = None
    total_duration_min: Optional[int] = None
    status: str
    route_geometry: Optional[str] = None
    created_at: Optional[datetime] = None
    optimized_at: Optional[datetime] = None
    stops: list[RouteStopOut] = []


# ------------------------------------------------------------------
#  Optimization Summary
# ------------------------------------------------------------------
class OptimizationSummary(BaseModel):
    total_vehicles_used: int
    total_orders_assigned: int
    total_distance_km: float
    total_duration_min: int


# ------------------------------------------------------------------
#  POST /optimize/run  Response
# ------------------------------------------------------------------
class OptimizationResponse(BaseModel):
    routes: list[RouteOut]
    unassigned_order_ids: list[int]
    summary: OptimizationSummary
