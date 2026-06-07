import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from app.core.deps import get_current_user, get_db
from sqlalchemy.orm import Session
from fastapi import Depends
from fastapi import Request
import logging
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.api.v1.router import api_router

# Veritabanı tablolarını oluştur (ilk çalıştırmada) ve Admin hesabını seed et
# NOT: Üretim ortamında (Render vb.) "Zero-downtime deploy" sırasında race condition'ları
# önlemek için `init_db()` ve `Base.metadata.create_all()` buraya eklenmemelidir.
# Bunun yerine veritabanı migrasyonları Alembic gibi araçlarla deploy adımında bir kez çalıştırılmalıdır.

app = FastAPI(
    title="Akıllı Dağıtım & Rota Optimizasyonu API",
    description="Smart Distribution & Route Optimization Backend",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("smart_distribution")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Sistem Hatası: {request.url} - {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Beklenmeyen bir sistem hatası oluştu."}
    )

app.include_router(api_router)

app.mount("/static", StaticFiles(directory="static", html=True), name="static")



@app.get("/admin-panel")
def admin_panel(request: Request, db: Session = Depends(get_db)):
    cookie_token = request.cookies.get("access_token")
    if not cookie_token:
        return RedirectResponse(url="/")
    try:
        token = cookie_token.split(" ")[1] if cookie_token.startswith("Bearer ") else cookie_token
        user = get_current_user(request, db, token)
        if user.role != "super_admin":
            return RedirectResponse(url="/")
        return FileResponse("protected/admin.html")
    except Exception:
        return RedirectResponse(url="/")

@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "Akıllı Dağıtım & Rota Optimizasyonu API",
    }
