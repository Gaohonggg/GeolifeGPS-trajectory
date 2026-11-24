"""API dự đoán home / office cho một user (contract: docs/openapi.yaml).

- `config`: cấu hình từ biến môi trường.
- `model`: nạp model từ MLflow registry, chuyển output sang response.
- `service`: logic endpoint, không phụ thuộc HTTP; định nghĩa interface nguồn điểm GPS (`PointStore`).
- `errors`, `schemas`, `main`: phần HTTP (FastAPI).
"""
