from aiogram import Router

from .common import router as common_router
from .wizard import router as wizard_router
from .dashboard import router as dashboard_router
from .management import router as management_router
user_router = Router()

user_router.include_router(common_router)
user_router.include_router(wizard_router)
user_router.include_router(dashboard_router)
user_router.include_router(management_router)
