# Lệnh chạy từ gốc repo.

.PHONY: env test test-all

env:            ## tạo .env lần đầu
	@test -f .env || cp .env.example .env

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

.PHONY: aws-whoami aws-publish-model aws-promote

aws-whoami:     ## tài khoản và user đang dùng
	aws sts get-caller-identity

aws-publish-model:  ## sao một version từ registry sang S3 kèm manifest: make aws-publish-model V=4
	@test -n "$(V)" || { echo "thiếu V, vd. make aws-publish-model V=4"; exit 1; }
	uv run python -m geolife.publish --version $(V)

aws-promote:    ## đọc @champion / @challenger, phát hành lên S3 version nào chưa có (ARGS=--champion-only)
	uv run python scripts/promote.py $(ARGS)

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
