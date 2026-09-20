from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.incidents import router as incident_router
from app.incidents.engine import IncidentEngine, IneligibleAnomaly, incident_id_for
from app.incidents.evidence import (
    EvidenceCandidate,
    anomaly_candidate,
    bucket_candidate,
    build_bundle,
)
from app.incidents.policy import capture_baseline, evaluate_recovery, severity_for
from app.models.detection import (
    NormalizedAnomaly,
    ServiceKey,
    ServiceMetricBucket,
    TimeRange,
    deterministic_id,
)
from app.models.incidents import DependencySnapshot, QueryLocator
from app.models.telemetry import DependencyEdge, ServiceReference, SourceDocument

NOW = datetime(2026, 9, 20, 12, 45, tzinfo=UTC)
SERVICE = ServiceKey(
    service_id=deterministic_id("svc", ["demo-shop", "development", "payment-service"]),
    namespace="demo-shop",
    environment="development",
    name="payment-service",
)
INVENTORY = ServiceKey(
    service_id=deterministic_id("svc", ["demo-shop", "development", "inventory-service"]),
    namespace="demo-shop",
    environment="development",
    name="inventory-service",
)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def metric(
    minute: datetime,
    *,
    errors: int = 0,
    latency: float = 20,
    service: ServiceKey = SERVICE,
) -> ServiceMetricBucket:
    end = minute + timedelta(minutes=1)
    bucket_id = deterministic_id(
        "bucket", [service.service_id, str(int(minute.timestamp() * 1_000_000_000)), "1.0.0"]
    )
    return ServiceMetricBucket(
        schema_version="1.0.0",
        bucket_id=bucket_id,
        service=service,
        window=TimeRange(start=stamp(minute), end=stamp(end)),
        bucket_time=stamp(minute),
        request_count=100,
        error_count=errors,
        error_rate=errors / 100,
        latency_mean_ms=latency / 2,
        latency_p95_ms=latency,
        source_count=100,
        invalid_span_count=0,
        late_span_count=0,
        quality_status="complete",
        quality_reasons=[],
        eligible_for_detection=True,
        source_kind="server_spans",
        aggregation_version="1.0.0",
        sampling_fraction=1.0,
        computed_at=stamp(end + timedelta(seconds=90)),
        finalized_at=stamp(end + timedelta(seconds=90)),
        source_visible_through=stamp(end + timedelta(seconds=90)),
    )


def anomaly(
    bucket: ServiceMetricBucket,
    *,
    source_id: str = "fixture-1",
    feature: str = "latency_p95_ms",
    status: str = "anomalous",
) -> NormalizedAnomaly:
    source = SourceDocument(index="phase6-development-fixture", document_id=source_id)
    return NormalizedAnomaly(
        schema_version="1.0.0",
        anomaly_id=deterministic_id("anomaly", [source.index, source.document_id]),
        detector_id="phase6-fixture-detector",
        detector_name="phase6-development-fixture",
        detector_config_version="1.0.0",
        service=bucket.service,
        feature=feature,
        feature_value=(bucket.latency_p95_ms if feature == "latency_p95_ms" else bucket.error_rate),
        input_bucket_id=bucket.bucket_id,
        detector_window=bucket.window,
        affected_window=bucket.window,
        execution_started_at=stamp(NOW - timedelta(seconds=2)),
        execution_ended_at=stamp(NOW - timedelta(seconds=1)),
        anomaly_grade=0.8 if status == "anomalous" else 0,
        detector_confidence=0.9,
        result_status=status,
        error_reason=None,
        source=source,
        observed_at=stamp(NOW),
    )


class MemoryRepository:
    def __init__(self, buckets: list[ServiceMetricBucket]) -> None:
        self.buckets = {item.bucket_id: item for item in buckets}
        self.incidents = {}
        self.anomalies = {}
        self.items = {}
        self.bundles = {}

    async def get_bucket(self, bucket_id):
        return self.buckets.get(bucket_id)

    async def baseline_buckets(self, service_id, before, limit=30):
        return [
            item
            for item in sorted(self.buckets.values(), key=lambda value: value.window.start)
            if item.service.service_id == service_id and item.window.end <= before
        ][-limit:]

    async def recent_buckets(self, service_id, start, limit=5):
        return [
            item
            for item in sorted(
                self.buckets.values(), key=lambda value: value.window.start, reverse=True
            )
            if item.service.service_id == service_id and item.window.start >= start
        ][:limit]

    async def get_incident(self, incident_id):
        return self.incidents.get(incident_id)

    async def get_active_incident(self, service_id, feature):
        return next(
            (
                item
                for item in self.incidents.values()
                if item.primary_service.service_id == service_id
                and item.feature == feature
                and item.state in ("open", "recovering")
            ),
            None,
        )

    async def related_candidates(self, incident):
        return list(self.incidents.values())

    async def save_incident(self, incident):
        self.incidents[incident.incident_id] = incident

    async def save_anomaly(self, item):
        self.anomalies[item.anomaly_id] = item

    async def save_evidence(self, items, bundle):
        self.items.update({item.evidence_id: item for item in items})
        self.bundles[bundle.bundle_id] = bundle

    async def list_incidents(self, **kwargs):
        return list(self.incidents.values())

    async def get_bundle(self, bundle_id):
        return self.bundles.get(bundle_id)

    async def get_bundle_version(self, incident_id, version):
        return next(
            (
                item
                for item in self.bundles.values()
                if item.incident_id == incident_id and item.version == version
            ),
            None,
        )

    async def get_evidence_items(self, evidence_ids):
        return [self.items[item_id] for item_id in evidence_ids if item_id in self.items]


def setup_data():
    trigger_minute = NOW - timedelta(minutes=2)
    baseline = [metric(trigger_minute - timedelta(minutes=index)) for index in range(10, 0, -1)]
    trigger = metric(trigger_minute, latency=100)
    return baseline, trigger, MemoryRepository([*baseline, trigger])


@pytest.mark.asyncio
async def test_anomaly_opens_deterministic_incident_with_baseline_and_evidence():
    baseline, trigger, repository = setup_data()
    event = anomaly(trigger)
    engine = IncidentEngine(repository, clock=lambda: NOW, allow_development_fixtures=True)
    incident = await engine.process(event)
    assert incident.incident_id == incident_id_for(event)
    assert incident.recovery_baseline is not None
    assert incident.recovery_baseline.bucket_ids == [item.bucket_id for item in baseline]
    assert incident.evidence_status == "ready"
    assert incident.fixture_source is True
    bundle = repository.bundles[incident.latest_evidence_bundle_id]
    assert len(bundle.evidence_ids) == 12
    assert repository.anomalies[event.anomaly_id].processing.processing_state == "processed"


@pytest.mark.asyncio
async def test_repeated_anomaly_updates_same_incident_and_replay_is_idempotent():
    _, trigger, repository = setup_data()
    engine = IncidentEngine(repository, clock=lambda: NOW, allow_development_fixtures=True)
    first = await engine.process(anomaly(trigger))
    second = await engine.process(anomaly(trigger, source_id="fixture-2"))
    bundle_count = len(repository.bundles)
    replay = await engine.process(anomaly(trigger, source_id="fixture-2"))
    assert first.incident_id == second.incident_id == replay.incident_id
    assert second.anomaly_count == 2
    assert len(repository.incidents) == 1
    assert len(repository.bundles) == bundle_count


@pytest.mark.asyncio
async def test_independent_feature_creates_separate_related_incident():
    _, trigger, repository = setup_data()
    engine = IncidentEngine(repository, clock=lambda: NOW, allow_development_fixtures=True)
    latency = await engine.process(anomaly(trigger))
    errors = await engine.process(anomaly(trigger, source_id="fixture-error", feature="error_rate"))
    assert latency.incident_id != errors.incident_id
    assert errors.related_incidents[0].incident_id == latency.incident_id
    assert (
        repository.incidents[latency.incident_id].related_incidents[0].incident_id
        == errors.incident_id
    )


@pytest.mark.asyncio
async def test_cross_service_incidents_link_only_with_dependency_evidence():
    baseline, trigger, repository = setup_data()
    inventory_baseline = [
        metric(
            datetime.fromisoformat(item.window.start.replace("Z", "+00:00")),
            service=INVENTORY,
        )
        for item in baseline
    ]
    inventory_trigger = metric(
        datetime.fromisoformat(trigger.window.start.replace("Z", "+00:00")),
        latency=100,
        service=INVENTORY,
    )
    repository.buckets.update(
        {item.bucket_id: item for item in [*inventory_baseline, inventory_trigger]}
    )
    edge = DependencyEdge(
        edge_id=deterministic_id("edge", ["payment", "inventory", trigger.window.start]),
        source_service=ServiceReference(
            namespace="demo-shop", environment="development", name="payment-service"
        ),
        target_service=ServiceReference(
            namespace="demo-shop", environment="development", name="inventory-service"
        ),
        window_start=trigger.window.start,
        window_end=trigger.window.end,
        observed_trace_count=1,
        sample_trace_ids=["a" * 32],
        observed_at=stamp(NOW),
        source_kind="trace_reconstruction",
    )

    async def provider(incident, event):
        return [
            EvidenceCandidate(
                evidence_type="dependency_edge",
                source=QueryLocator(
                    query_id=deterministic_id("query", [edge.edge_id]),
                    index_alias="otel-v1-apm-span",
                ),
                service=incident.primary_service,
                window=event.affected_window,
                summary="Observed payment to inventory dependency",
                snapshot=DependencySnapshot(edge=edge),
                template_id="dependencies-by-service",
                index_alias="otel-v1-apm-span",
            )
        ]

    engine = IncidentEngine(
        repository,
        clock=lambda: NOW,
        evidence_provider=provider,
        allow_development_fixtures=True,
    )
    payment = await engine.process(anomaly(trigger))
    inventory = await engine.process(anomaly(inventory_trigger, source_id="fixture-inventory"))
    assert inventory.related_incidents[0].incident_id == payment.incident_id
    assert inventory.related_incidents[0].reason == "dependency_and_overlap"


def test_evidence_truncation_is_recorded_and_ids_are_stable():
    _, trigger, _ = setup_data()
    event = anomaly(trigger)
    candidates = [anomaly_candidate(event), bucket_candidate(trigger), bucket_candidate(trigger)]
    items, bundle = build_bundle(
        incident_id_for(event),
        1,
        event.affected_window,
        candidates,
        now=NOW,
        max_items=2,
    )
    again, _ = build_bundle(
        incident_id_for(event), 1, event.affected_window, candidates, now=NOW, max_items=2
    )
    assert bundle.quality_reasons == ["truncated"]
    assert [item.evidence_id for item in items] == [item.evidence_id for item in again]


def test_severity_policy_is_deterministic_and_not_grade_based():
    baseline, trigger, _ = setup_data()
    captured = capture_baseline(baseline, captured_at=stamp(NOW))
    high = severity_for([trigger], captured)
    critical = severity_for([metric(NOW - timedelta(minutes=1), errors=20)], captured)
    assert high.severity == "high"
    assert critical.severity == "critical"
    assert high == severity_for([trigger], captured)


def test_stale_telemetry_prevents_recovery():
    baseline, trigger, repository = setup_data()
    base = capture_baseline(baseline, captured_at=stamp(NOW))
    assert base is not None
    event = anomaly(trigger)
    from app.models.incidents import Incident

    current = Incident(
        incident_id=incident_id_for(event),
        primary_service=SERVICE,
        affected_services=[SERVICE],
        feature="latency_p95_ms",
        state="open",
        severity="high",
        peak_severity="high",
        severity_reason="test",
        severity_bucket_ids=[trigger.bucket_id],
        opened_by_anomaly_id=event.anomaly_id,
        anomaly_count=1,
        recent_anomaly_ids=[event.anomaly_id],
        related_incidents=[],
        first_affected_at=trigger.window.start,
        last_affected_at=trigger.window.end,
        detected_at=stamp(NOW),
        updated_at=stamp(NOW),
        recovery_baseline=base,
    )
    healthy = metric(NOW - timedelta(minutes=1))
    decision = evaluate_recovery(
        current,
        healthy,
        both_detector_grades_zero=True,
        raw_fresh_at=NOW - timedelta(minutes=5),
        now=NOW,
    )
    assert decision.streak == 0
    assert decision.state == "open"


@pytest.mark.asyncio
async def test_three_then_five_healthy_windows_recover_and_resolve_then_recur():
    _, trigger, repository = setup_data()
    times = iter(NOW + timedelta(minutes=index) for index in range(10))
    engine = IncidentEngine(repository, clock=lambda: next(times), allow_development_fixtures=True)
    incident = await engine.process(anomaly(trigger))
    trigger_start = datetime.fromisoformat(trigger.window.start.replace("Z", "+00:00"))
    for index in range(1, 6):
        current_now = NOW + timedelta(minutes=index)
        healthy = metric(trigger_start + timedelta(minutes=index))
        repository.buckets[healthy.bucket_id] = healthy
        engine._clock = lambda value=current_now: value
        incident = await engine.apply_recovery(
            incident.incident_id,
            healthy,
            both_detector_grades_zero=True,
            raw_fresh_at=current_now,
        )
        if index == 3:
            assert incident.state == "recovering"
    assert incident.state == "resolved"
    reopened = incident.model_copy(update={"state": "recovering", "healthy_bucket_streak": 3})
    repository.incidents[incident.incident_id] = reopened
    unhealthy = metric(NOW + timedelta(minutes=6), errors=20)
    engine._clock = lambda: NOW + timedelta(minutes=7)
    result = await engine.apply_recovery(
        incident.incident_id,
        unhealthy,
        both_detector_grades_zero=False,
        raw_fresh_at=NOW + timedelta(minutes=7),
    )
    assert result.state == "open"
    assert result.healthy_bucket_streak == 0


@pytest.mark.asyncio
async def test_ineligible_and_malformed_anomalies_fail_safely():
    _, trigger, repository = setup_data()
    engine = IncidentEngine(repository, clock=lambda: NOW, allow_development_fixtures=True)
    with pytest.raises(IneligibleAnomaly):
        await engine.process(anomaly(trigger, status="normal"))
    malformed = anomaly(trigger).model_dump()
    malformed["service"]["service_id"] = "bad"
    with pytest.raises(ValidationError):
        NormalizedAnomaly.model_validate(malformed)
    assert repository.incidents == {}


@pytest.mark.asyncio
async def test_incident_api_lists_detail_and_evidence_without_storage_exposure():
    _, trigger, repository = setup_data()
    engine = IncidentEngine(repository, clock=lambda: NOW, allow_development_fixtures=True)
    incident = await engine.process(anomaly(trigger))
    app = FastAPI()
    app.state.incident_repository = repository
    app.include_router(incident_router)
    with TestClient(app) as client:
        listing = client.get("/api/v1/incidents")
        detail = client.get(f"/api/v1/incidents/{incident.incident_id}")
        evidence = client.get(f"/api/v1/incidents/{incident.incident_id}/evidence")
    assert listing.status_code == detail.status_code == evidence.status_code == 200
    assert listing.json()["result"]["items"][0]["fixture_source"] is True
    assert detail.json()["result"]["incident"]["incident_id"] == incident.incident_id
    assert evidence.json()["result"]["bundle"]["evidence_ids"]
    assert "opensearch" not in detail.text.lower()
