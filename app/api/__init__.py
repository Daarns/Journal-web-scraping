from fastapi import APIRouter
from .search_routes import router as search_router
from .ai_routes import router as ai_router
from .activity_routes import router as activity_router

api_router = APIRouter()

api_router.include_router(search_router, prefix="/search", tags=["search"])
api_router.include_router(ai_router, prefix="/ai", tags=["ai"])
api_router.include_router(activity_router, prefix="/activity", tags=["activity"])