from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.config import get_settings
from app.opensearch.client import OpenSearchReadinessClient
from app.opensearch.query import OpenSearchQueryClient
from app.repositories.incidents import OpenSearchIncidentRepository


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.opensearch = OpenSearchReadinessClient(settings)
    app.state.query_client = OpenSearchQueryClient(settings)
    app.state.incident_repository = OpenSearchIncidentRepository(app.state.query_client, settings)
    try:
        yield
    finally:
        await app.state.opensearch.close()
        await app.state.query_client.close()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="AIOps API", version=settings.build_version, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
    )
    application.include_router(health_router)
    application.include_router(incidents_router)
    return application


app = create_app()
