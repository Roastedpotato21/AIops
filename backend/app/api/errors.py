from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

ERROR_MESSAGES = {
    "invalid_cursor": "The pagination cursor is invalid or expired",
    "unauthenticated": "Authentication is required",
    "not_found": "The requested resource was not found",
    "conflict": "The request conflicts with current state",
    "evidence_not_ready": "Incident evidence is not ready",
    "idempotency_conflict": "The idempotency key was reused for a different request",
    "validation_error": "The request is invalid",
    "rate_limited": "The request rate limit was exceeded",
    "dependency_unavailable": "A required dependency is unavailable",
    "internal_error": "The request could not be completed",
}


def _payload(
    code: str,
    *,
    message: str | None = None,
    retryable: bool = False,
    details: list[dict[str, str]] | None = None,
    active_investigation_id: str | None = None,
) -> dict:
    return {
        "request_id": str(uuid4()),
        "error": {
            "code": code,
            "message": message or ERROR_MESSAGES[code],
            "retryable": retryable,
            "details": details or [],
            "active_investigation_id": active_investigation_id,
        },
    }


def _http_code(exc: HTTPException) -> str:
    detail = exc.detail if isinstance(exc.detail, str) else ""
    allowed = {
        "invalid_cursor",
        "unauthenticated",
        "not_found",
        "conflict",
        "evidence_not_ready",
        "idempotency_conflict",
        "validation_error",
        "rate_limited",
        "dependency_unavailable",
        "internal_error",
    }
    if detail in allowed:
        return detail
    return {
        400: "invalid_cursor",
        401: "unauthenticated",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        503: "dependency_unavailable",
    }.get(exc.status_code, "internal_error")


async def http_exception_response(_: Request, exc: HTTPException) -> JSONResponse:
    code = _http_code(exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(code, retryable=exc.status_code in {429, 503}),
        headers=exc.headers,
    )


async def validation_exception_response(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    details = []
    for error in exc.errors()[:20]:
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        details.append(
            {
                "field": location[:128] or "request",
                "reason": str(error.get("msg", "Invalid value"))[:256],
            }
        )
    return JSONResponse(
        status_code=422,
        content=_payload("validation_error", details=details),
    )


async def internal_exception_response(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=_payload("internal_error"))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_response)
    app.add_exception_handler(RequestValidationError, validation_exception_response)
    app.add_exception_handler(Exception, internal_exception_response)
