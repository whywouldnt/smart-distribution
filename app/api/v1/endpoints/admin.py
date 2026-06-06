from typing import List, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_active_superuser
from app.core.security import get_password_hash
from app.models.tenant import Tenant, User

router = APIRouter(prefix="/admin", tags=["admin"])

class TenantCreate(BaseModel):
    name: str
    slug: str
    contact_email: str | None = None
    
class TenantResponse(BaseModel):
    id: int
    name: str
    slug: str
    is_active: bool
    subscription_ends_at: datetime | None
    contact_email: str | None
    
    model_config = {"from_attributes": True}

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: str = "company_admin"

@router.get("/tenants", response_model=List[TenantResponse])
def get_tenants(
    db: Session = Depends(get_db), 
    current_admin: User = Depends(get_current_active_superuser)
) -> Any:
    """List all tenants (Super Admin only)"""
    return db.query(Tenant).all()

@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant_in: TenantCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_active_superuser)
) -> Any:
    """Create a new tenant (Super Admin only)"""
    existing = db.query(Tenant).filter(Tenant.slug == tenant_in.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu slug zaten kullanımda.")
        
    tenant = Tenant(
        name=tenant_in.name,
        slug=tenant_in.slug,
        contact_email=tenant_in.contact_email
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant

@router.patch("/tenants/{tenant_id}/toggle", response_model=TenantResponse)
def toggle_tenant_active(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_active_superuser)
) -> Any:
    """Toggle tenant active status - KILL SWITCH (Super Admin only)"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Firma bulunamadı")
        
    tenant.is_active = not tenant.is_active
    db.commit()
    db.refresh(tenant)
    return tenant

@router.post("/tenants/{tenant_id}/users", status_code=status.HTTP_201_CREATED)
def create_tenant_user(
    tenant_id: int,
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_active_superuser)
) -> Any:
    """Create a user for a specific tenant (Super Admin only)"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Firma bulunamadı")
        
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Bu e-posta adresi zaten kullanımda.")
        
    user = User(
        tenant_id=tenant_id,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role
    )
    db.add(user)
    db.commit()
    return {"msg": "Kullanıcı başarıyla oluşturuldu", "user_id": user.id}
