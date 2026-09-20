from typing import Annotated

from fastapi import APIRouter, Body, Header, HTTPException, Path, Request, Response

from app.agent.scheduling import SchedulingConflict
from app.api.incidents import _envelope
from app.models.incidents import ApiResponse
from app.models.investigation import (
    InvestigationAccepted,
    InvestigationCreate,
    InvestigationView,
)
from app.repositories.telemetry import TelemetryRepositoryError

router = APIRouter(prefix="/api/v1", tags=["investigations"])


@router.post("/incidents/{incident_id}/investigate", status_code=202)
async def create_investigation(
    request: Request,
    response: Response,
    incident_id: Annotated[str, Path(pattern=r"^incident_[0-9a-f]{64}$")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    body: Annotated[InvestigationCreate | None, Body()] = None,
) -> ApiResponse[InvestigationAccepted]:
    try:
        job = await request.app.state.investigation_scheduler.schedule(
            incident_id,
            body or InvestigationCreate(),
            principal_id="local-api",
            idempotency_key=idempotency_key,
        )
    except SchedulingConflict as exc:
        status = {
            "not_found": 404,
            "evidence_not_ready": 409,
            "conflict": 409,
            "idempotency_conflict": 409,
            "invalid_argument": 422,
            "rate_limited": 429,
        }[exc.code]
        raise HTTPException(status, exc.code) from None
    except TelemetryRepositoryError:
        raise HTTPException(503, "investigation_store_unavailable") from None
    response.headers["Location"] = f"/api/v1/investigations/{job.investigation_id}"
    return _envelope(
        InvestigationAccepted(
            investigation_id=job.investigation_id,
            state=job.state,
            incident_id=job.incident_id,
            evidence_version=job.evidence_version,
            created_at=job.created_at,
        )
    )


@router.get("/investigations/{investigation_id}")
async def get_investigation(
    request: Request,
    investigation_id: Annotated[str, Path(pattern=r"^inv_[0-9a-f]{64}$")],
) -> ApiResponse[InvestigationView]:
    try:
        view = await request.app.state.investigation_scheduler.view(investigation_id)
    except TelemetryRepositoryError:
        raise HTTPException(503, "investigation_store_unavailable") from None
    if view is None:
        raise HTTPException(404, "not_found")
    return _envelope(view)
