from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException

from inventory_service.config import InventorySettings, get_settings
from inventory_service.faults import FaultController
from inventory_service.models import (
    FaultRequest,
    FaultResponse,
    HealthResponse,
    InventoryRequest,
    InventoryResponse,
)


def create_app(
    settings: InventorySettings | None = None,
    fault_controller: FaultController | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    faults = fault_controller or FaultController()
    application = FastAPI(title="AIOps Demo Inventory Service", version="0.2.0")

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @application.post("/reserve", response_model=InventoryResponse)
    async def reserve_inventory(request: InventoryRequest) -> InventoryResponse:
        del request
        if await faults.should_error():
            raise HTTPException(status_code=500, detail="Inventory reservation unavailable")
        return InventoryResponse(reservation_id=str(uuid4()))

    if resolved.faults_allowed:
        fault_router = APIRouter(prefix="/__faults", include_in_schema=False)

        @fault_router.post("", response_model=FaultResponse)
        async def arm_fault(request: FaultRequest) -> FaultResponse:
            if request.duration_seconds > resolved.fault_max_duration_seconds:
                raise HTTPException(
                    status_code=422, detail="Fault duration exceeds configured limit"
                )
            await faults.arm(request.duration_seconds)
            return FaultResponse(expires_in_seconds=request.duration_seconds)

        application.include_router(fault_router)

    return application


app = create_app()
