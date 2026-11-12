"""FastAPI app.

    uvicorn geolife_api.main:app --port 8000

Model được nạp trong một thread nền: trong lúc nạp (hoặc khi MLflow chưa lên), /v1/health trả 503 và endpoint dự đoán
trả 503 `model_unavailable`. Swagger UI ở /docs hiển thị đúng contract trong docs/openapi.yaml.
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
from .db import Database
from .errors import ApiError, add_handlers
from .schemas import Health, UserPrediction
from .service import predict_user

log = logging.getLogger(__name__)


class State:
    """Những thứ app giữ suốt vòng đời: kết nối DB và model đang serve."""

    def __init__(self, db: Database, model: model_lib.LoadedModel | None = None):
        self.db = db
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
    h = Health(status="ok", model_loaded=state.model is not None, db_connected=state.db.ping())
    if not (h.model_loaded and h.db_connected):
        h.status = "unavailable"
        return JSONResponse(status_code=503, content=h.model_dump())
    return h


@router.post("/users/{user_id}/predictions", response_model=UserPrediction)
def predict(request: Request, user_id: Annotated[int, Path(ge=0)],
            start: Annotated[str | None, Query()] = None, end: Annotated[str | None, Query()] = None):
    state: State = request.app.state.geolife
    if state.model is None:
        raise ApiError(503, "model_unavailable", "model is loading")
    return predict_user(state.db, state.model, user_id, start, end)


def create_app(settings: Settings | None = None, state: State | None = None) -> FastAPI:
    """settings: đọc từ biến môi trường nếu không truyền. state: truyền sẵn (vd. trong test) thì không nạp DB / model."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state is not None:
            app.state.geolife = state
            yield
            return
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        s = settings or Settings()
        st = State(Database(s.database_url, s.db_pool_size))
        st.db.open()
        app.state.geolife = st
        threading.Thread(target=_load_model_forever, args=(st, s.model_uri, s.model_retry_s), daemon=True).start()
        yield
        st.stop.set()
        st.db.close()

    app = FastAPI(title="GeoLife Home/Office API", lifespan=lifespan)
    app.include_router(router)
    add_handlers(app)

    spec_path = settings.openapi_path if settings else Settings.model_fields["openapi_path"].default
    if spec_path.exists():
        spec = yaml.safe_load(spec_path.read_text())
        app.openapi = lambda: spec
    return app


app = create_app()
