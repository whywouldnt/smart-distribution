import asyncio
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.core.security import get_password_hash
from app.models.tenant import Tenant, User
from app.models.customer import Customer
from app.models.vehicle import Vehicle
from app.models.order import Order

def init_db():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if tenant exists
        tenant = db.query(Tenant).filter(Tenant.slug == "demo").first()
        if not tenant:
            print("Creating Demo Tenant...")
            tenant = Tenant(
                name="Demo Su Dağıtım",
                slug="demo",
                contact_email="iletisim@demosu.com",
                is_active=True
            )
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
            
        # Check if user exists
        user = db.query(User).filter(User.email == "admin@smartdistribution.com").first()
        if not user:
            print("Creating Admin User...")
            user = User(
                tenant_id=tenant.id,
                email="admin@smartdistribution.com",
                hashed_password=get_password_hash("admin123"),
                full_name="Sistem Yöneticisi",
                role="company_admin"
            )
            db.add(user)
            db.commit()
            
        print("Database initialization completed successfully.")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
