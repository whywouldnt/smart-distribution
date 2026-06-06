import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.api.v1.router import api_router
from app.core.database import Base, engine

from init_db import init_db

# Veritabanı tablolarını oluştur (ilk çalıştırmada) ve Admin hesabını seed et
Base.metadata.create_all(bind=engine)
init_db()

app = FastAPI(
    title="Akıllı Dağıtım & Rota Optimizasyonu API",
    description="Smart Distribution & Route Optimization Backend",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

app.mount("/static", StaticFiles(directory="static", html=True), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "Akıllı Dağıtım & Rota Optimizasyonu API",
    }
