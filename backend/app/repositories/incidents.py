from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.models.detection import NormalizedAnomaly, ServiceMetricBucket, deterministic_id
from app.models.incidents import EvidenceBundle, EvidenceItem, Incident, IncidentSummary
from app.opensearch.query import OpenSearchQueryClient, OpenSearchQueryFailure
from app.repositories.telemetry import TelemetryRepositoryError


class OpenSearchIncidentRepository:
    def __init__(self, client: OpenSearchQueryClient, settings: Settings) -> None:
        self._client = client
        self._incidents = settings.incidents_alias
        self._evidence = settings.evidence_alias
        self._anomalies = settings.anomalies_alias
        self._metrics = settings.service_metrics_alias
        self._state = settings.bootstrap_index

    async def _search(self, index: str, body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        try:
            response = await self._client.search(index, body)
            raw = response["hits"]["hits"]
            if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
                raise TypeError
            return raw
        except (OpenSearchQueryFailure, KeyError, TypeError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc

    async def get_bucket(self, bucket_id: str) -> ServiceMetricBucket | None:
        return await self._get_model(self._metrics, bucket_id, ServiceMetricBucket)

    async def baseline_buckets(
        self, service_id: str, before: str, limit: int = 30
    ) -> list[ServiceMetricBucket]:
        hits = await self._search(
            self._metrics,
            {
                "size": limit,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"service.service_id": service_id}},
                            {"range": {"window.end": {"lte": before}}},
                            {"term": {"quality_status": "complete"}},
                            {"term": {"eligible_for_detection": True}},
                            {"term": {"late_span_count": 0}},
                        ]
                    }
                },
                "sort": [{"window.start": "desc"}, {"bucket_id": "asc"}],
            },
        )
        return list(reversed(self._models(hits, ServiceMetricBucket)))

    async def recent_buckets(
        self, service_id: str, start: str, limit: int = 5
    ) -> list[ServiceMetricBucket]:
        hits = await self._search(
            self._metrics,
            {
                "size": limit,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"service.service_id": service_id}},
                            {"range": {"window.start": {"gte": start}}},
                        ]
                    }
                },
                "sort": [{"window.start": "desc"}, {"bucket_id": "asc"}],
            },
        )
        return self._models(hits, ServiceMetricBucket)

    async def get_incident(self, incident_id: str) -> Incident | None:
        return await self._get_model(self._incidents, incident_id, Incident)

    async def get_incident_record(self, incident_id: str) -> tuple[Incident, int, int] | None:
        try:
            response = await self._client.get_document(self._incidents, incident_id)
            if response is None:
                return None
            return (
                Incident.model_validate(response["_source"]),
                int(response["_seq_no"]),
                int(response["_primary_term"]),
            )
        except (OpenSearchQueryFailure, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc

    async def get_active_incident(self, service_id: str, feature: str) -> Incident | None:
        hits = await self._search(
            self._incidents,
            {
                "size": 2,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"primary_service.service_id": service_id}},
                            {"term": {"feature": feature}},
                            {"terms": {"state": ["open", "recovering"]}},
                            {"term": {"policy_version": "1.0.0"}},
                        ]
                    }
                },
                "sort": [{"detected_at": "asc"}, {"incident_id": "asc"}],
            },
        )
        models = self._models(hits, Incident)
        if len(models) > 1:
            raise TelemetryRepositoryError("unavailable", retryable=False)
        return models[0] if models else None

    async def related_candidates(self, incident: Incident) -> list[Incident]:
        start = datetime.fromisoformat(incident.first_affected_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(incident.last_affected_at.replace("Z", "+00:00"))
        start_value = (start - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        end_value = (end + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        namespace = incident.primary_service.namespace
        environment = incident.primary_service.environment
        hits = await self._search(
            self._incidents,
            {
                "size": 20,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"primary_service.namespace": namespace}},
                            {"term": {"primary_service.environment": environment}},
                            {
                                "range": {
                                    "first_affected_at": {
                                        "gte": start_value,
                                        "lte": end_value,
                                    }
                                }
                            },
                        ],
                        "must_not": [{"term": {"incident_id": incident.incident_id}}],
                    }
                },
            },
        )
        return self._models(hits, Incident)

    async def save_incident(self, incident: Incident) -> None:
        await self._put(self._incidents, incident.incident_id, incident.model_dump(mode="json"))

    async def save_incident_cas(self, incident: Incident, *, concurrency: tuple[int, int]) -> None:
        try:
            await self._client.put_document(
                self._incidents,
                incident.incident_id,
                incident.model_dump(mode="json"),
                refresh=True,
                if_seq_no=concurrency[0],
                if_primary_term=concurrency[1],
            )
        except OpenSearchQueryFailure as exc:
            raise TelemetryRepositoryError(
                "unavailable", retryable=exc.code == "unavailable"
            ) from exc

    async def save_anomaly(self, anomaly: NormalizedAnomaly) -> None:
        await self._put(self._anomalies, anomaly.anomaly_id, anomaly.model_dump(mode="json"))

    async def save_evidence(self, items: list[EvidenceItem], bundle: EvidenceBundle) -> None:
        for item in items:
            await self._put(self._evidence, item.evidence_id, item.model_dump(mode="json"))
        await self._put(self._evidence, bundle.bundle_id, bundle.model_dump(mode="json"))

    async def save_evidence_items(self, items: list[EvidenceItem]) -> None:
        for item in items:
            await self._put(self._evidence, item.evidence_id, item.model_dump(mode="json"))

    async def metric_buckets(
        self,
        service_ids: list[str],
        start: str,
        end: str,
        *,
        limit: int,
    ) -> list[ServiceMetricBucket]:
        hits = await self._search(
            self._metrics,
            {
                "size": limit,
                "query": {
                    "bool": {
                        "filter": [
                            {"terms": {"service.service_id": service_ids}},
                            {"range": {"window.start": {"gte": start, "lt": end}}},
                        ]
                    }
                },
                "sort": [{"window.start": "asc"}, {"bucket_id": "asc"}],
            },
        )
        return self._models(hits, ServiceMetricBucket)

    async def pending_anomalies(self, limit: int = 100) -> list[NormalizedAnomaly]:
        hits = await self._search(
            self._anomalies,
            {
                "size": limit,
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"processing.processing_state": "pending"}},
                            {"term": {"processing.processing_state": "assigned"}},
                            {
                                "bool": {
                                    "must_not": {"exists": {"field": "processing.processing_state"}}
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "sort": [{"execution_ended_at": "asc"}, {"anomaly_id": "asc"}],
            },
        )
        return self._models(hits, NormalizedAnomaly)

    async def save_worker_progress(self, anomaly: NormalizedAnomaly, *, owner_id: str) -> None:
        worker_id = deterministic_id("worker", ["incident", "normalized-anomalies-v1"])
        timestamp = anomaly.processing.processed_at or anomaly.observed_at
        await self._put(
            self._state,
            worker_id,
            {
                "schema_version": "1.0.0",
                "record_kind": "worker_cursor",
                "worker_state_id": worker_id,
                "role": "incident",
                "partition": "normalized-anomalies-v1",
                "cursor": {
                    "kind": "incident",
                    "execution_ended_at": anomaly.execution_ended_at,
                    "anomaly_id": anomaly.anomaly_id,
                },
                "owner_id": owner_id,
                "heartbeat_at": timestamp,
                "status": "running",
                "last_error": None,
                "updated_at": timestamp,
            },
        )

    async def list_incidents(
        self,
        *,
        namespace: str,
        environment: str,
        state: str | None,
        severity: str | None,
        service_id: str | None,
        start: str,
        end: str,
        limit: int,
    ) -> list[IncidentSummary]:
        filters: list[dict[str, Any]] = [
            {"term": {"primary_service.namespace": namespace}},
            {"term": {"primary_service.environment": environment}},
            {"range": {"detected_at": {"gte": start, "lt": end}}},
        ]
        if state:
            filters.append({"term": {"state": state}})
        if severity:
            filters.append({"term": {"severity": severity}})
        if service_id:
            filters.append(
                {
                    "nested": {
                        "path": "affected_services",
                        "query": {"term": {"affected_services.service_id": service_id}},
                    }
                }
            )
        hits = await self._search(
            self._incidents,
            {
                "size": limit,
                "query": {"bool": {"filter": filters}},
                "sort": [{"detected_at": "desc"}, {"incident_id": "asc"}],
            },
        )
        incidents = self._models(hits, Incident)
        return [
            IncidentSummary(
                incident_id=item.incident_id,
                primary_service=item.primary_service,
                feature=item.feature,
                state=item.state,
                severity=item.severity,
                peak_severity=item.peak_severity,
                detected_at=item.detected_at,
                first_affected_at=item.first_affected_at,
                updated_at=item.updated_at,
                evidence_status=item.evidence_status,
                latest_investigation_id=item.latest_investigation_id,
                fixture_source=item.fixture_source,
            )
            for item in incidents
        ]

    async def get_bundle(self, bundle_id: str) -> EvidenceBundle | None:
        return await self._get_model(self._evidence, bundle_id, EvidenceBundle)

    async def get_bundle_version(self, incident_id: str, version: int) -> EvidenceBundle | None:
        hits = await self._search(
            self._evidence,
            {
                "size": 1,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"record_kind": "evidence_bundle"}},
                            {"term": {"incident_id": incident_id}},
                            {"term": {"version": version}},
                        ]
                    }
                },
            },
        )
        models = self._models(hits, EvidenceBundle)
        return models[0] if models else None

    async def get_evidence_items(self, evidence_ids: list[str]) -> list[EvidenceItem]:
        if not evidence_ids:
            return []
        hits = await self._search(
            self._evidence,
            {
                "size": len(evidence_ids),
                "query": {"terms": {"evidence_id": evidence_ids}},
            },
        )
        by_id = {item.evidence_id: item for item in self._models(hits, EvidenceItem)}
        return [by_id[item_id] for item_id in evidence_ids if item_id in by_id]

    async def _get_model(self, index: str, document_id: str, model):
        try:
            result = await self._client.get_document(index, document_id)
            if result is None:
                return None
            return model.model_validate(result["_source"])
        except (OpenSearchQueryFailure, KeyError, TypeError, ValidationError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc

    @staticmethod
    def _models(hits: list[Mapping[str, Any]], model):
        try:
            return [model.model_validate(hit["_source"]) for hit in hits]
        except (KeyError, TypeError, ValidationError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=False) from exc

    async def _put(self, index: str, document_id: str, document: Mapping[str, Any]) -> None:
        try:
            await self._client.put_document(index, document_id, document, refresh=True)
        except OpenSearchQueryFailure as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc
