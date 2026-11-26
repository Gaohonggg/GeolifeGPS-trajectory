"""Handler của AWS Lambda cho API.

Lambda không nhận HTTP. API Gateway (HTTP API) đóng gói request thành event JSON (payload v2) và gọi function; Lambda
giao event cho `api(event, context)`. Mangum đổi event thành request ASGI cho app FastAPI rồi đổi response thành dict
`{"statusCode", "headers", "body", ...}` để API Gateway trả về client. App FastAPI giống hệt khi chạy bằng uvicorn.

Image chạy `python -m awslambdaric geolife_api.lambda_handlers.api`. `awslambdaric` import module và lấy `api` trong
pha init của execution environment, trước request đầu tiên. Lần lấy `api` đầu tiên chạy `_init`: đọc cấu hình, dựng
app, nạp model. Model nạp ở đây chứ không trong lifespan của FastAPI vì Mangum chạy lifespan quanh từng lần gọi.

Pha init của function on-demand có trần 10 giây; quá trần thì Lambda bỏ init đó và chạy lại toàn bộ init trong request
đầu tiên, nên request chờ gần gấp đôi. Vì vậy model nạp ở thread nền và pha init chỉ chờ thread này tới
`INIT_BUDGET_S` giây (tính từ lúc bắt đầu import module):

- Nạp xong trong hạn: request đầu chạy ngay, như khi nạp tuần tự.
- Hết hạn: pha init vẫn kết thúc, thread tiếp tục nạp; request đầu tiên chờ phần còn lại.
- Nạp lỗi: thread nạp lại ngay. Lỗi xảy ra khi đã có request đang chờ thì request đó trả `503 model_unavailable`;
  request sau chờ lần nạp mới.

Response đầu tiên của mỗi environment có header `X-Cold-Start: 1` để phía client tách request có cold start khi đo.
"""
from __future__ import annotations

import time

# Mốc bắt đầu import module: hạn của pha init và thời gian import thư viện đều tính từ đây.
_IMPORT_START = time.perf_counter()

import logging
import threading
from collections.abc import Callable

from fastapi import FastAPI
from mangum import Mangum

from . import model as model_lib
from .config import Settings
from .main import State, create_app
from .points import S3PointStore

log = logging.getLogger(__name__)

Handler = Callable[[dict, object], dict]


class ModelLoader:
    """Nạp model từ `uri` ở thread nền, bắt đầu ngay khi tạo."""

    def __init__(self, uri: str):
        self.uri = uri
        self._start()

    def _start(self) -> None:
        self._done = threading.Event()
        self._model: model_lib.LoadedModel | None = None
        self._error: Exception | None = None
        threading.Thread(target=self._run, name="model-load", daemon=True).start()

    def _run(self) -> None:
        try:
            self._model = model_lib.load(self.uri)
        except Exception as e:   # giữ lỗi để báo ở get(), thread nền không có ai nhận exception
            self._error = e
        finally:
            self._done.set()

    def wait(self, timeout: float) -> bool:
        """Chờ tối đa `timeout` giây; True nếu đã nạp xong (thành công hoặc lỗi)."""
        return self._done.wait(max(timeout, 0.0))

    def get(self) -> model_lib.LoadedModel:
        """Chờ tới khi nạp xong. Nạp lỗi thì bắt đầu nạp lại ở nền rồi raise lỗi đó."""
        self._done.wait()
        if self._error is not None:
            error = self._error
            self._start()
            raise error
        return self._model


def make_handler(app: FastAPI, loader: ModelLoader | None = None) -> Handler:
    """Handler cho HTTP API payload v2; gắn `X-Cold-Start: 1` vào response đầu tiên.

    Có `loader` và app chưa có model: chờ `loader` trước khi chuyển request cho app.
    """
    adapter = Mangum(app, lifespan="off")
    state: State = app.state.geolife
    first = True

    def handler(event: dict, context) -> dict:
        nonlocal first
        if state.model is None and loader is not None:
            t0 = time.perf_counter()
            if _take_model(state, loader):
                waited = {"modelWaitS": round(time.perf_counter() - t0, 3)}
                log.info("request waited %.2fs for the model", *waited.values(), extra=waited)
        response = adapter(event, context)
        if first:
            response.setdefault("headers", {})["x-cold-start"] = "1"
            first = False
        return response

    return handler


def _take_model(state: State, loader: ModelLoader) -> bool:
    """Chờ `loader` rồi gắn model vào `state`; False nếu nạp lỗi."""
    try:
        state.model = loader.get()
    except Exception:
        # state.model vẫn None nên app trả 503 model_unavailable; loader đã bắt đầu nạp lại
        log.exception("cannot load model from %s, reloading", loader.uri)
        return False
    return True


def _init() -> Handler:
    t0 = time.perf_counter()
    logging.getLogger().setLevel(logging.INFO)
    s = Settings()
    loader = ModelLoader(s.model_uri)
    # dựng nguồn điểm và app trong lúc thread nền nạp model
    state = State(S3PointStore(s.points_uri))
    handler = make_handler(create_app(state=state, settings=s), loader)
    ready = loader.wait(s.init_budget_s - (time.perf_counter() - _IMPORT_START))
    if ready:
        _take_model(state, loader)
    timings = {"importS": round(t0 - _IMPORT_START, 3), "initS": round(time.perf_counter() - _IMPORT_START, 3),
               "modelReady": state.model is not None}
    log.info("init done for %s: import %.2fs, init %.2fs, model ready %s", s.model_uri, *timings.values(),
             extra=timings)
    return handler


_handlers: dict[str, Handler] = {}


def __getattr__(name: str) -> Handler:
    # Dựng handler khi được lấy lần đầu (pha init trên Lambda), không phải lúc import,
    # để test import được module mà không nạp model
    if name != "api":
        raise AttributeError(name)
    if name not in _handlers:
        _handlers[name] = _init()
    return _handlers[name]
