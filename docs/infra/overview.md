# Hạ tầng AWS: tổng quan

Trang này chỉ vẽ các khái niệm và quan hệ. Giá trị cấu hình chi tiết (CIDR, quyền IAM, lifecycle…) ở [`config_relation.md`](config_relation.md); số đo RAM / thời gian ở [`../task_sizing.md`](../task_sizing.md).

## 1. Code nằm đâu, chạy ở đâu

Cùng một code Python chạy ở hai nơi; chỉ khác **cái khởi chạy nó**.

```mermaid
flowchart LR
  subgraph repo["Repo"]
    direction TB
    api["src/geolife_api/<br/>main · service · model · db<br/>+ migrate · seed"]
    mig["db/migrations/*.sql"]
    rel["src/geolife/<br/>register · publish"]
    ops["scripts/ecs_run.py"]
    tf["infra/<br/>bootstrap · foundation · data"]
    mk["Makefile"]
  end

  img[["Image geolife-api<br/>(chỉ có geolife_api + migrations)"]]
  api --> img
  mig --> img

  subgraph local["Local (docker compose)"]
    lpg[("Postgres")]
  end
  subgraph aws["AWS"]
    task["ECS task"]
    rds[("RDS")]
  end

  img -->|"make migrate / seed / api"| local
  img -->|"make aws-migrate / aws-seed<br/>qua ecs_run.py"| task --> rds
  rel -->|"chạy trên máy dev"| reg["Registry Databricks"] & s3[("S3 models/")]
  tf -->|"make tf-apply"| aws
  mk -.->|"gọi tất cả"| ops & tf & rel
```

| Thư mục / file | Vai trò | Chạy ở đâu |
| --- | --- | --- |
| `src/geolife_api/` | API (`main`, `service`, `model`, `db`) và hai lệnh DB (`migrate`, `seed`) | Trong image: compose ở local, ECS trên AWS |
| `db/migrations/` | Schema Postgres | Được `migrate` đọc, có trong image |
| `src/geolife/register.py`, `publish.py` | Đăng ký model vào registry; sao version sang S3 | Máy dev (cần code thuật toán + token Databricks) |
| `scripts/ecs_run.py` | Chạy một lệnh bất kỳ của image thành ECS task một lần, in log | Máy dev, điều khiển AWS |
| `infra/<stack>/` | Terraform, mỗi thư mục một stack | Máy dev |
| `Makefile` | Lối vào duy nhất: `make <lệnh>` cho local, `make aws-*` / `make tf-*` cho AWS | Máy dev |

`migrate` và `seed` nằm trong package API vì chúng phải có trong image để chạy được bên trong VPC (RDS không mở ra internet).

## 2. Các stack Terraform

Chia theo **vòng đời và chi phí**. Stack sau đọc output của stack trước qua `terraform_remote_state`.

```mermaid
flowchart TB
  b["bootstrap<br/>bucket tfstate"]
  f["foundation<br/>VPC · SG · S3 artifacts · ECR<br/>IAM role · ECS cluster · log · budget"]
  d["data<br/>RDS · task definition geolife-ops"]
  s["serving (bước 2.2)<br/>ALB · ECS service"]
  b -->|"giữ state của"| f & d & s
  f -->|"output: subnet, SG, role, bucket…"| d
  f --> s
  d -->|"output: DB host, secret"| s
```

| Stack | Tính phí | Vòng đời |
| --- | --- | --- |
| `bootstrap` | ~0 | Tạo một lần; state ở local |
| `foundation` | ~0 | Luôn bật |
| `data` | RDS theo giờ khi chạy | `make aws-db-stop` sau mỗi phiên |
| `serving` | ALB + task theo giờ | Destroy sau mỗi phiên |

## 3. Mạng và ai nói chuyện với ai

```mermaid
flowchart LR
  you(["Bạn"])
  subgraph vpc["VPC 10.20.0.0/16"]
    subgraph pub["Public subnet ×2"]
      alb{{"ALB<br/>(bước 2.2)"}}
      task["ECS task<br/>public IP"]
    end
    subgraph priv["Private subnet ×2 · không ra internet"]
      rds[("RDS :5432")]
    end
  end
  subgraph svc["Dịch vụ AWS (ngoài VPC)"]
    ecr["ECR"]
    s3[("S3 artifacts")]
    sm["Secrets Manager"]
    cw["CloudWatch Logs"]
  end

  you -->|":80, chỉ IP của bạn"| alb -->|":8000"| task -->|":5432"| rds
  task -->|"qua Internet Gateway"| ecr & s3 & cw
  sm -.->|"mật khẩu DB"| task
```

Chuỗi security group: `alb` → `task` → `rds`; mỗi nhóm chỉ nhận từ nhóm đứng trước. Không có NAT: task ra internet bằng public IP của chính nó.

## 4. Một task khởi động như thế nào

Hai role, hai việc khác nhau:

```mermaid
sequenceDiagram
  participant ECS as ECS (execution role)
  participant C as Container (task role)
  participant AWS as ECR · Secrets Manager · S3 · RDS

  ECS->>AWS: kéo image theo digest (ECR)
  ECS->>AWS: đọc secret rds!… lấy password
  ECS->>C: chạy container, tiêm DB_HOST / DB_USER / DB_PASSWORD
  C->>AWS: đọc s3://…/data hoặc /models (quyền task role)
  C->>AWS: kết nối RDS :5432
  C-->>ECS: stdout → CloudWatch Logs /ecs/geolife
```

- **Execution role:** quyền của ECS *trước khi* code chạy (image, secret, log).
- **Task role:** quyền của code *trong* container (S3). Không ghi được `models/`.
- Không có access key nào nằm trong image hay biến môi trường.

## 5. Ba luồng chính

**Phát hành** — chạy trên máy dev, tạo ra thứ bất biến có số version:

```mermaid
flowchart LR
  code["git commit"] -->|"make aws-push"| ecr["ECR<br/>geolife-api:git-sha"]
  nb["notebook tuning"] -->|"geolife.register"| reg["Registry<br/>version N"]
  reg -->|"make aws-publish-model V=N"| s3m[("S3 models/…/v=N/<br/>model/ + manifest.json")]
  alias["alias @champion / @challenger"] -.->|"chọn version"| reg
```

**Nạp dữ liệu** — `make aws-seed`:

```mermaid
flowchart LR
  pq[("S3 data/preprocess/v_1/<br/>points · users.parquet")] --> t["ECS task geolife-ops<br/>python -m geolife_api.seed"] -->|"COPY"| rds[("RDS<br/>users · gps_points")]
  dev["make aws-seed"] -->|"ecs_run.py: run_task + in log"| t
```

**Phục vụ** (bước 2.2) — API nạp model từ S3 lúc khởi động, đọc điểm GPS từ RDS mỗi request.

## 6. Lệnh theo vòng đời

| Khi nào | Lệnh |
| --- | --- |
| Một lần | `make tf-init S=<stack>` → `make tf-apply S=<stack>` (bootstrap → foundation → data) |
| Có code / model mới | `make aws-push`, `make aws-publish-model V=<n>` |
| Lần đầu có RDS | `make aws-migrate`, `make aws-seed` |
| Đầu phiên | `aws login --profile geolife-dev`, `make aws-db-start` |
| Cuối phiên | `make aws-db-stop` |
| Kiểm nhanh | `make aws-whoami`, `make aws-db-count` |
