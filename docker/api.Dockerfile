# syntax=docker/dockerfile:1
# Image của API trên AWS Lambda: thư viện nhóm `serving` + `lambda` và package geolife_api.
# Code thuật toán đi kèm model version (thư mục MLflow model trên S3), nên image không chứa package geolife.
# Build từ gốc repo: make aws-build (linux/arm64).

FROM ghcr.io/astral-sh/uv:0.11.18 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-default-groups --group serving --group lambda

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY src/geolife_api src/geolife_api
COPY docs/openapi.yaml docs/openapi.yaml
# Bytecode biên dịch sẵn: trên Lambda chỉ /tmp ghi được, Python không tự ghi .pyc vào /app.
RUN /app/.venv/bin/python -m compileall -q src/geolife_api
# HOME và cache của numba trỏ vào /tmp vì lý do trên.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    NUMBA_CACHE_DIR=/tmp/numba
# awslambdaric nhận event từ Runtime API của Lambda và gọi handler.
# CMD là handler; mỗi function đổi được qua image_config.command.
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["geolife_api.lambda_handlers.api"]
