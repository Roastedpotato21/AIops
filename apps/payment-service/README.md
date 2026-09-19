# Payment service

Synthetic FastAPI payment behavior for the controlled demo. It has no real payment credentials or external provider integration. Development-only bounded faults are registered only when `APP_ENVIRONMENT` is `development`, `demo`, or `test` and `FAULT_INJECTION_ENABLED=true`.
