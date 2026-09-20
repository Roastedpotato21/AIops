from datetime import UTC, datetime

import pytest

from app.detection.adapters import NativeResultError, normalize_native_result
from app.detection.registry import detector_spec, registered_specs
from app.models.telemetry import ServiceReference
from app.telemetry.aggregation.service import aggregate_minute, empty_query_result


def payment_spec():
    return detector_spec(
        ServiceReference(namespace="demo-shop", environment="development", name="payment-service"),
        "error_rate",
    )


def bucket():
    return aggregate_minute(
        ServiceReference(namespace="demo-shop", environment="development", name="payment-service"),
        datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        empty_query_result(),
        computed_at=datetime(2026, 9, 19, 12, 2, tzinfo=UTC),
        finalized=True,
    ).model_copy(
        update={
            "request_count": 20,
            "source_count": 20,
            "error_count": 2,
            "error_rate": 0.1,
            "latency_mean_ms": 10.0,
            "latency_p95_ms": 12.0,
            "quality_status": "complete",
            "quality_reasons": [],
            "eligible_for_detection": True,
        }
    )


def native(grade=0.4):
    return {
        "detector_id": "native-detector",
        "data_start_time": 1_789_819_200_000,
        "data_end_time": 1_789_819_260_000,
        "execution_start_time": 1_789_819_380_000,
        "execution_end_time": 1_789_819_381_000,
        "anomaly_grade": grade,
        "confidence": 0.91,
        "feature_data": [{"feature_name": "error_rate", "data": 0.1}],
        "error": "",
    }


def test_registry_has_six_stable_detector_specs():
    first = registered_specs()
    second = registered_specs()
    assert len(first) == 6
    assert [item.registration_id for item in first] == [item.registration_id for item in second]
    assert len({item.name for item in first}) == 6
    assert all(item.body["shingle_size"] == 8 for item in first)


def test_native_result_normalizes_and_links_exact_bucket():
    result = normalize_native_result(
        source_index="native-results-000001",
        source_id="result-1",
        native=native(),
        spec=payment_spec(),
        matching_buckets=[bucket()],
        observed_at=datetime(2026, 9, 19, 12, 4, tzinfo=UTC),
    )
    assert result.result_status == "anomalous"
    assert result.input_bucket_id == bucket().bucket_id
    assert result.feature_value == 0.1
    assert result.anomaly_grade == 0.4


def test_missing_bucket_is_insufficient_not_normal():
    result = normalize_native_result(
        source_index="native-results-000001",
        source_id="result-2",
        native=native(grade=0),
        spec=payment_spec(),
        matching_buckets=[],
        observed_at=datetime(2026, 9, 19, 12, 4, tzinfo=UTC),
    )
    assert result.result_status == "insufficient_data"


def test_ambiguous_bucket_and_feature_mismatch_fail_safely():
    ambiguous = normalize_native_result(
        source_index="native-results-000001",
        source_id="result-3",
        native=native(),
        spec=payment_spec(),
        matching_buckets=[bucket(), bucket()],
        observed_at=datetime(2026, 9, 19, 12, 4, tzinfo=UTC),
    )
    assert ambiguous.result_status == "failed"
    changed = native()
    changed["feature_data"] = [{"feature_name": "error_rate", "data": 0.2}]
    mismatch = normalize_native_result(
        source_index="native-results-000001",
        source_id="result-4",
        native=changed,
        spec=payment_spec(),
        matching_buckets=[bucket()],
        observed_at=datetime(2026, 9, 19, 12, 4, tzinfo=UTC),
    )
    assert mismatch.result_status == "failed"


def test_invalid_native_timestamp_is_rejected():
    invalid = native()
    invalid["data_start_time"] = "not-a-time"
    with pytest.raises(NativeResultError):
        normalize_native_result(
            source_index="native-results-000001",
            source_id="result-5",
            native=invalid,
            spec=payment_spec(),
            matching_buckets=[],
            observed_at=datetime(2026, 9, 19, 12, 4, tzinfo=UTC),
        )
