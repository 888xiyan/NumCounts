from fastapi import APIRouter

from app.api.v1.achievements import router as achievements_router
from app.api.v1.auth import router as auth_router
from app.api.v1.functions import router as functions_router
from app.api.v1.health import router as health_router
from app.api.v1.records import router as records_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(functions_router)
api_router.include_router(achievements_router)
api_router.include_router(health_router)
api_router.include_router(records_router)
