from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute


class StrictQueryRoute(APIRoute):
    """Reject query fields that are not declared by the matched endpoint."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        allowed = {parameter.alias for parameter in self.dependant.query_params}

        async def handler(request: Request) -> Response:
            unknown = sorted(set(request.query_params) - allowed)
            if unknown:
                raise HTTPException(422, "validation_error")
            return await original(request)

        return handler
