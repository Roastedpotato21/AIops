from contextlib import asynccontextmanager
from uuid import uuid4

from aiops_telemetry import TelemetryRuntime, TelemetrySettings, configure_telemetry
from aiops_telemetry.config import load_telemetry_settings
from aiops_telemetry.runtime import instrument_fastapi
from fastapi import APIRouter, FastAPI, HTTPException

from payment_service.config import PaymentSettings, get_settings
from payment_service.faults import FaultController
from payment_service.models import (
    FaultRequest,
    FaultResponse,
    HealthResponse,
    PaymentRequest,
    PaymentResponse,
)


def create_app(
    settings: PaymentSettings | None = None,
    fault_controller: FaultController | None = None,
    telemetry_runtime: TelemetryRuntime | None = None,
    telemetry_settings: TelemetrySettings | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    faults = fault_controller or FaultController()
    telemetry = telemetry_runtime or configure_telemetry(
        telemetry_settings or load_telemetry_settings("payment-service")
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        telemetry.shutdown()

    application = FastAPI(
        title="AIOps Demo Payment Service", version="0.2.0", lifespan=lifespan
    )

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @application.post("/payments", response_model=PaymentResponse)
    async def process_payment(request: PaymentRequest) -> PaymentResponse:
        del request
        action = await faults.apply()
        if action == "errors":
            telemetry.logger.error("payment.failed", extra={"event": "payment.failed"})
            raise HTTPException(status_code=500, detail="Payment unavailable")
        telemetry.logger.info("payment.completed", extra={"event": "payment.completed"})
        return PaymentResponse(payment_id=str(uuid4()))

    if resolved.faults_allowed:
        fault_router = APIRouter(prefix="/__faults", include_in_schema=False)

        @fault_router.post("", response_model=FaultResponse)
        async def arm_fault(request: FaultRequest) -> FaultResponse:
            if request.duration_seconds > resolved.fault_max_duration_seconds:
                raise HTTPException(
                    status_code=422, detail="Fault duration exceeds configured limit"
                )
            await faults.arm(request.mode, request.duration_seconds, request.latency_ms)
            return FaultResponse(expires_in_seconds=request.duration_seconds)

        application.include_router(fault_router)

    instrument_fastapi(application, telemetry, {"/payments"})
    return application


app = create_app()
