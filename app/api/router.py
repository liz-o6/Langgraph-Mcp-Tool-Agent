from fastapi import APIRouter

from app.api.routes import chat, files, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(files.router)
