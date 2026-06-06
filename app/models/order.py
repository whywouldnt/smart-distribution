from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import (
    Integer, String, Float, DateTime, ForeignKey, CheckConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.vehicle import Vehicle
    from app.models.route import Route
    from app.models.route_stop import RouteStop
    from app.models.tenant import Tenant


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id"), nullable=False
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("vehicles.id")
    )
    route_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("routes.id")
    )
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint(
            "status IN ('pending', 'assigned', 'in_transit', 'delivered', 'cancelled')"
        ),
        default="pending",
    )
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    bottle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    empty_returns_expected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    volume_m3: Mapped[float] = mapped_column(Float, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    delivery_lat: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_lng: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_address: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)

    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="orders"
    )
    vehicle: Mapped["Vehicle | None"] = relationship(
        "Vehicle", back_populates="orders"
    )
    route: Mapped["Route | None"] = relationship(
        "Route", back_populates="orders"
    )
    route_stops: Mapped[List["RouteStop"]] = relationship(
        "RouteStop", back_populates="order"
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, status={self.status!r})>"
