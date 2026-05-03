from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.body_metrics import router as body_metrics_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.daily_archives import router as daily_archives_router
from app.api.v1.dev import router as dev_router
from app.api.v1.health import router as health_router
from app.api.v1.meals import router as meals_router
from app.api.v1.pending_actions import router as pending_actions_router
from app.api.v1.profile import router as profile_router
from app.api.v1.summaries import router as summaries_router
from app.api.v1.uploads import router as uploads_router

api_router = APIRouter()
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(health_router, tags=["health"])
api_router.include_router(profile_router, tags=["profile"])
api_router.include_router(meals_router, tags=["meals"])
api_router.include_router(body_metrics_router, tags=["body-metrics"])
api_router.include_router(conversations_router, tags=["conversations"])
api_router.include_router(pending_actions_router, tags=["agent"])
api_router.include_router(uploads_router, tags=["uploads"])
api_router.include_router(daily_archives_router, tags=["daily-archives"])
api_router.include_router(summaries_router, tags=["summaries"])
api_router.include_router(dev_router, tags=["dev"])
