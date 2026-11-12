# syntax=docker/dockerfile:1
# Image của API: chỉ chứa thư viện (nhóm `serving` + thư viện thuật toán) và package geolife_api.
# Code thuật toán (geolife) không nằm trong image: nó đi kèm model version, tải từ MLflow registry lúc khởi động.
# Build từ gốc repo:  docker build -f docker/api.Dockerfile .

FROM ghcr.io/astral-sh/uv:0.11.18 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-default-groups --group serving

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY src/geolife_api src/geolife_api
COPY db/migrations db/migrations
COPY docs/openapi.yaml docs/openapi.yaml
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    NUMBA_CACHE_DIR=/tmp/numba
USER app
EXPOSE 8000
CMD ["uvicorn", "geolife_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
