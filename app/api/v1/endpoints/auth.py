from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.core.deps import get_current_user
from app.models.tenant import User

router = APIRouter()

@router.post("/login")
@limiter.limit("5/minute")
def login_access_token(
    request: Request, response: Response, db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests"""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="E-posta veya şifre hatalı")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Pasif kullanıcı")
    
    access_token = create_access_token(user.id)
    
    # Güvenli httpOnly Cookie ayarlama (XSS Koruması)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=3600 # 1 saat
    )
    
    return {
        "message": "Giriş başarılı",
        "role": user.role,
        "tenant_id": user.tenant_id
    }

@router.get("/me")
def read_users_me(current_user: User = Depends(get_current_user)) -> Any:
    """Get current user."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "full_name": current_user.full_name
    }
