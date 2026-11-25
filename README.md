# GeoLife: phát hiện nơi ở và nơi làm việc từ GPS

Từ quỹ đạo GPS của bộ [GeoLife Trajectories 1.3](https://www.microsoft.com/en-us/research/publication/geolife-gps-trajectory-dataset-user-guide/), suy ra home và office của từng user. Dataset không có nhãn home/office.

## Pipeline

```
.plt thô ──► EDA (chỉ dữ liệu thô) ──► preprocess v_n ──► model <tên> v_k ──► stay ──► place ──► home / office
                                         (làm sạch, chia      (tham số chọn bằng
                                          dev / holdout)        tuning trên dev)
```

## Cấu trúc repo

| Đường dẫn | Nội dung |
| --- | --- |
| `src/geolife/` | Code thuật toán và công cụ phát hành model (`register` vào registry, `publish` sang S3), theo thứ tự pipeline: `io`, `preprocess`, `timezone`, `calendar`, `models/` (mỗi model một file chứa thuật toán của nó: `stay_point`, `dbscan`; `base` là interface và hợp đồng dữ liệu chung), `home_office`, `confidence`, `evaluation`, `run`; `tuning/` chứa các phép đo khi chọn tham số (`common` dùng chung, mỗi model một file) |
| `EDA/` | Notebook `01`–`05`, chỉ phân tích dữ liệu thô (đọc thẳng file `.plt`). Hình ở `EDA/figures/` |
| `preprocess/v_<n>/` | `config.yaml` + `preprocess.ipynb` (gọi hàm trong `src/geolife/preprocess.py`, in mẫu kiểm tra sau mỗi bước) |
| `models_tuning/<tên>/v_<k>/` | `config.yaml` (tham số + version dữ liệu) + `tuning.ipynb` (cách chọn từng tham số, chạy trên `dev`) |
| `results/data_v<n>/<tên>_v<k>/<split>/` | `predictions.csv`, `metrics.json` của một lần chạy |
| `docs/` | Tài liệu, đọc theo thứ tự bên dưới; `openapi.yaml` là contract của API |
| `src/geolife_api/` | API theo contract `docs/openapi.yaml`: đọc điểm của user qua một nguồn điểm (`service.PointStore`, hiện thực là `points.S3PointStore` trên S3 hoặc thư mục local), chạy model version nạp từ MLflow registry trên Databricks hoặc bản phát hành trên S3 (`main` là phần HTTP, `service` là logic). `export_points` dựng điểm theo user cho API và upload lên S3; `lambda_handlers` là handler trên AWS Lambda (event của API Gateway → app FastAPI qua Mangum) |
| `docker/` | `api.Dockerfile`: image của API trên Lambda (`linux/arm64`, chỉ chứa `geolife_api`) |
| `scripts/` | `promote.py`: đổi alias `@champion` / `@challenger` trên registry thành số model version, phát hành lên S3 version nào chưa có; `measure_lambda_memory.py`: đo RAM / thời gian của image dưới giới hạn của một function |
| `infra/` | Terraform, mỗi thư mục một stack: `bootstrap` (bucket state), `foundation` (bucket artifacts, ECR, budget) |
| `.env.example` | Biến môi trường ở local (token Databricks, MLflow); `make env` copy thành `.env` (không commit) |
| `tests/` | `test_parity` (chạy từng user, đọc từ `points.parquet` và từ bản dựng cho API, khớp kết quả chạy hàng loạt), `test_mlflow_model`, `test_publish`, `test_export_points`, `api/` (HTTP với nguồn điểm / model giả; handler Lambda với event mẫu của API Gateway; `S3PointStore`), `integration/` (với API đang chạy, theo `API_URL`) |
| `data/` | Không commit. `Geolife_Trajectories/` là dữ liệu gốc; `preprocess/v_<n>/` là output của từng version preprocess; `serving/v_<n>/` là điểm theo user cho API, dựng từ `preprocess/v_<n>/` |

**Quản lý version:** preprocess và model đều có version riêng, mỗi version là một thư mục có `config.yaml`. Khi đã có kết quả dựa trên một version thì không
sửa version đó nữa: đổi tham số thì tạo version mới. Config của model ghi `data_version` để biết nó được tuning trên dữ liệu nào.

## Thứ tự đọc

1. [`docs/gps_data_preprocessing.md`](docs/gps_data_preprocessing.md): kiến thức nền về dữ liệu GPS thô.
2. [`docs/eda_findings.md`](docs/eda_findings.md): insight từ EDA trên dữ liệu thô.
3. [`docs/preprocess_v1.md`](docs/preprocess_v1.md): pipeline làm sạch, bằng chứng của từng quy tắc, output.
4. [`docs/evaluation.md`](docs/evaluation.md): chỉ số, cách dùng `dev` / `holdout`, các giả định.
5. [`docs/models/stay_point_v1.md`](docs/models/stay_point_v1.md): model stay_point v1 (neo cố định ở điểm đầu), cách chọn từng tham số, kết quả holdout.
6. [`docs/models/stay_point_v2.md`](docs/models/stay_point_v2.md): model stay_point v2 (neo động: tâm các điểm đã nhận), cùng quy trình chọn tham số với v1.
7. [`docs/confidence.md`](docs/confidence.md): confidence của từng dự đoán home / office (lấy mẫu lại theo tuần), ví dụ cách tính.
8. [`docs/models/dbscan_v1.md`](docs/models/dbscan_v1.md): model dbscan v1 (DBSCAN trên ô lưới, trọng số thời gian, mỗi cụm là một place; toạ độ ô = tâm hình học), cách chọn từng tham số, kết quả holdout.
9. [`docs/models/dbscan_v2.md`](docs/models/dbscan_v2.md): model dbscan v2 (toạ độ ô = trung bình có trọng số thời gian của các điểm trong ô), cùng quy trình chọn tham số với dbscan v1.
10. [`docs/infra/fargate/`](docs/infra/fargate/overview.md): phương án triển khai bằng ECS Fargate + RDS (code ở nhánh `fargate`): hạ tầng qua sơ đồ, giá trị cấu hình của từng stack ([`config_relation.md`](docs/infra/fargate/config_relation.md)), kiến thức nền ([`knowledges.md`](docs/infra/fargate/knowledges.md)), số đo RAM và thời gian để chọn cỡ task ([`task_sizing.md`](docs/infra/fargate/task_sizing.md)).
11. [`docs/infra/lambda/serving_data.md`](docs/infra/lambda/serving_data.md): phương án AWS Lambda (nhánh `main`), dữ liệu điểm cho API: bố cục mỗi user một file parquet trên S3, cách dựng / upload, cách API đọc, số byte và số GET mỗi request.
12. [`docs/infra/lambda/request_flow.md`](docs/infra/lambda/request_flow.md): một request đi qua API Gateway, Lambda, handler (Mangum) và FastAPI, từng khâu nhận gì và trả gì.
13. [`docs/infra/lambda/sizing.md`](docs/infra/lambda/sizing.md): số đo RAM và thời gian của image để chọn RAM cho function.

## Chạy lại

```bash
uv sync
```

```bash
uv run jupyter nbconvert --to notebook --execute --inplace preprocess/v_1/preprocess.ipynb
```

Notebook tuning chọn tham số trên `dev`, ô cuối eval trên `holdout` rồi đăng ký version đó lên MLflow trên Databricks
(cần các biến Databricks / MLflow trong `.env`, xem phần dưới); version đã đăng ký thì bỏ qua.

```bash
uv run jupyter nbconvert --to notebook --execute --inplace models_tuning/stay_point/v_1/tuning.ipynb
```

Chỉ eval lại trên `holdout`, không chạy lại notebook:

```bash
uv run python -m geolife.run --model stay_point --version 1 --split holdout
```

Các notebook EDA chạy từ thư mục `EDA/` theo cùng cách.

## Model registry

Cần `uv` và một workspace Databricks có Unity Catalog (Free Edition đủ dùng). Điền `.env` theo `.env.example`
(`make env`): host và personal access token của workspace, đường dẫn experiment, tên model `catalog.schema.model`
(schema phải có sẵn). Các notebook tuning đăng ký model vào registry; `make test` chạy test nhanh, `make test-all`
thêm test parity trên toàn bộ dữ liệu và test với API đang chạy (`API_URL`).

Mọi thuật toán chung một registered model (`MLFLOW_MODEL_NAME`, vd. `workspace.geolife.geolife_home_office`) trong
Unity Catalog; version của registry là thứ tự đăng
ký (hiện tại: 1 = `stay_point` v1, 2 = `stay_point` v2, 3 = `dbscan` v1, 4 = `dbscan` v2), tag `algorithm` và
`config_version` của mỗi version cho biết nó là thuật toán, config nào. Một version chứa code thuật toán và
`config.yaml` của nó cùng signature (cột và kiểu của input / output), nên image của API không chứa code `geolife`. Thuật toán mới chỉ cần thêm vào `REGISTRY` trong
`src/geolife/models/__init__.py` và có `models_tuning/<tên>/v_<k>/` (notebook kết thúc bằng ô eval + đăng ký như các
version hiện có).


## API ở local

Dựng điểm theo user cho API từ `data/preprocess/v_1/` (ghi vào `data/serving/v_1/`), rồi chạy API ở
`http://localhost:8000` (`MODEL_URI` và biến Databricks đọc từ `.env`):

```bash
make serving-points
```

```bash
make api
```

`make aws-export-points` upload bản dựng lên `s3://geolife-<account_id>-artifacts/data/serving/v_1/`; chi tiết ở
[`docs/infra/lambda/serving_data.md`](docs/infra/lambda/serving_data.md).

## Image của API

```bash
make aws-build
```

```bash
make aws-push
```

`aws-build` build `docker/api.Dockerfile` cho `linux/arm64`, tag theo git SHA; `aws-push` đẩy lên ECR và từ chối khi
còn thay đổi chưa commit. Image chạy handler `geolife_api.lambda_handlers.api`
([`docs/infra/lambda/request_flow.md`](docs/infra/lambda/request_flow.md)).
