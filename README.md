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
| `src/geolife/` | Toàn bộ code, theo thứ tự pipeline: `io`, `preprocess`, `timezone`, `calendar`, `stays`, `places`, `home_office`, `models/`, `evaluation`, `run` |
| `EDA/` | Notebook `01`–`05`, chỉ phân tích dữ liệu thô (đọc thẳng file `.plt`). Hình ở `EDA/figures/` |
| `preprocess/v_<n>/` | `config.yaml` + `preprocess.ipynb` (gọi hàm trong `src/geolife/preprocess.py`, in mẫu kiểm tra sau mỗi bước) |
| `models/<tên>/v_<k>/` | `config.yaml` (tham số + version dữ liệu) + `tuning.ipynb` (cách chọn từng tham số, chạy trên `dev`) |
| `results/data_v<n>/<tên>_v<k>/<split>/` | `predictions.csv`, `metrics.json` của một lần chạy |
| `docs/` | Tài liệu, đọc theo thứ tự bên dưới |
| `data/` | Không commit. `Geolife_Trajectories/` là dữ liệu gốc; `preprocess/v_<n>/` là output của từng version preprocess |

**Quản lý version:** preprocess và model đều có version riêng, mỗi version là một thư mục có `config.yaml`. Khi đã có kết quả dựa trên một version thì không
sửa version đó nữa: đổi tham số thì tạo version mới. Config của model ghi `data_version` để biết nó được tuning trên dữ liệu nào.

## Thứ tự đọc

1. [`docs/gps_data_preprocessing.md`](docs/gps_data_preprocessing.md): kiến thức nền về dữ liệu GPS thô.
2. [`docs/eda_findings.md`](docs/eda_findings.md): insight từ EDA trên dữ liệu thô.
3. [`docs/preprocess_v1.md`](docs/preprocess_v1.md): pipeline làm sạch, bằng chứng của từng quy tắc, output.
4. [`docs/evaluation.md`](docs/evaluation.md): chỉ số, cách dùng `dev` / `holdout`, các giả định.
5. [`docs/models/stay_point_v1.md`](docs/models/stay_point_v1.md): model stay_point v1, cách chọn từng tham số, kết quả holdout.

## Chạy lại

```bash
uv sync
```

```bash
uv run jupyter nbconvert --to notebook --execute --inplace preprocess/v_1/preprocess.ipynb
```

```bash
uv run jupyter nbconvert --to notebook --execute --inplace models/stay_point/v_1/tuning.ipynb
```

```bash
uv run python -m geolife.run --model stay_point --version 1 --split holdout
```

Các notebook EDA chạy từ thư mục `EDA/` theo cùng cách.
