# Lệnh chạy từ gốc repo.

.PHONY: env test test-all serving-points api

env:            ## tạo .env lần đầu
	@test -f .env || cp .env.example .env

serving-points: ## dựng điểm theo user cho API (data/serving/v_1/) từ data/preprocess/v_1/
	uv run python -m geolife_api.export_points build --version 1

# Mặc định đọc bản dựng ở local; đọc từ S3: make api POINTS_URI=s3://geolife-<account_id>-artifacts/data/serving/v_1
POINTS_URI ?= $(CURDIR)/data/serving/v_1

api: env        ## chạy API ở local (http://localhost:8000); MODEL_URI và Databricks đọc từ .env
	POINTS_URI=$(POINTS_URI) uv run --env-file .env uvicorn --factory geolife_api.main:create_app --port 8000

test:           ## test nhanh
	uv run pytest -m "not slow and not integration"

test-all:       ## thêm parity toàn bộ dữ liệu + test với API đang chạy (API_URL)
	uv run pytest

# ---- AWS ----
# aws CLI, Terraform và boto3 đều đọc hai biến này; đổi bằng `make <lệnh> AWS_PROFILE=...`
export AWS_PROFILE ?= geolife-dev
export AWS_REGION  ?= ap-southeast-1

# Gán bằng `=` để chỉ gọi aws khi lệnh cần tới.
# GNU make 3.81 (bản đi kèm macOS) không truyền biến export vào $(shell), nên profile được truyền tường minh.
AWS_ACCOUNT = $(shell AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text)
ECR_HOST    = $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com
ECR_REPO    = $(ECR_HOST)/geolife-api
GIT_SHA     = $(shell git rev-parse --short=12 HEAD)
IMAGE       = geolife-api:$(GIT_SHA)

.PHONY: aws-whoami aws-build aws-push aws-export-points aws-publish-model aws-promote aws-deploy aws-url aws-smoke \
	aws-pause aws-resume

aws-whoami:     ## tài khoản và user đang dùng
	aws sts get-caller-identity

# Lambda chỉ nhận image một nền tảng: build linux/arm64 (Graviton) thành một manifest, không đính kèm provenance / SBOM.
aws-build:      ## build image của API, tag theo git SHA
	docker buildx build --platform linux/arm64 --provenance=false --sbom=false -f docker/api.Dockerfile -t $(IMAGE) --load .

aws-push: aws-build  ## push image lên ECR; từ chối khi còn thay đổi chưa commit (tag phải đúng với code)
	@test -z "$$(git status --porcelain)" || { echo "còn thay đổi chưa commit: tag $(GIT_SHA) sẽ không đúng với image"; exit 1; }
	aws ecr get-login-password | docker login --username AWS --password-stdin $(ECR_HOST)
	docker tag $(IMAGE) $(ECR_REPO):$(GIT_SHA)
	docker push $(ECR_REPO):$(GIT_SHA)

aws-export-points: serving-points  ## upload data/serving/v_1/ lên S3, manifest ghi sau cùng; đã có thì không ghi gì
	uv run python -m geolife_api.export_points upload --version 1

aws-publish-model:  ## sao một version từ registry sang S3 kèm manifest: make aws-publish-model V=4
	@test -n "$(V)" || { echo "thiếu V, vd. make aws-publish-model V=4"; exit 1; }
	uv run python -m geolife.publish --version $(V)

aws-promote:    ## alias live theo @champion: phát hành lên S3, đóng Lambda version nếu thiếu, apply stack app
	uv run python scripts/promote.py $(ARGS)

# ---- Stack app: function Lambda + HTTP API; không tính tiền khi không có request nên không phải huỷ sau mỗi phiên ----
APP      = terraform -chdir=infra/app
API_URL  = $(shell AWS_PROFILE=$(AWS_PROFILE) $(APP) output -raw url 2>/dev/null)
SMOKE_USER ?= 83
PAUSE_VARS = infra/app/pause.auto.tfvars

aws-deploy:     ## terraform apply stack app theo tfvars hiện có (image mới, đổi cấu hình)
	$(APP) apply

aws-url:        ## URL của HTTP API
	@echo $(API_URL)

aws-smoke:      ## gọi các endpoint qua HTTP API, kiểm mã trả về
	@test -n "$(API_URL)" || { echo "stack app chưa có (make aws-promote)"; exit 1; }
	@fail=0; \
	expect() { want=$$1; shift; code=$$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$$@"); \
		if [ "$$code" = "$$want" ]; then echo "ok   $$code $$*"; else echo "FAIL $$code (cần $$want) $$*"; fail=1; fi; }; \
	expect 200 $(API_URL)/v1/health; \
	expect 200 -X POST $(API_URL)/v1/users/$(SMOKE_USER)/predictions; \
	expect 404 -X POST $(API_URL)/v1/users/999999/predictions; \
	expect 400 -X POST "$(API_URL)/v1/users/$(SMOKE_USER)/predictions?start=hom-qua"; \
	expect 404 $(API_URL)/khong-co; \
	exit $$fail

# Đặt reserved concurrency về 0 bằng aws CLI để có hiệu lực ngay, không qua terraform plan;
# ghi paused vào tfvars để make aws-deploy sau đó không bật lại.
aws-pause:      ## chặn mọi request: reserved concurrency của function về 0
	echo 'paused = true' > $(PAUSE_VARS)
	aws lambda put-function-concurrency --function-name geolife-api --reserved-concurrent-executions 0

aws-resume:     ## bật lại sau aws-pause
	echo 'paused = false' > $(PAUSE_VARS)
	aws lambda put-function-concurrency --function-name geolife-api \
		--reserved-concurrent-executions $$($(APP) output -raw api_reserved_concurrency)

# ---- Terraform: make tf-<lệnh> S=<stack>, vd. make tf-plan S=foundation ----
# bootstrap giữ state ở local; các stack khác lưu state trong bucket do bootstrap tạo.
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
