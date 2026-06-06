from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import Integer, String, Float, DateTime, ForeignKey, Text, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle
    from app.models.order import Order
    from app.models.route_stop import RouteStop
    from app.models.tenant import Tenant


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vehicles.id"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(255))
    total_distance_km: Mapped[float | None] = mapped_column(Float)
    total_duration_min: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint(
            "status IN ('planned', 'optimized', 'in_progress', 'completed')"
        ),
        default="planned",
    )
    route_geometry: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    optimized_at: Mapped[datetime | None] = mapped_column(DateTime)

    vehicle: Mapped["Vehicle"] = relationship(
        "Vehicle", back_populates="routes"
    )
    orders: Mapped[List["Order"]] = relationship(
        "Order", back_populates="route"
    )
    route_stops: Mapped[List["RouteStop"]] = relationship(
        "RouteStop", back_populates="route", order_by="RouteStop.stop_sequence"
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")

    def __repr__(self) -> str:
        return f"<Route(id={self.id}, name={self.name!r})>"
