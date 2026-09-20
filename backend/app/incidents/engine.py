from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from app.incidents.evidence import (
    EvidenceCandidate,
    anomaly_candidate,
    bucket_candidate,
    build_bundle,
)
from app.incidents.policy import (
    POLICY_VERSION,
    capture_baseline,
    evaluate_recovery,
    retain_peak,
    severity_for,
)
from app.models.detection import NormalizedAnomaly, ServiceMetricBucket, deterministic_id
from app.models.incidents import EvidenceBundle, EvidenceItem, Incident, RelatedIncident


class IncidentRepository(Protocol):
    async def get_bucket(self, bucket_id: str) -> ServiceMetricBucket | None: ...

    async def baseline_buckets(
        self, service_id: str, before: str, limit: int = 30
    ) -> list[ServiceMetricBucket]: ...

    async def recent_buckets(
        self, service_id: str, start: str, limit: int = 5
    ) -> list[ServiceMetricBucket]: ...

    async def get_incident(self, incident_id: str) -> Incident | None: ...

    async def get_active_incident(self, service_id: str, feature: str) -> Incident | None: ...

    async def related_candidates(self, incident: Incident) -> list[Incident]: ...

    async def save_incident(self, incident: Incident) -> None: ...

    async def save_anomaly(self, anomaly: NormalizedAnomaly) -> None: ...

    async def save_evidence(self, items: list[EvidenceItem], bundle: EvidenceBundle) -> None: ...


EvidenceProvider = Callable[[Incident, NormalizedAnomaly], Awaitable[list[EvidenceCandidate]]]


class IneligibleAnomaly(ValueError):
    pass


def incident_id_for(anomaly: NormalizedAnomaly) -> str:
    return deterministic_id(
        "incident",
        [anomaly.service.service_id, anomaly.feature, anomaly.anomaly_id, POLICY_VERSION],
    )


def _utc(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


class IncidentEngine:
    def __init__(
        self,
        repository: IncidentRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        evidence_provider: EvidenceProvider | None = None,
        allow_development_fixtures: bool = False,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._evidence_provider = evidence_provider
        self._allow_development_fixtures = allow_development_fixtures

    async def process(self, anomaly: NormalizedAnomaly) -> Incident:
        fixture = anomaly.source.index == "phase6-development-fixture"
        if fixture and not self._allow_development_fixtures:
            raise IneligibleAnomaly("development fixture is disabled")
        if (
            anomaly.result_status != "anomalous"
            or anomaly.anomaly_grade is None
            or anomaly.anomaly_grade <= 0
            or anomaly.input_bucket_id is None
            or anomaly.affected_window is None
        ):
            await self._mark_non_incident(anomaly, "result is not an eligible positive anomaly")
            raise IneligibleAnomaly("result is not an eligible positive anomaly")
        bucket = await self._repository.get_bucket(anomaly.input_bucket_id)
        if (
            bucket is None
            or bucket.service != anomaly.service
            or bucket.finalized_at is None
            or not bucket.eligible_for_detection
            or bucket.quality_status != "complete"
            or bucket.late_span_count != 0
        ):
            await self._mark_non_incident(anomaly, "source bucket is not detector-ready")
            raise IneligibleAnomaly("source bucket is not detector-ready")

        assigned_id = anomaly.processing.incident_id
        incident = (
            await self._repository.get_incident(assigned_id)
            if assigned_id is not None
            else await self._repository.get_active_incident(
                anomaly.service.service_id, anomaly.feature
            )
        )
        if incident is not None and anomaly.anomaly_id in incident.recent_anomaly_ids:
            if anomaly.processing.processing_state != "processed":
                await self._repository.save_anomaly(
                    anomaly.model_copy(
                        update={
                            "processing": anomaly.processing.model_copy(
                                update={
                                    "processing_state": "processed",
                                    "incident_id": incident.incident_id,
                                    "disposition": "attached",
                                    "processed_at": _utc(self._clock()),
                                }
                            )
                        }
                    )
                )
            return incident

        now = self._clock()
        observed_at = _utc(now)
        baseline_buckets = await self._repository.baseline_buckets(
            anomaly.service.service_id, anomaly.affected_window.start
        )
        recent = await self._repository.recent_buckets(
            anomaly.service.service_id, anomaly.affected_window.start
        )
        decision = severity_for(
            recent or [bucket],
            incident.recovery_baseline
            if incident
            else capture_baseline(baseline_buckets, captured_at=observed_at),
        )
        if incident is None:
            baseline = capture_baseline(baseline_buckets, captured_at=observed_at)
            incident = Incident(
                incident_id=incident_id_for(anomaly),
                primary_service=anomaly.service,
                affected_services=[anomaly.service],
                feature=anomaly.feature,
                state="open",
                severity=decision.severity,
                peak_severity=decision.severity,
                severity_reason=decision.reason,
                severity_bucket_ids=decision.bucket_ids,
                opened_by_anomaly_id=anomaly.anomaly_id,
                anomaly_count=1,
                recent_anomaly_ids=[anomaly.anomaly_id],
                related_incidents=[],
                first_affected_at=anomaly.affected_window.start,
                last_affected_at=anomaly.affected_window.end,
                detected_at=observed_at,
                updated_at=observed_at,
                recovery_baseline=baseline,
                fixture_source=fixture,
            )
        else:
            anomaly_ids = list(dict.fromkeys([*incident.recent_anomaly_ids, anomaly.anomaly_id]))[
                -100:
            ]
            peak = retain_peak(incident.peak_severity, decision.severity)
            current = retain_peak(incident.severity, decision.severity)
            incident = incident.model_copy(
                update={
                    "state": "open" if incident.state == "recovering" else incident.state,
                    "severity": current,
                    "peak_severity": peak,
                    "severity_reason": decision.reason,
                    "severity_bucket_ids": decision.bucket_ids,
                    "anomaly_count": len(anomaly_ids),
                    "recent_anomaly_ids": anomaly_ids,
                    "first_affected_at": min(
                        incident.first_affected_at, anomaly.affected_window.start
                    ),
                    "last_affected_at": max(incident.last_affected_at, anomaly.affected_window.end),
                    "updated_at": observed_at,
                    "recovering_since": None,
                    "resolved_at": None,
                    "healthy_bucket_streak": 0,
                    "fixture_source": incident.fixture_source or fixture,
                }
            )

        await self._repository.save_incident(incident)
        assigned = anomaly.model_copy(
            update={
                "processing": anomaly.processing.model_copy(
                    update={
                        "processing_state": "assigned",
                        "disposition": (
                            "opened"
                            if incident.opened_by_anomaly_id == anomaly.anomaly_id
                            else "attached"
                        ),
                        "incident_id": incident.incident_id,
                        "policy_version": POLICY_VERSION,
                        "decision_reason": (
                            "development fixture" if fixture else "eligible native detector result"
                        ),
                    }
                )
            }
        )
        await self._repository.save_anomaly(assigned)

        candidates = [anomaly_candidate(assigned), bucket_candidate(bucket)]
        candidates.extend(bucket_candidate(item) for item in baseline_buckets)
        if self._evidence_provider is not None:
            candidates.extend(await self._evidence_provider(incident, assigned))
        version = incident.evidence_version + 1
        items, bundle = build_bundle(
            incident.incident_id,
            version,
            window=anomaly.affected_window,
            candidates=candidates,
            now=now,
        )
        await self._repository.save_evidence(items, bundle)
        incident = incident.model_copy(
            update={
                "latest_evidence_bundle_id": bundle.bundle_id,
                "evidence_version": version,
                "evidence_status": "partial" if bundle.quality_status == "partial" else "ready",
                "updated_at": observed_at,
            }
        )
        incident = await self._link_related(incident, items, observed_at)
        await self._repository.save_incident(incident)
        await self._repository.save_anomaly(
            assigned.model_copy(
                update={
                    "processing": assigned.processing.model_copy(
                        update={
                            "processing_state": "processed",
                            "processed_at": observed_at,
                        }
                    )
                }
            )
        )
        return incident

    async def apply_recovery(
        self,
        incident_id: str,
        bucket: ServiceMetricBucket | None,
        *,
        both_detector_grades_zero: bool,
        raw_fresh_at: datetime | None,
    ) -> Incident:
        incident = await self._repository.get_incident(incident_id)
        if incident is None:
            raise ValueError("incident not found")
        decision = evaluate_recovery(
            incident,
            bucket,
            both_detector_grades_zero=both_detector_grades_zero,
            raw_fresh_at=raw_fresh_at,
            now=self._clock(),
        )
        severity = "low" if decision.state in ("recovering", "resolved") else incident.severity
        updated = incident.model_copy(
            update={
                "state": decision.state,
                "severity": severity,
                "healthy_bucket_streak": decision.streak,
                "recovering_since": decision.recovering_since,
                "resolved_at": decision.resolved_at,
                "last_recovery_bucket_end": decision.last_bucket_end,
                "updated_at": _utc(self._clock()),
            }
        )
        await self._repository.save_incident(updated)
        return updated

    async def _link_related(
        self, incident: Incident, items: list[EvidenceItem], linked_at: str
    ) -> Incident:
        related = list(incident.related_incidents)
        for candidate in await self._repository.related_candidates(incident):
            if candidate.incident_id == incident.incident_id:
                continue
            reason = None
            supporting_ids: list[str] = []
            if (
                candidate.primary_service == incident.primary_service
                and candidate.feature != incident.feature
            ):
                reason = "same_service_overlap"
                supporting_ids = [items[0].evidence_id]
            else:
                for item in items:
                    snapshot = item.snapshot
                    if snapshot.kind == "dependency_edge":
                        names = {
                            snapshot.edge.source_service.name,
                            snapshot.edge.target_service.name,
                        }
                        if {
                            incident.primary_service.name,
                            candidate.primary_service.name,
                        } <= names:
                            reason = "dependency_and_overlap"
                            supporting_ids = [item.evidence_id]
                            break
                    if snapshot.kind == "trace":
                        service_ids = {service.service_id for service in snapshot.services}
                        if {
                            incident.primary_service.service_id,
                            candidate.primary_service.service_id,
                        } <= service_ids:
                            reason = "shared_trace"
                            supporting_ids = [item.evidence_id]
                            break
            if reason is not None:
                if candidate.incident_id not in {item.incident_id for item in related}:
                    related.append(
                        RelatedIncident(
                            incident_id=candidate.incident_id,
                            reason=reason,
                            evidence_ids=supporting_ids,
                            linked_at=linked_at,
                        )
                    )
                reverse = list(candidate.related_incidents)
                if incident.incident_id not in {item.incident_id for item in reverse}:
                    reverse.append(
                        RelatedIncident(
                            incident_id=incident.incident_id,
                            reason=reason,
                            evidence_ids=supporting_ids,
                            linked_at=linked_at,
                        )
                    )
                    await self._repository.save_incident(
                        candidate.model_copy(
                            update={"related_incidents": reverse[:20], "updated_at": linked_at}
                        )
                    )
        return incident.model_copy(update={"related_incidents": related[:20]})

    async def _mark_non_incident(self, anomaly: NormalizedAnomaly, reason: str) -> None:
        await self._repository.save_anomaly(
            anomaly.model_copy(
                update={
                    "processing": anomaly.processing.model_copy(
                        update={
                            "processing_state": "processed",
                            "disposition": "non_anomalous",
                            "decision_reason": reason,
                            "processed_at": _utc(self._clock()),
                        }
                    )
                }
            )
        )
