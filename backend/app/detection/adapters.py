import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.detection.registry import CONFIG_VERSION, DetectorSpec
from app.models.detection import (
    NormalizedAnomaly,
    ServiceMetricBucket,
    TimeRange,
    deterministic_id,
)
from app.models.telemetry import SourceDocument


class NativeResultError(ValueError):
    pass


def epoch_ms(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise NativeResultError(f"invalid {field}")
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def optional_ratio(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NativeResultError(f"invalid {field}")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise NativeResultError(f"invalid {field}")
    return result


def feature_value(source: Mapping[str, Any], expected_name: str) -> float | None:
    data = source.get("feature_data")
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        return None
    matches = [
        item
        for item in data
        if isinstance(item, Mapping) and item.get("feature_name") == expected_name
    ]
    if len(matches) != 1:
        return None
    value = matches[0].get("data")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        value = value[0] if len(value) == 1 else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def normalize_native_result(
    *,
    source_index: str,
    source_id: str,
    native: Mapping[str, Any],
    spec: DetectorSpec,
    matching_buckets: Sequence[ServiceMetricBucket],
    observed_at: datetime,
) -> NormalizedAnomaly:
    detector_id = native.get("detector_id")
    if not isinstance(detector_id, str) or not detector_id:
        raise NativeResultError("native result has no detector_id")
    start = epoch_ms(native.get("data_start_time"), "data_start_time")
    end = epoch_ms(native.get("data_end_time"), "data_end_time")
    execution_start = epoch_ms(native.get("execution_start_time"), "execution_start_time")
    execution_end = epoch_ms(native.get("execution_end_time"), "execution_end_time")
    window = TimeRange(start=start, end=end)
    grade = optional_ratio(native.get("anomaly_grade"), "anomaly_grade")
    confidence = optional_ratio(native.get("confidence"), "confidence")
    value = feature_value(native, spec.feature)
    native_error = native.get("error")
    error = native_error[:512] if isinstance(native_error, str) and native_error else None

    bucket = matching_buckets[0] if len(matching_buckets) == 1 else None
    if error:
        status = "failed"
    elif len(matching_buckets) > 1:
        status = "failed"
        error = "detector interval selected more than one input bucket"
    elif bucket is None or value is None or grade is None:
        status = "insufficient_data"
    elif abs(value - float(getattr(bucket, spec.feature))) > max(1e-9, abs(value) * 1e-9):
        status = "failed"
        error = "native feature value did not match the selected input bucket"
    else:
        status = "anomalous" if grade > 0 else "normal"
    source = SourceDocument(index=source_index, document_id=source_id)
    return NormalizedAnomaly(
        schema_version="1.0.0",
        anomaly_id=deterministic_id("anomaly", [source_index, source_id]),
        detector_id=detector_id,
        detector_name=spec.name,
        detector_config_version=CONFIG_VERSION,
        service=spec.service,
        feature=spec.feature,
        feature_value=value,
        input_bucket_id=bucket.bucket_id if bucket else None,
        detector_window=window,
        affected_window=bucket.window if bucket else None,
        execution_started_at=execution_start,
        execution_ended_at=execution_end,
        anomaly_grade=grade,
        detector_confidence=confidence,
        result_status=status,
        error_reason=error,
        source=source,
        observed_at=observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    )
