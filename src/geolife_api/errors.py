"""Lỗi API dạng `{"error": {"code", "message"}}` (docs/openapi.yaml)."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _validation_message(exc: RequestValidationError) -> str:
    e = exc.errors()[0]
    field = ".".join(str(x) for x in e["loc"][1:]) or "request"
    return f"{field}: {e['msg']}"


def add_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        return error_response(400, "invalid_request", _validation_message(exc))

    @app.exception_handler(PoolTimeout)
    @app.exception_handler(OperationalError)
    async def _db_down(request: Request, exc: Exception):
        log.warning("database unavailable: %s", exc)
        return error_response(503, "db_unavailable", "database is unavailable")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("unexpected error")
        return error_response(500, "internal_error", "unexpected error")
