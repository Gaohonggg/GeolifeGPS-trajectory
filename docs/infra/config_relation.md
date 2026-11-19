# Cấu hình và quan hệ hạ tầng AWS

Nguồn: [`infra/`](../../infra/) (bốn stack `bootstrap`, `foundation`, `data`, `serving`) và [`Makefile`](../../Makefile). Các giá trị dưới đây mô tả code đang khai báo. Sơ đồ tổng quan và các luồng chạy: [`overview.md`](overview.md).

| Mục | Stack |
|---|---|
| 1–2 | Chung: state, provider, biến |
| 3–8 | `foundation`: mạng, security group, IAM, lưu trữ, compute, outputs |
| 9 | `data`: RDS, task `geolife-ops` |
| 10 | `serving`: ALB, hai slot API |
| 11 | Makefile: các lệnh AWS |

## 1. Các stack và nơi lưu state

| Stack | Tạo gì? | State lưu ở đâu? |
|---|---|---|
| `bootstrap` | Bucket S3 `geolife-<account_id>-tfstate` | Local: thông thường `infra/bootstrap/terraform.tfstate` |
| `foundation` | Mạng, S3 artifacts, ECR, IAM, ECS cluster, log group, budget | Trong bucket trên, tại `foundation/terraform.tfstate` |
| `data` | RDS, task definition `geolife-ops` | `data/terraform.tfstate` |
| `serving` | ALB, target group, task definition và ECS service của từng slot | `serving/terraform.tfstate` |

```text
Máy chạy Terraform                              AWS
──────────────────                              ───
bootstrap/main.tf ─────── tạo ────────────────► Bucket S3 chứa state
bootstrap/terraform.tfstate                      geolife-<account_id>-tfstate
  │                                               │
  └─ Ghi nhận bucket và cấu hình                  ├─ foundation/terraform.tfstate
     do bootstrap quản lý                         ├─ data/terraform.tfstate
                                                  └─ serving/terraform.tfstate
```

Bucket được tạo thật trên AWS. “Local” chỉ vị trí state của bootstrap; state là bản ghi liên kết resource trong code với tài nguyên AWS, không phải bản sao nội dung bucket.

| Cấu hình chung | Giá trị |
|---|---|
| Terraform | `>= 1.10` |
| AWS provider | `hashicorp/aws`, `~> 6.0` — từ 6.0 đến dưới 7.0 |
| Backend (trừ bootstrap) | S3; `use_lockfile=true` (khoá state bằng file `.tflock` trong bucket, không cần DynamoDB), `encrypt=true` |
| Bucket backend | Makefile truyền lúc `init`: `geolife-<account_id>-tfstate` |
| Default tags | `Project=geolife`; `Stack=<tên stack>` |
| Tên dùng chung | `local.name = "geolife"` |
| Account ID | Đọc tài khoản AWS đang sử dụng qua `aws_caller_identity` |

## 2. Các biến chung và của foundation

| Biến | Giá trị mặc định | Cấu hình gì? |
|---|---|---|
| Terraform `region` | `ap-southeast-1` | Region của AWS provider; có ở mọi stack |
| `alert_email` | Phải cung cấp | Email nhận cảnh báo ngân sách foundation |
| `monthly_budget_usd` | `20` | Ngân sách tháng, đơn vị USD |
| `vpc_cidr` | `10.20.0.0/16` | Dải IP của VPC và cơ sở chia subnet |
| `log_retention_days` | `14` | Số ngày giữ log trong CloudWatch |
| Makefile `AWS_PROFILE` | `geolife-dev` | Profile AWS dùng khi chạy các lệnh qua Makefile |
| Makefile `AWS_REGION` | `ap-southeast-1` | Region môi trường và region backend được truyền lúc init |

`terraform.tfvars.example` là mẫu cung cấp `alert_email`; Terraform không tự nạp file `.example`. `var.region` của provider và region backend truyền từ Makefile là hai cấu hình riêng; khi đổi region cần kiểm tra cả hai.

## 3. Mạng: VPC, subnet và route

Nguồn: [`network.tf`](../../infra/foundation/network.tf).

```text
VPC: 10.20.0.0/16
├── AZ thứ nhất: local.azs[0]
│   ├── Public:  10.20.0.0/24
│   └── Private: 10.20.10.0/24
└── AZ thứ hai: local.azs[1]
    ├── Public:  10.20.1.0/24
    └── Private: 10.20.11.0/24
```

Code lấy hai AZ khả dụng đầu tiên. Các CIDR trên dùng giá trị `vpc_cidr` mặc định.

| Cấu hình | Giá trị / quan hệ |
|---|---|
| DNS support / hostnames | Cả hai bật |
| Public subnet | `count=2`; `cidrsubnet(var.vpc_cidr, 8, count.index)` |
| Private subnet | `count=2`; `cidrsubnet(var.vpc_cidr, 8, 10 + count.index)` |
| Internet Gateway | Gắn vào VPC |
| Public route table | Route nội bộ VPC và `0.0.0.0/0 → Internet Gateway` |
| Public route associations | Hai public subnet dùng chung public route table |
| Private subnet | Dùng main route table; theo cấu hình hiện tại chỉ có route nội bộ |
| Tự gán public IP | `map_public_ip_on_launch=false` |
| NAT Gateway | Không khai báo |

```text
Máy trong public subnet muốn gửi dữ liệu
                 │
          Xem route table
                 │
       ┌─────────┴──────────┐
       ▼                    ▼
Đến IP trong VPC       Đến IP ngoài VPC
Ví dụ: database       Ví dụ: public endpoint AWS
       │                    │
Đi trong mạng nội bộ   Qua Internet Gateway
                            │
                     Cần public IPv4 phù hợp
                     và security group cho phép
```

Public subnet có đường ra Internet nhưng không tự gán public IP. ECS task (service API và task `geolife-ops`) xin public IP bằng `assign_public_ip` để đi theo đường này. Private subnet không có đường Internet.

## 4. Security group: ai kết nối tới ai?

```text
Người dùng
    │
    │ TCP 80 từ allowed_cidr: rule nằm ở stack serving
    ▼
  [ALB] ───── TCP 8000 ─────► [ECS task] ───── TCP 5432 ─────► [RDS]
                                  │
                                  └─ Cho phép mọi giao thức đi ra IPv4
                                     Đường đi thực tế phụ thuộc route/IP
```

Foundation tạo security group và các rule nội bộ. Rule vào ALB nằm ở stack `serving` vì nguồn được phép (IP của máy chạy `make aws-up`) đổi theo mạng; RDS gắn SG `rds` ở stack `data`.

| Rule | Nhóm áp dụng | Hướng | Nguồn / đích | Cho phép |
|---|---|---|---|---|
| `alb_to_task` | ALB SG | Ra | Đến task SG | TCP `8000` |
| `task_from_alb` | Task SG | Vào | Từ ALB SG | TCP `8000` |
| `task_all` | Task SG | Ra | Đến `0.0.0.0/0` | Mọi giao thức (`-1`) |
| `rds_from_task` | RDS SG | Vào | Từ task SG | TCP `5432` |

Rule tham chiếu SG nhận diện nguồn/đích theo nhóm, không hardcode IP. Không có rule vào task trực tiếp từ Internet. Security group có trạng thái nên lưu lượng phản hồi của kết nối được phép không cần mở cổng ngược riêng.

## 5. IAM: ai có quyền làm gì?

Nguồn: [`iam.tf`](../../infra/foundation/iam.tf).

```text
Hạ tầng ECS                          Code bên trong container
     │                                         │
     ▼                                         ▼
Execution role                            Task role
geolife-ecs-execution                      geolife-ecs-task
     │                                         │
     ├─ Kéo image ECR                          ├─ Đọc data/, models/, monitoring/
     ├─ Gửi log CloudWatch                     └─ Ghi monitoring/, exports/
     └─ Đọc RDS secret để tiêm vào container
```

| Cấu hình | Giá trị / ý nghĩa |
|---|---|
| Bên được nhận hai role | Service `ecs-tasks.amazonaws.com` |
| Trust action | `sts:AssumeRole` |
| Trust condition | `aws:SourceAccount` phải bằng account hiện tại |
| Execution managed policy | `AmazonECSTaskExecutionRolePolicy` do AWS quản lý |
| Execution inline policy | `secretsmanager:GetSecretValue` |
| Phạm vi secret | `arn:aws:secretsmanager:<region>:<account_id>:secret:rds!*` |
| Task inline policy | `ListBucket`, `GetObject`, `PutObject` theo prefix bên dưới |

Trust policy quyết định **ai được nhận role**; permission policy quyết định **nhận role rồi được làm gì**. Secret `rds!…` do RDS tạo khi bật `manage_master_user_password` (stack `data`); foundation dùng mẫu `rds!*` vì tên secret chỉ có sau khi RDS được tạo. Mọi task definition (stack `data` và `serving`) gắn hai role này bằng ARN.

**Ma trận quyền S3 của task role:**

| Prefix trong bucket artifacts | List theo prefix | Đọc object | Ghi object | Xóa object |
|---|---|---|---|---|
| `data/` | Có | Có | Không cấp | Không cấp |
| `models/` | Có | Có | Không cấp | Không cấp |
| `monitoring/` | Có | Có | Có | Không cấp |
| `exports/` | Không cấp | Không cấp | Có | Không cấp |
| Prefix khác | Không cấp | Không cấp | Không cấp | Không cấp |

List áp dụng trên bucket ARN, có điều kiện `s3:prefix`; đọc/ghi áp dụng trên object ARN. “Không cấp” là không có Allow trong policy này, không phải Explicit Deny. Quyền hiệu lực còn phụ thuộc các policy/giới hạn khác trên AWS.

Danh tính chạy Terraform/push image/publish model là credentials bên ngoài hai role trên; foundation không khai báo đầy đủ quyền của người triển khai. Task role không được policy này cấp quyền publish vào `models/`.

## 6. Lưu trữ: state, artifacts và image

Nguồn: [`bootstrap/main.tf`](../../infra/bootstrap/main.tf), [`storage.tf`](../../infra/foundation/storage.tf).

```text
AWS
├── S3: geolife-<account_id>-tfstate
│   └── <stack>/terraform.tfstate          State của foundation, data, serving
├── S3: geolife-<account_id>-artifacts
│   ├── data/preprocess/                   Dữ liệu đã xử lý
│   ├── models/<model>/v=<n>/              Model và manifest
│   ├── monitoring/                        Dữ liệu theo dõi
│   └── exports/                           Kết quả xuất
└── ECR: geolife-api                        Docker image API
    └── Tag theo Git SHA                   Quy ước trong Makefile
```

Các prefix artifacts là quy ước sử dụng; Terraform không upload dữ liệu hoặc tạo sẵn object.

| Cấu hình S3 | Bucket state | Bucket artifacts |
|---|---|---|
| Versioning | Bật | Bật |
| Chặn public | Cả bốn cờ bật | Cả bốn cờ bật |
| Mã hóa mặc định | `AES256` / SSE-S3 | `AES256` / SSE-S3 |
| Policy bắt buộc TLS | Không khai báo policy riêng trong bootstrap | Deny `s3:*` khi `aws:SecureTransport=false` |
| Xóa noncurrent versions | Sau 90 ngày không còn hiện hành | Sau 30 ngày không còn hiện hành, mọi prefix |
| Dọn multipart upload dở dang | Không khai báo | Sau 7 ngày |
| Expiration bản hiện hành | Không khai báo | `exports/`: 90 ngày |

Versioning không đồng nghĩa bất biến. Bản hiện hành dưới `models/` không có expiration rule, nhưng phiên bản cũ vẫn chịu rule noncurrent 30 ngày. Với bucket versioning, expiration thường tạo delete marker; không phải xóa vĩnh viễn ngay mọi phiên bản. [`publish.py`](../../src/geolife/publish.py) kiểm tra nội dung và ghi manifest sau cùng khi phát hành model.

| Cấu hình ECR | Giá trị / ý nghĩa |
|---|---|
| Repository | `geolife-api` |
| Image tags | `IMMUTABLE`: không ghi đè tag đã tồn tại |
| Scan on push | `true` |
| Lifecycle | Giữ 5 image có tag mới nhất; manifest không tag bị xoá sau 7 ngày |
| `force_delete` | `true`: cho phép xóa repository còn image |

Immutable tag không ngăn lifecycle xóa image cũ.

## 7. Compute, log và budget

| Tài nguyên / cấu hình | Giá trị | Ý nghĩa |
|---|---|---|
| ECS cluster | `geolife` | Nơi chạy service API và task `geolife-ops` |
| Container Insights | `disabled` | Tắt tính năng này trên cluster |
| CloudWatch log group | `/ecs/geolife` | Log của mọi task; stream prefix `ops` hoặc `api-<slot>` |
| Log retention | `14` ngày mặc định | Lấy từ `log_retention_days` |
| Budget | `geolife-monthly`, `COST`, `USD`, `MONTHLY` | Theo dõi chi phí tháng |
| Budget limit | `20` USD mặc định | Lấy từ `monthly_budget_usd` |
| Notifications | Chi phí `ACTUAL` vượt `50%` và `100%` | Với 20 USD là ngưỡng 10 và 20 USD |
| Người nhận | `alert_email` | Nhận email cảnh báo |
| Credit / refund | Cả hai `include_...=false` | Không tính các khoản điều chỉnh này vào budget |
| Budget filter | Không khai báo | Không giới hạn riêng tài nguyên có tag Geolife |

Budget chỉ cảnh báo, không tự dừng tài nguyên; số liệu chi phí trễ khoảng một ngày. Phần tốn tiền chính nằm ở stack `data` (RDS) và `serving` (ALB, task).

## 8. Outputs: foundation đưa gì cho stack tiếp theo?

Nguồn: [`outputs.tf`](../../infra/foundation/outputs.tf).

```text
Foundation
    │
    ├─ VPC/subnet/security group IDs ───► Chọn mạng và luồng kết nối
    ├─ Bucket/ECR URL ─────────────────► Chọn dữ liệu, model và image
    ├─ Execution/task role ARNs ───────► Gắn quyền cho ECS task
    └─ Cluster/log group ──────────────► Chọn nơi chạy và nơi gửi log
                                            │
                                  Stack data (infra/data)
                                  và serving (infra/serving)
```

| Nhóm | Outputs |
|---|---|
| Tài khoản/vùng | `region`, `account_id` |
| Mạng | `vpc_id`, `public_subnet_ids`, `private_subnet_ids` |
| Security group | `alb_security_group_id`, `task_security_group_id`, `rds_security_group_id` |
| Lưu trữ | `artifacts_bucket`, `ecr_repository_url` |
| IAM | `execution_role_arn`, `task_role_arn` |
| Compute/log | `ecs_cluster_name`, `ecs_cluster_arn`, `log_group_name` |

Stack `data` và `serving` đọc các output này qua `terraform_remote_state`; người chạy Terraform cần quyền đọc bucket state.

```text
Muốn ứng dụng đọc được model trên S3
                 │
       ┌─────────┴──────────┐
       ▼                    ▼
Có đường mạng tới S3    Có quyền GetObject
Route + IP + SG         Task role + bucket policy
       │                    │
       └─────────┬──────────┘
                 ▼
       Đọc object model qua SDK
```

## 9. Stack data: RDS và task `geolife-ops`

Nguồn: [`rds.tf`](../../infra/data/rds.tf), [`ops_task.tf`](../../infra/data/ops_task.tf), [`variables.tf`](../../infra/data/variables.tf).

```text
foundation outputs ──► data
  private_subnet_ids      ├─ aws_db_subnet_group "geolife" (2 private subnet)
  rds_security_group_id   ├─ aws_db_instance "geolife" ──► secret rds!… (Secrets Manager, RDS tự tạo)
  execution/task role     └─ aws_ecs_task_definition "geolife-ops"
  ecr_repository_url           image ghim theo digest, DB_* lấy từ aws_db_instance
```

**RDS** (`aws_db_instance.main`):

| Cấu hình | Giá trị | Ghi chú |
|---|---|---|
| Engine | PostgreSQL `17` | Cùng major với `postgres:17` ở local; minor do AWS chọn và tự nâng (`auto_minor_version_upgrade`) |
| Instance | `db.t4g.micro` (`db_instance_class`) | 2 vCPU burstable, 1 GB RAM |
| Ổ đĩa | gp3 `20` GB (`db_allocated_storage_gb`), mã hoá | gp3 dưới 400 GB: 3 000 IOPS, 125 MB/s cố định |
| DB / user | `geolife` / `geolife` | |
| Mật khẩu | `manage_master_user_password = true` | RDS sinh và lưu trong Secrets Manager; không nằm trong state |
| Mạng | Subnet group 2 private subnet, SG `rds`, `publicly_accessible = false`, `multi_az = false` | Chỉ task trong VPC kết nối được |
| Backup | `backup_retention_period = 1`, `skip_final_snapshot = true`, `deletion_protection = false` | Dữ liệu dựng lại được từ S3 bằng `make aws-seed` |
| Áp dụng thay đổi | `apply_immediately = true` | Không chờ maintenance window |
| Theo dõi | Performance Insights và Enhanced Monitoring tắt | Chỉ dùng metric cơ bản trong CloudWatch |
| Parameter group | `geolife` (family `postgres17`): `random_page_cost = 1.1` | Ổ gp3 là SSD; mặc định 4 giả định ổ quay ([`task_sizing.md`](../task_sizing.md) B5). Đổi parameter group chỉ có hiệu lực sau reboot hoặc stop / start |

RDS đang stop vẫn tính phí ổ đĩa; AWS tự start lại một instance đã stop quá 7 ngày.

**Task definition `geolife-ops`** (lệnh chạy một lần trong VPC: migrate, seed, kiểm tra DB):

| Cấu hình | Giá trị |
|---|---|
| CPU / RAM | 1 vCPU / 2 GB; `ecs_run.py --memory` đổi RAM cho riêng một lần chạy |
| Kiến trúc | Fargate, Linux ARM64 |
| Image | `geolife-api` ghim theo digest; `image_tag = null` lấy image mới nhất trong ECR |
| Lệnh mặc định | `python -m geolife_api.migrate`; `ecs_run.py` ghi đè bằng command override |
| Biến môi trường | `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `AWS_REGION` |
| Secret | `DB_PASSWORD` = khoá `password` của secret `rds!…` |
| Log | `/ecs/geolife`, stream `ops/ops/<task id>` |

Image được ghim lúc `terraform apply`, nên sau `make aws-push` cần apply lại stack `data` để task `geolife-ops` dùng image mới.

| Output | Dùng bởi |
|---|---|
| `db_host`, `db_port`, `db_name`, `db_user`, `db_secret_arn` | Stack `serving` (biến môi trường và secret của task API) |
| `db_identifier` | Tham khảo; Makefile dùng `DB_ID = geolife` |
| `ops_task_definition_arn`, `ops_image` | `scripts/ecs_run.py` |

## 10. Stack serving: ALB và hai slot API

Nguồn: [`infra/serving/`](../../infra/serving/).

```text
models.auto.tfvars.json ──► local.active_slots (slot có version)
  blue_model_version          ├─ aws_ecs_task_definition "geolife-api-<slot>"   MODEL_URI = s3://…/v=<N>/model
  green_model_version         └─ aws_ecs_service "api-<slot>" ──► target group "geolife-api-<slot>"
  live_slot, canary_weight ──► local.weights ──► listener :80 (forward có trọng số)
                                 local.other_slot ──► rule X-Canary: 1
```

**Biến** ([`variables.tf`](../../infra/serving/variables.tf)):

| Biến | Mặc định | Ai đặt |
|---|---|---|
| `allowed_cidr` | Bắt buộc | `make aws-up` truyền IP công khai của máy (`/32`) |
| `blue_model_version`, `green_model_version` | `null` (slot không chạy) | `make aws-promote` ghi vào `models.auto.tfvars.json` |
| `live_slot` | `blue` | Như trên |
| `canary_weight` | `0` (0–100) | Như trên; sửa tay để tăng dần canary |
| `image_tag` | `null` (image mới nhất trong ECR) | Truyền `-var` khi cần chạy một build cụ thể |
| `model_name` | `geolife_home_office` | Thư mục dưới `models/` trên S3 |
| `api_cpu` / `api_memory` | `512` / `2048` | 0,5 vCPU / 2 GB theo [`task_sizing.md`](../task_sizing.md) B3 |

Terraform tự nạp file `*.auto.tfvars.json` trong thư mục stack, nên không cần `-var-file`.

**ALB** ([`alb.tf`](../../infra/serving/alb.tf)):

| Tài nguyên | Cấu hình |
|---|---|
| Rule vào SG `alb` | TCP 80 từ `allowed_cidr` |
| `aws_lb.api` | `geolife-api`, application, internet-facing, 2 public subnet, `idle_timeout = 60` giây |
| Target group `geolife-api-blue` / `-green` | HTTP 8000, `target_type = ip` (bắt buộc với Fargate `awsvpc`), `deregistration_delay = 30` giây |
| Health check | `GET /v1/health` cần `200`; mỗi 15 giây, timeout 5 giây; 2 lần đạt thì khoẻ, 3 lần trượt thì không khoẻ |
| Listener :80 | Forward tới hai target group, trọng số `local.weights` (live slot `100 − canary_weight`, slot còn lại `canary_weight`) |
| Rule `canary_header` (priority 10) | Header `X-Canary: 1` → target group của `other_slot` |

`/v1/health` trả `503` khi model chưa nạp xong hoặc DB không kết nối được, nên ALB không gửi request tới task chưa sẵn sàng. Request chạy quá `idle_timeout` bị ALB cắt với `504`.

**Task definition và service của mỗi slot** ([`ecs.tf`](../../infra/serving/ecs.tf)):

| Cấu hình | Giá trị |
|---|---|
| Kiến trúc | Fargate, Linux ARM64 |
| Image | `geolife-api` ghim theo digest (như `geolife-ops`) |
| Biến môi trường | `MODEL_URI` (bản phát hành trên S3, task không gọi registry), `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `AWS_REGION` |
| Secret | `DB_PASSWORD` = khoá `password` của secret `rds!…` |
| Log | `/ecs/geolife`, stream prefix `api-<slot>` |
| `desired_count` | `1` |
| Mạng | 2 public subnet, SG `task`, `assign_public_ip = true` |
| `health_check_grace_period_seconds` | `120`: bỏ qua health check của ALB khi task đang tải model và chạy thử |
| Rolling update | `minimum_healthy_percent = 100`, `maximum_percent = 200`: task mới khoẻ rồi mới dừng task cũ |
| Circuit breaker | Bật, `rollback = true`: deploy không lên được thì quay về task definition trước |
| `wait_for_steady_state` | `true`: `terraform apply` chỉ xong khi service ổn định |

| Output | Ý nghĩa |
|---|---|
| `url` | `http://<DNS của ALB>`; `make aws-url` in giá trị này |
| `image` | Image (theo digest) đang chạy |
| `slots` | Mỗi slot: `model_version`, `weight`, `live` |

## 11. Makefile: các lệnh AWS

Nguồn: [`Makefile`](../../Makefile), phần `# ---- AWS ----`.

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `AWS_PROFILE` | `geolife-dev` (export) | aws CLI, Terraform, boto3 đều đọc; đổi bằng `make <lệnh> AWS_PROFILE=...` |
| `AWS_REGION` | `ap-southeast-1` (export) | |
| `AWS_ACCOUNT` | `aws sts get-caller-identity` | Gán bằng `=`: chỉ gọi khi lệnh cần |
| `ECR_REPO` | `<account>.dkr.ecr.<region>.amazonaws.com/geolife-api` | |
| `IMAGE` | `geolife-api:<git SHA 12 ký tự>` | |
| `ARTIFACTS_BUCKET`, `STATE_BUCKET` | `geolife-<account>-artifacts`, `geolife-<account>-tfstate` | |
| `MY_CIDR` | IP công khai từ `checkip.amazonaws.com` + `/32` | Nguồn duy nhất được gọi ALB |
| `DB_ID` | `geolife` | Identifier của RDS |

GNU make 3.81 (bản đi kèm macOS) không truyền biến `export` vào `$(shell …)`, nên các biến gọi lệnh AWS truyền `AWS_PROFILE` tường minh.

| Nhóm | Lệnh | Việc làm |
|---|---|---|
| Image, model | `aws-build`, `aws-push` | Build `linux/arm64` (không đính kèm provenance / SBOM), push lên ECR; từ chối khi còn thay đổi chưa commit |
| | `aws-publish-model V=<n>` | Sao version `n` từ registry sang S3 kèm manifest |
| | `aws-promote` | Đọc alias, phát hành nếu thiếu, ghi `models.auto.tfvars.json` (`ARGS=--champion-only`) |
| DB | `aws-migrate`, `aws-seed`, `aws-db-count` | Chạy trong task `geolife-ops` qua `ecs_run.py` (`MEMORY=<MB>` đổi RAM) |
| | `aws-db-start`, `aws-db-stop` | Start / stop RDS và chờ tới trạng thái đích; bỏ qua nếu đã ở trạng thái đó |
| Serving | `aws-up` | `aws-db-start`, rồi `terraform apply` stack `serving` với `allowed_cidr = MY_CIDR` |
| | `aws-down` | `terraform destroy` stack `serving`, rồi `aws-db-stop` (tắt service trước để task không bị thay liên tục khi mất DB) |
| | `aws-url`, `aws-smoke` | In URL; gọi `/v1/health`, một user có dữ liệu, một user không có, một đường dẫn không có, kiểm mã trả về |
| Terraform | `tf-init`, `tf-plan`, `tf-apply`, `tf-output` với `S=<stack>` | `tf-init` truyền bucket backend (trừ `bootstrap`) |
