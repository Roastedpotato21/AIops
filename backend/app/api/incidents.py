from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.models.detection import deterministic_id
from app.models.incidents import (
    ApiResponse,
    Coverage,
    EvidenceResponse,
    Freshness,
    IncidentDetail,
    IncidentSummary,
    Page,
    TimelineEntry,
)

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _envelope[T](result: T) -> ApiResponse[T]:
    now = _utc(datetime.now(UTC))
    return ApiResponse(
        result=result,
        request_id=str(uuid4()),
        freshness=Freshness(
            generated_at=now,
            latest_source_at=None,
            age_seconds=None,
            state="not_applicable",
        ),
        coverage=Coverage(status="complete", reasons=[]),
    )


def _timeline(incident) -> list[TimelineEntry]:
    entries = [
        TimelineEntry(
            entry_id=deterministic_id("timeline", [incident.incident_id, "detected"]),
            occurred_at=incident.detected_at,
            kind="detected",
            summary=(
                "Development fixture incident opened"
                if incident.fixture_source
                else "Eligible detector anomaly opened incident"
            ),
            evidence_ids=[],
        )
    ]
    if incident.latest_evidence_bundle_id:
        entries.append(
            TimelineEntry(
                entry_id=deterministic_id(
                    "timeline", [incident.incident_id, "evidence", incident.evidence_version]
                ),
                occurred_at=incident.updated_at,
                kind="evidence",
                summary=f"Evidence bundle revision {incident.evidence_version} committed",
                evidence_ids=[],
            )
        )
    if incident.recovering_since:
        entries.append(
            TimelineEntry(
                entry_id=deterministic_id(
                    "timeline", [incident.incident_id, "recovering", incident.recovering_since]
                ),
                occurred_at=incident.recovering_since,
                kind="recovering",
                summary="Three consecutive healthy minutes observed",
                evidence_ids=[],
            )
        )
    if incident.resolved_at:
        entries.append(
            TimelineEntry(
                entry_id=deterministic_id(
                    "timeline", [incident.incident_id, "resolved", incident.resolved_at]
                ),
                occurred_at=incident.resolved_at,
                kind="resolved",
                summary="Five consecutive healthy minutes observed",
                evidence_ids=[],
            )
        )
    return sorted(entries, key=lambda item: (item.occurred_at, item.entry_id))


@router.get("")
async def list_incidents(
    request: Request,
    namespace: Annotated[str, Query(min_length=1, max_length=63)] = "demo-shop",
    environment: Annotated[str, Query(min_length=1, max_length=63)] = "development",
    state: Literal["open", "recovering", "resolved"] | None = None,
    severity: Literal["low", "medium", "high", "critical"] | None = None,
    service_id: Annotated[str | None, Query(pattern=r"^svc_[0-9a-f]{64}$")] = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> ApiResponse[Page[IncidentSummary]]:
    if cursor is not None:
        raise HTTPException(400, "invalid_cursor")
    stop = end or datetime.now(UTC)
    begin = start or stop - timedelta(hours=24)
    if (
        begin.tzinfo is None
        or stop.tzinfo is None
        or begin >= stop
        or stop - begin > timedelta(days=30)
    ):
        raise HTTPException(422, "invalid incident time range")
    items = await request.app.state.incident_repository.list_incidents(
        namespace=namespace,
        environment=environment,
        state=state,
        severity=severity,
        service_id=service_id,
        start=_utc(begin),
        end=_utc(stop),
        limit=limit + 1,
    )
    return _envelope(Page(items=items[:limit], next_cursor=None, has_more=len(items) > limit))


@router.get("/{incident_id}")
async def get_incident(
    request: Request,
    incident_id: Annotated[str, Path(pattern=r"^incident_[0-9a-f]{64}$")],
    timeline_limit: Annotated[int, Query(ge=1, le=50)] = 20,
    timeline_cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> ApiResponse[IncidentDetail]:
    if timeline_cursor is not None:
        raise HTTPException(400, "invalid_cursor")
    incident = await request.app.state.incident_repository.get_incident(incident_id)
    if incident is None:
        raise HTTPException(404, "not_found")
    bundle = (
        await request.app.state.incident_repository.get_bundle(incident.latest_evidence_bundle_id)
        if incident.latest_evidence_bundle_id
        else None
    )
    timeline = _timeline(incident)
    detail = IncidentDetail(
        incident=incident,
        evidence_bundle=bundle,
        timeline=Page(
            items=timeline[:timeline_limit],
            next_cursor=None,
            has_more=len(timeline) > timeline_limit,
        ),
        latest_investigation=None,
    )
    return _envelope(detail)


@router.get("/{incident_id}/evidence")
async def get_incident_evidence(
    request: Request,
    incident_id: Annotated[str, Path(pattern=r"^incident_[0-9a-f]{64}$")],
    bundle_version: Annotated[int | None, Query(ge=1)] = None,
    type: Literal[
        "anomaly_result", "metric_bucket", "log_record", "span", "trace", "dependency_edge"
    ]
    | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> ApiResponse[EvidenceResponse]:
    if cursor is not None:
        raise HTTPException(400, "invalid_cursor")
    incident = await request.app.state.incident_repository.get_incident(incident_id)
    if incident is None:
        raise HTTPException(404, "not_found")
    bundle = (
        await request.app.state.incident_repository.get_bundle_version(incident_id, bundle_version)
        if bundle_version is not None
        else (
            await request.app.state.incident_repository.get_bundle(
                incident.latest_evidence_bundle_id
            )
            if incident.latest_evidence_bundle_id
            else None
        )
    )
    if bundle is None:
        raise HTTPException(409, "evidence_not_ready")
    items = await request.app.state.incident_repository.get_evidence_items(bundle.evidence_ids)
    if type is not None:
        items = [item for item in items if item.evidence_type == type]
    response = EvidenceResponse(
        incident_id=incident_id,
        bundle=bundle,
        items=Page(items=items[:limit], next_cursor=None, has_more=len(items) > limit),
    )
    return _envelope(response)
