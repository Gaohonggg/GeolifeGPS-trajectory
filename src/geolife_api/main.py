"""FastAPI app: `create_app(store=...)` với một `PointStore` (mặc định `S3PointStore` theo `POINTS_URI`).

Model nạp ở thread nền; trong lúc chưa nạp xong, /v1/health và endpoint dự đoán trả 503.
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import Annotated

import yaml
from fastapi import APIRouter, FastAPI, Path, Query, Request
from fastapi.responses import JSONResponse

from . import model as model_lib
from .config import Settings
from .errors import ApiError, add_handlers
from .points import S3PointStore
from .schemas import Health, UserPrediction
from .service import PointStore, predict_user

log = logging.getLogger(__name__)


class State:
    """Nguồn điểm GPS và model đang serve."""

    def __init__(self, store: PointStore, model: model_lib.LoadedModel | None = None):
        self.store = store
        self.model = model
        self.stop = threading.Event()


def _load_model_forever(state: State, uri: str, retry_s: float) -> None:
    while not state.stop.is_set():
        try:
            state.model = model_lib.load(uri)
            log.info("serving %s v%s from %s", state.model.info.name, state.model.info.version, uri)
            return
        except Exception:
            log.exception("cannot load %s, retrying in %.0fs", uri, retry_s)
            state.stop.wait(retry_s)


router = APIRouter(prefix="/v1")


@router.get("/health", response_model=Health)
def health(request: Request):
    state: State = request.app.state.geolife
    h = Health(status="ok", model_loaded=state.model is not None, data_available=state.store.ping())
    if not (h.model_loaded and h.data_available):
        h.status = "unavailable"
        return JSONResponse(status_code=503, content=h.model_dump())
    return h


@router.post("/users/{user_id}/predictions", response_model=UserPrediction)
def predict(request: Request, user_id: Annotated[int, Path(ge=0)],
            start: Annotated[str | None, Query()] = None, end: Annotated[str | None, Query()] = None):
    state: State = request.app.state.geolife
    if state.model is None:
        raise ApiError(503, "model_unavailable", "model is loading")
    return predict_user(state.store, state.model, user_id, start, end)


def create_app(store: PointStore | None = None, settings: Settings | None = None,
               state: State | None = None) -> FastAPI:
    """App với `state` dựng sẵn (Lambda, test), hoặc tự dựng trong lifespan (uvicorn).

    - Có `state`: gắn ngay vào app, không cần lifespan (Mangum chạy với `lifespan="off"`).
    - Không có `state`: lifespan dựng nguồn điểm (`store`, mặc định theo `POINTS_URI`) và nạp model ở thread nền.
      Chạy ở local: `uvicorn --factory geolife_api.main:create_app` (`make api`).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        s = settings or Settings()
        st = State(store or S3PointStore(s.points_uri))
        app.state.geolife = st
        threading.Thread(target=_load_model_forever, args=(st, s.model_uri, s.model_retry_s), daemon=True).start()
        yield
        st.stop.set()

    app = FastAPI(title="GeoLife Home/Office API", lifespan=lifespan if state is None else None)
    if state is not None:
        app.state.geolife = state
    app.include_router(router)
    add_handlers(app)

    spec_path = settings.openapi_path if settings else Settings.model_fields["openapi_path"].default
    if spec_path.exists():   # /docs hiển thị đúng contract thay vì schema FastAPI tự sinh
        spec = yaml.safe_load(spec_path.read_text())
        app.openapi = lambda: spec
    return app

