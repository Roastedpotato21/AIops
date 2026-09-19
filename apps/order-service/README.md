# Order service

FastAPI entrypoint for the controlled demo request chain. `POST /orders` calls Payment first and Inventory only after payment succeeds. Downstream URLs and the bounded timeout come exclusively from environment-backed settings.
