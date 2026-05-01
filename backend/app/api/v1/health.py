from fastapi import APIRouter, Request

from app.core.responses import success_response

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    return success_response({"status": "ok"}, request)
