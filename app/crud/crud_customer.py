import random
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.order import Order

BOTTLE_WEIGHT_KG = 19

def create_customer_with_order(
    db: Session, 
    tenant_id: int, 
    name: str, 
    address: str, 
    lat: float, 
    lng: float
) -> Customer:
    """
    Belirtilen tenant için müşteri oluşturur ve otomatik olarak başlangıç siparişi tanımlar.
    Veritabanı işlemleri (transaction) burada yönetilir.
    """
    try:
        customer = Customer(
            tenant_id=tenant_id,
            name=name,
            address=address,
            lat=lat,
            lng=lng,
        )
        db.add(customer)
        db.flush()  # Müşteri ID'sini Order oluşturmak için hemen al

        bottle_count = random.randint(1, 3)
        empty_returns = random.randint(0, bottle_count)
        
        order = Order(
            tenant_id=tenant_id,
            customer_id=customer.id,
            status="pending",
            bottle_count=bottle_count,
            empty_returns_expected=empty_returns,
            weight_kg=round(bottle_count * BOTTLE_WEIGHT_KG, 1),
            volume_m3=round(bottle_count * 0.025, 3),
            delivery_lat=lat,
            delivery_lng=lng,
            delivery_address=address,
        )
        db.add(order)
        db.commit()
        db.refresh(customer)
        
        return customer
    except Exception as e:
        db.rollback()
        raise e
