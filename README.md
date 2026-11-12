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
| `src/geolife/` | Toàn bộ code, theo thứ tự pipeline: `io`, `preprocess`, `timezone`, `calendar`, `models/` (mỗi model một file chứa thuật toán của nó: `stay_point`, `dbscan`; `base` là interface và hợp đồng dữ liệu chung), `home_office`, `confidence`, `evaluation`, `run`; `tuning/` chứa các phép đo khi chọn tham số (`common` dùng chung, mỗi model một file) |
| `EDA/` | Notebook `01`–`05`, chỉ phân tích dữ liệu thô (đọc thẳng file `.plt`). Hình ở `EDA/figures/` |
| `preprocess/v_<n>/` | `config.yaml` + `preprocess.ipynb` (gọi hàm trong `src/geolife/preprocess.py`, in mẫu kiểm tra sau mỗi bước) |
| `models_tuning/<tên>/v_<k>/` | `config.yaml` (tham số + version dữ liệu) + `tuning.ipynb` (cách chọn từng tham số, chạy trên `dev`) |
| `results/data_v<n>/<tên>_v<k>/<split>/` | `predictions.csv`, `metrics.json` của một lần chạy |
| `docs/` | Tài liệu, đọc theo thứ tự bên dưới; `openapi.yaml` là contract của API |
| `src/geolife_api/` | API theo contract `docs/openapi.yaml`: đọc điểm của user từ Postgres, chạy model version nạp từ MLflow registry (`main` là phần HTTP, `service` là logic, `migrate` / `seed` tạo bảng và nạp dữ liệu) |
| `db/migrations/` | Schema Postgres, mỗi file một lần thay đổi, chạy theo thứ tự tên |
| `docker/` | `api.Dockerfile`, `compose.yaml` (Postgres, MLflow, API), `.env.example` |
| `tests/` | `test_parity` (chạy từng user khớp kết quả chạy hàng loạt), `test_mlflow_model`, `api/` (HTTP với DB / model giả), `integration/` (với stack đang chạy) |
| `data/` | Không commit. `Geolife_Trajectories/` là dữ liệu gốc; `preprocess/v_<n>/` là output của từng version preprocess |

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

## Chạy lại

```bash
uv sync
```

```bash
uv run jupyter nbconvert --to notebook --execute --inplace preprocess/v_1/preprocess.ipynb
```

Notebook tuning chọn tham số trên `dev`, ô cuối eval trên `holdout` rồi đăng ký version đó lên MLflow, nên cần MLflow
đang chạy (`make up`, xem phần dưới); version đã đăng ký thì bỏ qua.

```bash
uv run jupyter nbconvert --to notebook --execute --inplace models_tuning/stay_point/v_1/tuning.ipynb
```

Chỉ eval lại trên `holdout`, không chạy lại notebook:

```bash
uv run python -m geolife.run --model stay_point --version 1 --split holdout
```

Các notebook EDA chạy từ thư mục `EDA/` theo cùng cách.

## Chạy API ở local

Cần Docker và `uv`. Lần đầu (tạo `docker/.env`, lên Postgres + MLflow, tạo bảng, nạp 182 user, chạy API):

```bash
make setup
```

MLflow lúc đầu chưa có model: chạy các notebook tuning (phần trên) để đăng ký. Tới lúc đó `/health` báo
`model_loaded: false`; API tự thử nạp lại model mỗi vài giây nên không cần khởi động lại.

```bash
curl -X POST "http://localhost:8000/v1/users/5/predictions?start=2008-11-01T00:00:00Z"
```

- Swagger UI (đúng contract): http://localhost:8000/docs. MLflow UI: http://localhost:5001.
- API serve một model version, chọn bằng `MODEL_URI` trong `docker/.env` (mặc định `models:/geolife_home_office/1`); đổi xong chạy lại `make api`.
- `make test`: test nhanh; `make test-all`: thêm test parity trên toàn bộ dữ liệu và test với stack đang chạy.
- `make down` dừng stack, `make clean` xoá luôn dữ liệu Postgres và MLflow.

Mọi thuật toán chung một registered model `geolife_home_office` trong MLflow; version của registry là thứ tự đăng
ký (hiện tại: 1 = `stay_point` v1, 2 = `stay_point` v2, 3 = `dbscan` v1, 4 = `dbscan` v2), tag `algorithm` và
`config_version` của mỗi version cho biết nó là thuật toán, config nào. Một version chứa code thuật toán và
`config.yaml` của nó, nên image của API không chứa code `geolife`. Thuật toán mới chỉ cần thêm vào `REGISTRY` trong
`src/geolife/models/__init__.py` và có `models_tuning/<tên>/v_<k>/` (notebook kết thúc bằng ô eval + đăng ký như các
version hiện có).

