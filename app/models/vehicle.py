from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import String, Float, DateTime, func, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.route import Route
    from app.models.tenant import Tenant


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    plate: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    capacity_kg: Mapped[float] = mapped_column(Float, nullable=False)
    volume_m3: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("type IN ('van', 'truck', 'motorcycle', 'bicycle')"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("status IN ('available', 'in_use', 'maintenance')"),
        default="available",
    )
    driver_name: Mapped[str | None] = mapped_column(String(255))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    orders: Mapped[List["Order"]] = relationship(
        "Order", back_populates="vehicle"
    )
    routes: Mapped[List["Route"]] = relationship(
        "Route", back_populates="vehicle"
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")

    def __repr__(self) -> str:
        return f"<Vehicle(id={self.id}, plate={self.plate!r})>"
