# GeoLife: phát hiện nơi ở và nơi làm việc từ GPS

Mục tiêu: từ quỹ đạo GPS của bộ [GeoLife Trajectories 1.3](https://www.microsoft.com/en-us/research/publication/geolife-gps-trajectory-dataset-user-guide/), suy ra home và office của từng user kèm confidence. Dataset không có nhãn home/office, nên đánh giá bằng kiểm tra thủ công trên một mẫu cố định trước.

## Cấu trúc repo

| Đường dẫn | Nội dung |
| --- | --- |
| `docs/` | Tài liệu, đọc theo thứ tự ở mục dưới |
| `EDA/` | Notebook EDA `01`–`07`, đọc thẳng file `.plt` gốc. `utils.py` chứa hàm đọc dữ liệu và hàm dùng chung. Hình ở `EDA/figures/` |
| `preprocess/v_*/` | Mỗi version preprocess gồm `config.yaml` và `preprocess.ipynb` (toàn bộ code nằm trong notebook) |
| `data/` | Không commit. `data/Geolife_Trajectories/` là dữ liệu gốc; `data/preprocess/v_*/` là output của từng version |

## Thứ tự đọc

1. [`docs/gps_data_preprocessing.md`](docs/gps_data_preprocessing.md): kiến thức nền về dữ liệu GPS thô (noise, outlier, timezone) và nguyên tắc tiền xử lý.
2. [`docs/eda_findings.md`](docs/eda_findings.md): số liệu và insight từ EDA.
3. [`docs/preprocess_v1.md`](docs/preprocess_v1.md): quy tắc làm sạch, mỗi quy tắc kèm bằng chứng.
4. [`docs/evaluation_protocol.md`](docs/evaluation_protocol.md): định nghĩa home/office, tập đánh giá, chỉ số, confidence và các giả định.

## Chạy lại

```bash
uv sync
```

```bash
uv run jupyter nbconvert --to notebook --execute --inplace preprocess/v_1/preprocess.ipynb
```

Các notebook EDA chạy từ thư mục `EDA/` theo cùng cách.
