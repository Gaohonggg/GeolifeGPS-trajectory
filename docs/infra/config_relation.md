# Cấu hình và quan hệ hạ tầng AWS

Nguồn: [`infra/bootstrap/`](../../infra/bootstrap/), [`infra/foundation/`](../../infra/foundation/) và [`Makefile`](../../Makefile). Các giá trị dưới đây mô tả code đang khai báo, không xác nhận đã triển khai trên AWS.

## 1. Bootstrap, foundation và nơi lưu state

| Stack | Tạo gì? | State lưu ở đâu? |
|---|---|---|
| `bootstrap` | Bucket S3 `geolife-<account_id>-tfstate` | Local: thông thường `infra/bootstrap/terraform.tfstate` |
| `foundation` | Mạng, S3 artifacts, ECR, IAM, ECS cluster, log group, budget | Trong bucket trên, tại `foundation/terraform.tfstate` |

```text
Máy chạy Terraform                              AWS
──────────────────                              ───
bootstrap/main.tf ─────── tạo ────────────────► Bucket S3 chứa state
bootstrap/terraform.tfstate                      geolife-<account_id>-tfstate
  │                                               │
  └─ Ghi nhận bucket và cấu hình                   └─ foundation/terraform.tfstate
     do bootstrap quản lý                            Ghi nhận tài nguyên foundation
```

Bucket được tạo thật trên AWS. “Local” chỉ vị trí state của bootstrap; state là bản ghi liên kết resource trong code với tài nguyên AWS, không phải bản sao nội dung bucket.

| Cấu hình chung | Giá trị |
|---|---|
| Terraform | `>= 1.10` |
| AWS provider | `hashicorp/aws`, `~> 6.0` — từ 6.0 đến dưới 7.0 |
| Backend foundation | S3; `use_lockfile=true`, `encrypt=true` |
| Bucket backend | Makefile truyền lúc `init`: `geolife-<account_id>-tfstate` |
| Default tags | `Project=geolife`; `Stack=bootstrap` hoặc `foundation` |
| Tên dùng chung của foundation | `local.name = "geolife"` |
| Account ID | Đọc tài khoản AWS đang sử dụng qua `aws_caller_identity` |

## 2. Các biến đang cấu hình

| Biến | Giá trị mặc định | Cấu hình gì? |
|---|---|---|
| Terraform `region` | `ap-southeast-1` | Region của AWS provider; có ở cả hai stack |
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

Public subnet có đường ra Internet nhưng không tự gán public IP. Theo thiết kế trong comment, ECS task sau này dùng `assign_public_ip` để đi theo đường này. Private subnet hiện không có đường Internet qua NAT.

## 4. Security group: ai kết nối tới ai?

```text
Người dùng
    │
    │ Rule vào ALB: chưa khai báo trong foundation
    ▼
  [ALB] ───── TCP 8000 ─────► [ECS task] ───── TCP 5432 ─────► [RDS]
                                  │
                                  └─ Cho phép mọi giao thức đi ra IPv4
                                     Đường đi thực tế phụ thuộc route/IP
```

ALB, ECS task và RDS trong sơ đồ là tài nguyên dự kiến. Foundation mới tạo security group cho chúng, chưa tạo ALB, RDS, task definition hay service.

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

Trust policy quyết định **ai được nhận role**; permission policy quyết định **nhận role rồi được làm gì**. Mẫu `rds!*` có thể khớp nhiều secret; foundation chưa tạo secret này. Task definition sau này cần gắn các role bằng ARN.

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
│   └── foundation/terraform.tfstate       Bản ghi quản lý hạ tầng
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
| Lifecycle | `tagStatus=any`, giữ năm image mới nhất theo thời gian push |
| `force_delete` | `true`: cho phép xóa repository còn image |

Immutable tag không ngăn lifecycle xóa image cũ.

## 7. Compute, log và budget

| Tài nguyên / cấu hình | Giá trị | Ý nghĩa |
|---|---|---|
| ECS cluster | `geolife` | Nơi tổ chức task/service; chưa chạy container |
| Container Insights | `disabled` | Tắt tính năng này trên cluster |
| CloudWatch log group | `/ecs/geolife` | Nơi nhận log khi task sau này cấu hình gửi vào |
| Log retention | `14` ngày mặc định | Lấy từ `log_retention_days` |
| Budget | `geolife-monthly`, `COST`, `USD`, `MONTHLY` | Theo dõi chi phí tháng |
| Budget limit | `20` USD mặc định | Lấy từ `monthly_budget_usd` |
| Notifications | Chi phí `ACTUAL` vượt `50%` và `100%` | Với 20 USD là ngưỡng 10 và 20 USD |
| Người nhận | `alert_email` | Nhận email cảnh báo |
| Credit / refund | Cả hai `include_...=false` | Không tính các khoản điều chỉnh này vào budget |
| Budget filter | Không khai báo | Không giới hạn riêng tài nguyên có tag Geolife |

Budget chỉ cảnh báo, không tự dừng tài nguyên. Foundation không tạo NAT/ALB/RDS nhưng lưu trữ, log và thao tác dịch vụ vẫn có thể phát sinh chi phí.

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
                                  Stack data/serving dự kiến
                                  (chưa có trong infra/)
```

| Nhóm | Outputs |
|---|---|
| Tài khoản/vùng | `region`, `account_id` |
| Mạng | `vpc_id`, `public_subnet_ids`, `private_subnet_ids` |
| Security group | `alb_security_group_id`, `task_security_group_id`, `rds_security_group_id` |
| Lưu trữ | `artifacts_bucket`, `ecr_repository_url` |
| IAM | `execution_role_arn`, `task_role_arn` |
| Compute/log | `ecs_cluster_name`, `ecs_cluster_arn`, `log_group_name` |

Comment dự kiến consumer đọc qua `terraform_remote_state`. Outputs không tự tạo consumer hay cấp quyền đọc state.

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
