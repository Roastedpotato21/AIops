from datetime import UTC, datetime

import pytest
from test_incidents import setup_data

from app.incidents.development_fixture import FIXTURE_SOURCE_INDEX, build_fixture


def test_phase9_fixture_is_typed_labeled_and_idempotent():
    _, _, base = setup_data()
    bucket = next(
        item
        for item in base.buckets.values()
        if item.service.name == "payment-service" and item.latency_p95_ms is not None
    )
    observed = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    first = build_fixture(bucket, observed_at=observed)
    second = build_fixture(bucket, observed_at=observed)
    assert first == second
    assert first.source.index == FIXTURE_SOURCE_INDEX
    assert first.processing.processing_state == "pending"
    assert first.result_status == "anomalous"
    assert first.input_bucket_id == bucket.bucket_id


def test_phase9_fixture_rejects_non_detector_ready_bucket():
    _, _, base = setup_data()
    bucket = next(item for item in base.buckets.values() if item.service.name == "payment-service")
    ineligible = bucket.model_copy(update={"eligible_for_detection": False})
    with pytest.raises(ValueError, match="detector-ready"):
        build_fixture(ineligible, observed_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC))
