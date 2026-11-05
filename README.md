# GeoLife: phát hiện nơi ở và nơi làm việc từ GPS

Mục tiêu: từ quỹ đạo GPS của bộ [GeoLife Trajectories 1.3](https://www.microsoft.com/en-us/research/publication/geolife-gps-trajectory-dataset-user-guide/), suy ra home và office của từng user. Dataset không có nhãn home/office.

> **Đang tái cấu trúc.** Model, evaluation và các doc của preprocess/model đã được gỡ để viết lại theo plan mới. Bản cũ được lưu ở `data/_archive/pre_cleanup_2026-11-05.tar.gz` (không commit).

## Cấu trúc repo

| Đường dẫn | Nội dung |
| --- | --- |
| `docs/` | `gps_data_preprocessing.md` (kiến thức nền), `eda_findings.md` (insight EDA trên dữ liệu thô) |
| `EDA/` | Notebook `01`–`05`, chỉ phân tích dữ liệu thô (đọc thẳng file `.plt`). `utils.py` chứa hàm đọc dữ liệu. Hình ở `EDA/figures/` |
| `preprocess/v_*/` | Mỗi version preprocess gồm `config.yaml` và `preprocess.ipynb` |
| `data/` | Không commit. `Geolife_Trajectories/` là dữ liệu gốc; `preprocess/v_*/` là output của từng version |

## Chạy lại

```bash
uv sync
```

```bash
uv run jupyter nbconvert --to notebook --execute --inplace preprocess/v_1/preprocess.ipynb
```

Các notebook EDA chạy từ thư mục `EDA/` theo cùng cách.
