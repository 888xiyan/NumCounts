from fastapi import APIRouter

from app.api.v1.achievements import router as achievements_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.formal_calculations import result_router as formal_result_router
from app.api.v1.formal_calculations import router as formal_calculation_router
from app.api.v1.functions import router as functions_router
from app.api.v1.health import router as health_router
from app.api.v1.links import router as links_router
from app.api.v1.member import router as member_router
from app.api.v1.monitoring import router as monitoring_router
from app.api.v1.plugins import router as plugins_router
from app.api.v1.records import router as records_router
from app.api.v1.special_performance import router as special_performance_router
from app.api.v1.workflows import router as workflows_router
from app.api.v1.workflows import run_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(audit_router)
api_router.include_router(functions_router)
api_router.include_router(formal_calculation_router)
api_router.include_router(formal_result_router)
api_router.include_router(achievements_router)
api_router.include_router(health_router)
api_router.include_router(links_router)
api_router.include_router(monitoring_router)
api_router.include_router(member_router)
api_router.include_router(records_router)
api_router.include_router(special_performance_router)
api_router.include_router(plugins_router)
api_router.include_router(workflows_router)
api_router.include_router(run_router)
