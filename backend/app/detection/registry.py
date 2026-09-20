import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from app.models.detection import FeatureName, ServiceKey, deterministic_id
from app.models.telemetry import ServiceReference
from app.telemetry.aggregation.service import service_key

CONFIG_VERSION = "1.0.0"
AGGREGATION_VERSION = "1.0.0"
SHINGLE_SIZE = 8
INTERVAL_MINUTES = 1


@dataclass(frozen=True)
class DetectorSpec:
    service: ServiceKey
    feature: FeatureName
    name: str
    registration_id: str
    body: dict[str, Any]
    config_sha256: str


def _feature_suffix(feature: FeatureName) -> Literal["latency", "errors"]:
    return "latency" if feature == "latency_p95_ms" else "errors"


def detector_spec(
    service: ServiceReference,
    feature: FeatureName,
    *,
    source_index: str = "aiops-service-metrics-v1",
    result_index: str = "opensearch-ad-plugin-result-aiops-v1",
    window_delay_minutes: int = 3,
) -> DetectorSpec:
    key = service_key(service)
    suffix = _feature_suffix(feature)
    # OpenSearch 3.8 rejects detector names longer than 64 characters, so the
    # full service_id remains in the exact filter/registry while the unique
    # registered service name is used in the human-readable detector name.
    name = f"aiops-{service.name}-{suffix}-v1"
    body: dict[str, Any] = {
        "name": name,
        "description": f"AIOps Phase 5 {feature} detector for {service.name}",
        "time_field": "bucket_time",
        "indices": [source_index],
        "filter_query": {
            "bool": {
                "filter": [
                    {"term": {"service.service_id": key.service_id}},
                    {"term": {"aggregation_version": AGGREGATION_VERSION}},
                    {"term": {"eligible_for_detection": True}},
                    {"exists": {"field": "finalized_at"}},
                ]
            }
        },
        "feature_attributes": [
            {
                "feature_id": f"{suffix}-v1",
                "feature_name": feature,
                "feature_enabled": True,
                "aggregation_query": {
                    feature: {"avg": {"field": feature}},
                },
            }
        ],
        "detection_interval": {"period": {"interval": INTERVAL_MINUTES, "unit": "Minutes"}},
        "window_delay": {"period": {"interval": window_delay_minutes, "unit": "Minutes"}},
        "shingle_size": SHINGLE_SIZE,
        "schema_version": 0,
        "result_index": result_index,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return DetectorSpec(
        service=key,
        feature=feature,
        name=name,
        registration_id=deterministic_id(
            "detreg", [key.service_id, feature, CONFIG_VERSION]
        ),
        body=body,
        config_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def registered_specs(window_delay_minutes: int = 3) -> tuple[DetectorSpec, ...]:
    services = (
        ServiceReference(namespace="demo-shop", environment="development", name="order-service"),
        ServiceReference(namespace="demo-shop", environment="development", name="payment-service"),
        ServiceReference(
            namespace="demo-shop",
            environment="development",
            name="inventory-service",
        ),
    )
    return tuple(
        detector_spec(service, feature, window_delay_minutes=window_delay_minutes)
        for service in services
        for feature in ("latency_p95_ms", "error_rate")
    )
