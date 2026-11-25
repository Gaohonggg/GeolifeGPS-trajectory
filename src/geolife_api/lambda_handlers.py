"""Handler của AWS Lambda cho API.

Lambda không nhận HTTP. API Gateway (HTTP API) đóng gói request thành event JSON (payload v2) và gọi function; Lambda
giao event cho `api(event, context)`. Mangum đổi event thành request ASGI cho app FastAPI rồi đổi response thành dict
`{"statusCode", "headers", "body", ...}` để API Gateway trả về client. App FastAPI giống hệt khi chạy bằng uvicorn.

Image chạy `python -m awslambdaric geolife_api.lambda_handlers.api`. `awslambdaric` import module và lấy `api` trong
pha init của execution environment, trước request đầu tiên. Lần lấy `api` đầu tiên chạy `_init`: đọc cấu hình, nạp
model, dựng app. Model nạp ở đây chứ không trong lifespan của FastAPI vì Mangum chạy lifespan quanh từng lần gọi.
Init lỗi thì Lambda báo lỗi init và thử init lại ở request sau.

Response đầu tiên của mỗi environment có header `X-Cold-Start: 1` để phía client tách request có cold start khi đo.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import FastAPI
from mangum import Mangum

from . import model as model_lib
from .config import Settings
from .main import State, create_app
from .points import S3PointStore

log = logging.getLogger(__name__)

Handler = Callable[[dict, object], dict]


def make_handler(app: FastAPI) -> Handler:
    """Handler cho HTTP API payload v2; gắn `X-Cold-Start: 1` vào response đầu tiên."""
    adapter = Mangum(app, lifespan="off")
    first = True

    def handler(event: dict, context) -> dict:
        nonlocal first
        response = adapter(event, context)
        if first:
            response.setdefault("headers", {})["x-cold-start"] = "1"
            first = False
        return response

    return handler


def _init() -> Handler:
    logging.getLogger().setLevel(logging.INFO)
    s = Settings()
    model = model_lib.load(s.model_uri)
    log.info("serving %s v%s from %s", model.info.name, model.info.version, s.model_uri)
    state = State(S3PointStore(s.points_uri), model)
    return make_handler(create_app(state=state, settings=s))


_handlers: dict[str, Handler] = {}


def __getattr__(name: str) -> Handler:
    # Dựng handler khi được lấy lần đầu (pha init trên Lambda), không phải lúc import,
    # để test import được module mà không nạp model
    if name != "api":
        raise AttributeError(name)
    if name not in _handlers:
        _handlers[name] = _init()
    return _handlers[name]
