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

# ---- AWS  ----
# aws CLI, Terraform và boto3 đều đọc hai biến này; đổi bằng `make <lệnh> AWS_PROFILE=...`
export AWS_PROFILE ?= geolife-dev
export AWS_REGION  ?= ap-southeast-1

# `=` thay vì `:=`: chỉ gọi aws / git khi lệnh cần tới
# make 3.81 của macOS không truyền biến export vào $(shell), nên truyền profile tường minh
AWS_ACCOUNT = $(shell AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text)
ECR_HOST    = $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com
ECR_REPO    = $(ECR_HOST)/geolife-api
GIT_SHA     = $(shell git rev-parse --short=12 HEAD)
IMAGE       = geolife-api:$(GIT_SHA)

.PHONY: aws-whoami aws-build aws-push aws-publish-model

aws-whoami:     ## tài khoản và user đang dùng
	aws sts get-caller-identity

# --provenance=false: không đính attestation, nên image là một manifest đơn thay vì OCI index có manifest con
aws-build:      ## build image linux/arm64 (Fargate Graviton), tag theo git SHA
	docker buildx build --platform linux/arm64 --provenance=false --sbom=false -f docker/api.Dockerfile -t $(IMAGE) --load .

aws-push: aws-build  ## push image lên ECR; từ chối khi còn thay đổi chưa commit (tag phải đúng với code)
	@test -z "$$(git status --porcelain)" || { echo "còn thay đổi chưa commit: tag $(GIT_SHA) sẽ không đúng với image"; exit 1; }
	aws ecr get-login-password | docker login --username AWS --password-stdin $(ECR_HOST)
	docker tag $(IMAGE) $(ECR_REPO):$(GIT_SHA)
	docker push $(ECR_REPO):$(GIT_SHA)

aws-publish-model:  ## sao một version từ registry sang S3 kèm manifest: make aws-publish-model V=4
	@test -n "$(V)" || { echo "thiếu V, vd. make aws-publish-model V=4"; exit 1; }
	uv run python -m geolife.publish --version $(V)

# ---- Terraform: make tf-plan S=foundation ----
# bootstrap giữ state ở local; các stack khác dùng bucket do bootstrap tạo
TF          = terraform -chdir=infra/$(S)
STATE_BUCKET = geolife-$(AWS_ACCOUNT)-tfstate

.PHONY: tf-check tf-init tf-plan tf-apply tf-output

tf-check:
	@test -n "$(S)" -a -d "infra/$(S)" || { echo "thiếu S hoặc infra/$(S) không có, vd. make tf-plan S=foundation"; exit 1; }

tf-init: tf-check   ## terraform init cho một stack
ifeq ($(S),bootstrap)
	$(TF) init
else
	$(TF) init -backend-config="bucket=$(STATE_BUCKET)" -backend-config="region=$(AWS_REGION)"
endif

tf-plan: tf-check   ## xem thay đổi
	$(TF) plan

tf-apply: tf-check  ## áp dụng (Terraform hỏi lại trước khi tạo / sửa)
	$(TF) apply

tf-output: tf-check
	$(TF) output
