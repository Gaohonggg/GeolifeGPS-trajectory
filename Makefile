# Stack local, chạy từ gốc repo.
COMPOSE    := docker compose --env-file .env -f docker/compose.yaml
DATA_DIR   ?= data/preprocess/v_1

.PHONY: env up api migrate seed setup test test-all down clean

env:            ## tạo .env lần đầu
	@test -f .env || cp .env.example .env

up: env         ## postgres
	$(COMPOSE) up -d --wait postgres

api: env        ## build và chạy API
	$(COMPOSE) up -d --build api

migrate: env    ## tạo / cập nhật bảng
	$(COMPOSE) run --rm --no-deps api python -m geolife_api.migrate

seed: env       ## nạp dữ liệu (ARGS=--replace để nạp lại)
	$(COMPOSE) run --rm --no-deps -v $(CURDIR)/$(DATA_DIR):/data:ro api \
		python -m geolife_api.seed --data-dir /data $(ARGS)

setup: up migrate seed api  ## từ đầu tới lúc API chạy

test:           ## test nhanh (không cần docker)
	uv run pytest -m "not slow and not integration"

test-all:       ## thêm parity toàn bộ dữ liệu + test với stack đang chạy
	uv run pytest

down:           ## dừng stack, giữ dữ liệu
	$(COMPOSE) down

clean:          ## dừng và xoá dữ liệu Postgres
	$(COMPOSE) down -v
