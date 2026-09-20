import hashlib
import json
from datetime import UTC, datetime

from app.config import Settings
from app.models.detection import deterministic_id
from app.models.incidents import SchedulingReservation
from app.models.investigation import InvestigationCreate, InvestigationJob, InvestigationView
from app.repositories.telemetry import TelemetryRepositoryError


class SchedulingConflict(RuntimeError):
    def __init__(self, code: str, active_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.active_id = active_id


class InvestigationScheduler:
    def __init__(self, incidents, investigations, settings: Settings) -> None:
        self._incidents = incidents
        self._investigations = investigations
        self._settings = settings

    async def schedule(
        self,
        incident_id: str,
        request: InvestigationCreate,
        *,
        principal_id: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> InvestigationJob:
        if (
            not 1 <= len(idempotency_key) <= 128
            or not idempotency_key.isascii()
            or not idempotency_key.isprintable()
        ):
            raise SchedulingConflict("invalid_argument")
        incident_record = await self._incidents.get_incident_record(incident_id)
        if incident_record is None:
            raise SchedulingConflict("not_found")
        incident, seq_no, primary_term = incident_record
        if incident.latest_evidence_bundle_id is None or incident.evidence_version < 1:
            raise SchedulingConflict("evidence_not_ready")
        bundle = (
            await self._incidents.get_bundle_version(incident_id, request.evidence_version)
            if request.evidence_version is not None
            else await self._incidents.get_bundle(incident.latest_evidence_bundle_id)
        )
        if bundle is None:
            raise SchedulingConflict("evidence_not_ready")
        body_sha = hashlib.sha256(_canonical(request.model_dump(mode="json"))).hexdigest()
        key_hash = hashlib.sha256(
            _canonical([principal_id, incident_id, idempotency_key])
        ).hexdigest()
        investigation_id = deterministic_id("inv", [principal_id, incident_id, idempotency_key])
        existing = await self._investigations.get_job(investigation_id)
        if existing is not None:
            job = existing[0]
            if job.request_body_sha256 != body_sha or job.incident_id != incident_id:
                raise SchedulingConflict("idempotency_conflict", job.investigation_id)
            return job
        active = await self._investigations.active_job(incident_id)
        if active is not None:
            raise SchedulingConflict("conflict", active.investigation_id)
        created_at = _utc(now or datetime.now(UTC))
        if incident.scheduling_reservation is not None:
            reserved = incident.scheduling_reservation
            if reserved.investigation_id != investigation_id:
                raise SchedulingConflict("conflict", reserved.investigation_id)
        elif incident.user_job_count >= 5:
            raise SchedulingConflict("rate_limited")
        else:
            reservation = SchedulingReservation(
                investigation_id=investigation_id,
                trigger="user",
                principal_id=principal_id,
                idempotency_key_hash=key_hash,
                request_body_sha256=body_sha,
                requested_evidence_version=request.evidence_version,
                resolved_evidence_bundle_id=bundle.bundle_id,
                resolved_evidence_version=bundle.version,
                reserved_at=created_at,
                provider_id=self._settings.llm_provider,
                model_id=self._settings.llm_model,
                prompt_version="1.0.0",
                tool_contract_version="1.0.0",
            )
            try:
                await self._incidents.save_incident_cas(
                    incident.model_copy(
                        update={
                            "scheduling_reservation": reservation,
                            "user_job_count": incident.user_job_count + 1,
                            "last_user_job_at": created_at,
                            "updated_at": created_at,
                        }
                    ),
                    concurrency=(seq_no, primary_term),
                )
            except TelemetryRepositoryError as exc:
                raise SchedulingConflict("conflict") from exc
        job = InvestigationJob(
            investigation_id=investigation_id,
            incident_id=incident_id,
            evidence_bundle_id=bundle.bundle_id,
            evidence_version=bundle.version,
            trigger="user",
            requested_by=principal_id,
            idempotency_key_hash=key_hash,
            request_body_sha256=body_sha,
            requested_evidence_version=request.evidence_version,
            state="queued",
            attempt_count=0,
            created_at=created_at,
            updated_at=created_at,
            provider_id=self._settings.llm_provider,
            model_id=self._settings.llm_model,
            additional_evidence_ids=[],
            tool_calls_used=0,
            tool_executions=[],
            fixture_source=incident.fixture_source,
        )
        persisted = await self._investigations.create_job(job)
        current = await self._incidents.get_incident_record(incident_id)
        if current is not None:
            current_incident, current_seq, current_term = current
            reservation = current_incident.scheduling_reservation
            if reservation and reservation.investigation_id == persisted.investigation_id:
                await self._incidents.save_incident_cas(
                    current_incident.model_copy(
                        update={
                            "latest_investigation_id": persisted.investigation_id,
                            "scheduling_reservation": None,
                            "updated_at": created_at,
                        }
                    ),
                    concurrency=(current_seq, current_term),
                )
        return persisted

    async def view(self, investigation_id: str) -> InvestigationView | None:
        record = await self._investigations.get_job(investigation_id)
        if record is None:
            return None
        job = record[0]
        items = await self._incidents.get_evidence_items(job.additional_evidence_ids)
        return InvestigationView(
            investigation_id=job.investigation_id,
            incident_id=job.incident_id,
            evidence_version=job.evidence_version,
            state=job.state,
            attempt_count=job.attempt_count,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            report=job.report,
            failure=job.last_error,
            additional_evidence=items,
            fixture_source=job.fixture_source,
        )


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
