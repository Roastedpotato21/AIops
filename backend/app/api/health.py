from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from app.api.strict import StrictQueryRoute
from app.models.health import HealthResponse, ReadinessCheck, ReadyResponse

router = APIRouter(route_class=StrictQueryRoute)


def now() -> datetime:
    return datetime.now(UTC)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(version=request.app.state.settings.build_version, checked_at=now())


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request, response: Response) -> ReadyResponse:
    checked_at = now()
    checks = [
        ReadinessCheck(
            name="configuration", state="pass", reason_code=None, checked_at=checked_at
        )
    ]

    cluster = await request.app.state.opensearch.cluster()
    checks.append(
        ReadinessCheck(
            name="opensearch",
            state=cluster.state,
            reason_code=cluster.reason_code,
            checked_at=checked_at,
        )
    )
    if cluster.state == "pass":
        bootstrap = await request.app.state.opensearch.bootstrap()
    else:
        bootstrap = cluster
    checks.append(
        ReadinessCheck(
            name="bootstrap",
            state=bootstrap.state,
            reason_code=bootstrap.reason_code,
            checked_at=checked_at,
        )
    )
    ready_state = all(check.state == "pass" for check in checks)
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if ready_state else "not_ready", checked_at=checked_at, checks=checks
    )
