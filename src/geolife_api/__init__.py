"""API suy ra home / office cho một user (contract: docs/openapi.yaml).

- `config`: cấu hình đọc từ biến môi trường.
- `db`: kết nối Postgres, đọc điểm GPS của user.
- `model`: nạp model version từ MLflow registry, chuyển kết quả sang dạng response.
- `service`: `predict_user`, logic của endpoint, không phụ thuộc web framework.
- `errors`, `schemas`, `main`: phần HTTP (FastAPI).
- `migrate`, `seed`: lệnh chạy một lần để tạo bảng và nạp dữ liệu.
"""
