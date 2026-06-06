import random
from app.db.base import Base
from app.db.session import engine
from app.core.database import SessionLocal
from app.models.customer import Customer
from app.models.vehicle import Vehicle
from app.models.order import Order

def seed_db():
    db = SessionLocal()
    try:
        # 0. Tablolar yoksa oluştur (seed çalıştırılmadan önce DB silinmiş olabilir)
        Base.metadata.create_all(bind=engine)

        # 1. Önceki test verilerini temizle
        db.query(Order).delete()
        db.query(Vehicle).delete()
        db.query(Customer).delete()
        db.commit()

        # 2. Araçları Oluştur (2 Panelvan, 1 Motosiklet)
        vehicles = [
            Vehicle(plate="15 ABC 01", capacity_kg=500.0, volume_m3=5.0, type="van", status="available", driver_name="Bucak Dağıtım 1"),
            Vehicle(plate="15 ABC 02", capacity_kg=500.0, volume_m3=5.0, type="van", status="available", driver_name="Bucak Dağıtım 2"),
            Vehicle(plate="07 XYZ 99", capacity_kg=50.0, volume_m3=1.0, type="motorcycle", status="available", driver_name="Antalya Ekspres")
        ]
        db.add_all(vehicles)
        db.commit()

        # 3. Müşterileri Oluştur (Antalya ve Bucak Koordinatları)
        # Bucak Merkezi: ~37.458, 30.288
        # Antalya Merkezi: ~36.884, 30.705
        customers = []
        for i in range(12):
            is_bucak = i % 2 == 0
            base_lat = 37.458 if is_bucak else 36.884
            base_lng = 30.288 if is_bucak else 30.705
            
            c = Customer(
                name=f"Fırın / Bayi {i+1}",
                email=f"bayi{i+1}@test.com",
                phone="05550001122",
                address="Bucak Merkez" if is_bucak else "Antalya Merkez",
                lat=base_lat + random.uniform(-0.02, 0.02),
                lng=base_lng + random.uniform(-0.02, 0.02)
            )
            customers.append(c)
        db.add_all(customers)
        db.commit()

        # 4. Siparişleri Oluştur (Damacana bazlı)
        orders = []
        BOTTLE_WEIGHT_KG = 19
        for idx, c in enumerate(customers):
            bottle_count = random.randint(1, 5)
            empty_returns = random.choice([bottle_count, bottle_count - 1, bottle_count])
            o = Order(
                customer_id=c.id,
                status="pending",
                bottle_count=bottle_count,
                empty_returns_expected=empty_returns,
                weight_kg=round(bottle_count * BOTTLE_WEIGHT_KG, 1),
                volume_m3=round(bottle_count * 0.025, 3),
                priority=1,
                delivery_lat=c.lat,
                delivery_lng=c.lng,
                delivery_address=c.address
            )
            orders.append(o)
        db.add_all(orders)
        db.commit()

        print("✅ Veritabanı temizlendi ve gerçekçi damacana test verileri yüklendi!")

    except Exception as e:
        print(f"HATA: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()