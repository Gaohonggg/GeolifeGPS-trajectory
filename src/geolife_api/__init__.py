"""API dự đoán home / office cho một user (contract: docs/openapi.yaml).

- `config`: cấu hình từ biến môi trường.
- `db`: đọc điểm GPS từ Postgres.
- `model`: nạp model từ MLflow registry, chuyển output sang response.
- `service`: logic endpoint, không phụ thuộc HTTP.
- `errors`, `schemas`, `main`: phần HTTP (FastAPI).
- `migrate`, `seed`: tạo bảng, nạp dữ liệu.
"""
