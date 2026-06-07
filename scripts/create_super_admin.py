import os
import sys

# app dizinini Python yoluna ekle
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.tenant import User
from app.core.security import get_password_hash

def create_super_admin():
    db = SessionLocal()
    email = "super@patron.com"
    existing = db.query(User).filter(User.email == email).first()
    
    if not existing:
        user = User(
            tenant_id=None,  # Super Admin'in tenant_id'si None'dır! Sistemi üstten görür.
            email=email,
            hashed_password=get_password_hash("Patron123!"),
            role="super_admin",
            full_name="Kurucu Patron",
            is_active=True
        )
        db.add(user)
        db.commit()
        print(f"Süper Admin başarıyla oluşturuldu!\nE-Posta: {email}\nŞifre: Patron123!")
    else:
        print("Süper Admin hesabı zaten mevcut.")
    
    db.close()

if __name__ == "__main__":
    create_super_admin()
