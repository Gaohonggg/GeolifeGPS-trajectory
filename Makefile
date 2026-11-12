# Lệnh chạy stack local. Mọi lệnh chạy từ gốc repo.
COMPOSE    := docker compose -f docker/compose.yaml
DATA_DIR   ?= data/preprocess/v_1
MLFLOW_URL := http://localhost:5001

.PHONY: env up api migrate seed setup test test-all down clean

env:            ## tạo docker/.env lần đầu
	@test -f docker/.env || cp docker/.env.example docker/.env

up: env         ## postgres + mlflow
	$(COMPOSE) up -d --wait postgres mlflow

api: env        ## build và chạy API (MODEL_URI trong docker/.env)
	$(COMPOSE) up -d --build api

migrate: env    ## tạo / cập nhật bảng
	$(COMPOSE) run --rm --no-deps api python -m geolife_api.migrate

seed: env       ## nạp points.parquet vào Postgres (thêm ARGS=--replace để nạp lại)
	$(COMPOSE) run --rm --no-deps -v $(CURDIR)/$(DATA_DIR):/data:ro api \
		python -m geolife_api.seed --data-dir /data $(ARGS)

setup: up migrate seed api  ## từ đầu tới lúc API chạy (model do notebook tuning đăng ký)

test:           ## test nhanh (không cần docker)
	uv run pytest -m "not slow and not integration"

test-all:       ## mọi test: parity trên toàn bộ dữ liệu + test với stack đang chạy
	MLFLOW_TRACKING_URI=$(MLFLOW_URL) uv run pytest

down:           ## dừng stack, giữ dữ liệu
	$(COMPOSE) down

clean:          ## xoá cả dữ liệu Postgres và MLflow
	$(COMPOSE) down -v
