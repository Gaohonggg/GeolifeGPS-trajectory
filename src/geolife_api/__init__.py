"""API dự đoán home / office cho một user (contract: docs/openapi.yaml).

- `config`: cấu hình từ biến môi trường.
- `model`: nạp model từ MLflow registry, chuyển output sang response.
- `service`: logic endpoint, không phụ thuộc HTTP; định nghĩa interface nguồn điểm GPS (`PointStore`).
- `points`: `S3PointStore`, đọc điểm theo user trên S3 hoặc thư mục local.
- `export_points`: dựng điểm theo user (`data/serving/v_<n>/`) từ preprocess và upload lên S3.
- `errors`, `schemas`, `main`: phần HTTP (FastAPI).
"""
