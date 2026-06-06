from fastapi import APIRouter

from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.customers import router as customers_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.delivery import router as delivery_router
from app.api.v1.endpoints.optimization import router as optimization_router
from app.api.v1.endpoints.vehicles import router as vehicles_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(admin_router)
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(customers_router)
api_router.include_router(dashboard_router)
api_router.include_router(delivery_router)
api_router.include_router(optimization_router)
api_router.include_router(vehicles_router)
