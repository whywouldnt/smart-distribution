from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, Time, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.route import Route
    from app.models.order import Order
    from app.models.tenant import Tenant


class RouteStop(Base):
    __tablename__ = "route_stops"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    route_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("routes.id"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id"), nullable=False
    )
    stop_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_arrival: Mapped[str | None] = mapped_column(Time)
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint(
            "status IN ('pending', 'arrived', 'completed', 'skipped')"
        ),
        default="pending",
    )

    route: Mapped["Route"] = relationship(
        "Route", back_populates="route_stops"
    )
    order: Mapped["Order"] = relationship(
        "Order", back_populates="route_stops"
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")

    __table_args__ = (
        UniqueConstraint("route_id", "stop_sequence", name="uq_route_stop_seq"),
    )

    def __repr__(self) -> str:
        return (
            f"<RouteStop(id={self.id}, route_id={self.route_id}, "
            f"stop_sequence={self.stop_sequence})>"
        )
