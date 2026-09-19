# Inventory service

Synthetic FastAPI inventory reservation behavior for the controlled demo. Development-only bounded faults are registered only when `APP_ENVIRONMENT` is `development`, `demo`, or `test` and `FAULT_INJECTION_ENABLED=true`.
