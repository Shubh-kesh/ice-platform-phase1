from fastapi import APIRouter

from app.api.v1 import auth, users, projects, audit, tasks, site_logs, inventory, finance

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(audit.router)
api_router.include_router(tasks.router)
api_router.include_router(site_logs.router)
api_router.include_router(inventory.router)
api_router.include_router(finance.router)
