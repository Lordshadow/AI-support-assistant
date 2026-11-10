"""ASGI application for the authenticated staff dashboard API."""

from fastapi import FastAPI

from services.dashboard_api.auth import router as auth_router
from services.dashboard_api.conversations import router as conversations_router
from services.dashboard_api.escalations import router as escalations_router
from services.dashboard_api.knowledge import router as knowledge_router
from services.dashboard_api.refunds import legacy_router as legacy_refunds_router
from services.dashboard_api.refunds import integration_router as refund_integration_router
from services.dashboard_api.refunds import router as refunds_router
from services.dashboard_api.reports import router as reports_router
from services.dashboard_api.search import router as search_router
from services.dashboard_api.settings import router as settings_router
from services.dashboard_api.widget import router as widget_router


def create_dashboard_api() -> FastAPI:
    app = FastAPI(title="NovaRetail Staff API", docs_url=None, redoc_url=None)
    for router in (
        auth_router,
        conversations_router,
        escalations_router,
        knowledge_router,
        refunds_router,
        refund_integration_router,
        legacy_refunds_router,
        reports_router,
        search_router,
        settings_router,
        widget_router,
    ):
        app.include_router(router)
    return app
