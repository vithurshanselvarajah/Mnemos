from fastapi import APIRouter

from app.api import system

router = APIRouter()
router.include_router(system.router)
