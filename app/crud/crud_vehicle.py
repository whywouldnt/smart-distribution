from sqlalchemy.orm import Session
from app.models.vehicle import Vehicle

def get_vehicle_by_plate(db: Session, tenant_id: int, plate: str) -> Vehicle | None:
    """Belirtilen firmaya ait ve plakası eşleşen aracı getirir."""
    return db.query(Vehicle).filter(
        Vehicle.tenant_id == tenant_id, 
        Vehicle.plate == plate
    ).first()

def create_vehicle(
    db: Session, 
    tenant_id: int, 
    plate: str, 
    capacity_kg: float, 
    type: str, 
    status: str, 
    volume_m3: float
) -> Vehicle:
    """Sisteme yeni bir araç ekler."""
    vehicle = Vehicle(
        tenant_id=tenant_id,
        plate=plate,
        capacity_kg=capacity_kg,
        type=type,
        status=status,
        volume_m3=volume_m3,
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle
