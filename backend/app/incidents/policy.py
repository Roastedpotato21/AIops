from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median

from app.models.detection import ServiceMetricBucket, TimeRange
from app.models.incidents import Incident, IncidentSeverity, RecoveryBaseline

POLICY_VERSION = "1.0.0"
SEVERITY_ORDER: dict[IncidentSeverity, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


@dataclass(frozen=True)
class SeverityDecision:
    severity: IncidentSeverity
    reason: str
    bucket_ids: list[str]


@dataclass(frozen=True)
class RecoveryDecision:
    state: str
    streak: int
    recovering_since: str | None
    resolved_at: str | None
    last_bucket_end: str | None
    reason: str


def capture_baseline(
    buckets: list[ServiceMetricBucket], *, captured_at: str
) -> RecoveryBaseline | None:
    eligible = [
        item
        for item in sorted(buckets, key=lambda value: value.window.start)[-30:]
        if item.finalized_at is not None
        and item.quality_status == "complete"
        and item.eligible_for_detection
        and item.request_count >= 20
        and item.late_span_count == 0
        and item.sampling_fraction == 1
        and item.latency_p95_ms is not None
        and item.error_rate is not None
    ]
    if len(eligible) < 10:
        return None
    return RecoveryBaseline(
        window=TimeRange(start=eligible[0].window.start, end=eligible[-1].window.end),
        bucket_ids=[item.bucket_id for item in eligible],
        latency_p95_median_ms=median(
            item.latency_p95_ms for item in eligible if item.latency_p95_ms is not None
        ),
        error_rate_median=median(
            item.error_rate for item in eligible if item.error_rate is not None
        ),
        captured_at=captured_at,
    )


def severity_for(
    buckets: list[ServiceMetricBucket], baseline: RecoveryBaseline | None
) -> SeverityDecision:
    considered = [
        item
        for item in sorted(buckets, key=lambda value: value.window.start, reverse=True)
        if item.finalized_at is not None
        and item.quality_status == "complete"
        and item.request_count >= 20
        and item.late_span_count == 0
    ][:5]
    bucket_ids = [item.bucket_id for item in considered]
    maximum_error = max((item.error_rate or 0 for item in considered), default=0)
    maximum_latency = max((item.latency_p95_ms or 0 for item in considered), default=0)
    if maximum_error >= 0.20:
        return SeverityDecision("critical", f"error_rate {maximum_error:.6f} >= 0.20", bucket_ids)
    if maximum_error >= 0.05:
        return SeverityDecision("high", f"error_rate {maximum_error:.6f} >= 0.05", bucket_ids)
    if baseline is not None:
        threshold = 3 * max(baseline.latency_p95_median_ms, 1)
        if maximum_latency >= threshold:
            return SeverityDecision(
                "high", f"latency_p95_ms {maximum_latency:.6f} >= {threshold:.6f}", bucket_ids
            )
    return SeverityDecision("medium", "eligible positive detector result", bucket_ids)


def retain_peak(current: IncidentSeverity, candidate: IncidentSeverity) -> IncidentSeverity:
    return candidate if SEVERITY_ORDER[candidate] > SEVERITY_ORDER[current] else current


def evaluate_recovery(
    incident: Incident,
    bucket: ServiceMetricBucket | None,
    *,
    both_detector_grades_zero: bool,
    raw_fresh_at: datetime | None,
    now: datetime,
) -> RecoveryDecision:
    baseline = incident.recovery_baseline
    if bucket is None or baseline is None:
        return RecoveryDecision(
            incident.state,
            0,
            incident.recovering_since,
            incident.resolved_at,
            incident.last_recovery_bucket_end,
            "baseline or metric bucket missing",
        )
    bucket_end = datetime.fromisoformat(bucket.window.end.replace("Z", "+00:00"))
    last_affected = datetime.fromisoformat(incident.last_affected_at.replace("Z", "+00:00"))
    fresh = (
        now.astimezone(UTC) - bucket_end <= timedelta(seconds=300)
        and raw_fresh_at is not None
        and now.astimezone(UTC) - raw_fresh_at.astimezone(UTC) <= timedelta(seconds=120)
    )
    complete = (
        bucket_end > last_affected
        and bucket.finalized_at is not None
        and bucket.quality_status == "complete"
        and bucket.request_count >= 20
        and bucket.sampling_fraction == 1
        and bucket.late_span_count == 0
        and both_detector_grades_zero
        and fresh
    )
    within_threshold = (
        bucket.latency_p95_ms is not None
        and bucket.error_rate is not None
        and bucket.latency_p95_ms <= baseline.latency_p95_median_ms * 1.2 + 10
        and bucket.error_rate <= min(1, baseline.error_rate_median + 0.01)
    )
    if not complete or not within_threshold:
        state = "open" if incident.state == "recovering" else incident.state
        return RecoveryDecision(
            state,
            0,
            None if state == "open" else incident.recovering_since,
            None if state == "open" else incident.resolved_at,
            incident.last_recovery_bucket_end,
            "stale, incomplete, anomalous, or unhealthy metric evidence",
        )
    if incident.last_recovery_bucket_end == bucket.window.end:
        return RecoveryDecision(
            incident.state,
            incident.healthy_bucket_streak,
            incident.recovering_since,
            incident.resolved_at,
            incident.last_recovery_bucket_end,
            "bucket already evaluated",
        )
    streak = incident.healthy_bucket_streak + 1
    observed = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if streak >= 5:
        return RecoveryDecision(
            "resolved",
            streak,
            incident.recovering_since,
            observed,
            bucket.window.end,
            "five consecutive healthy minutes",
        )
    if streak >= 3:
        return RecoveryDecision(
            "recovering",
            streak,
            incident.recovering_since or observed,
            None,
            bucket.window.end,
            "three consecutive healthy minutes",
        )
    return RecoveryDecision(
        "open", streak, None, None, bucket.window.end, "healthy minute recorded"
    )
