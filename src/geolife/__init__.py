"""GeoLife: tìm home / office từ quỹ đạo GPS.

Các module theo thứ tự pipeline:

- `paths`, `geo`: đường dẫn chuẩn của repo, khoảng cách trên mặt cầu.
- `io`: đọc dữ liệu thô (.plt, labels.txt) và output của preprocess.
- `preprocess`: các bước làm sạch (notebook `preprocess/v_*/preprocess.ipynb` gọi lần lượt).
- `timezone`, `calendar`: giờ local theo toạ độ, lịch ngày làm việc theo quốc gia.
- `models`: mỗi model một file, chứa thuật toán tìm nơi ở lại của model đó (`stay_point`: stay → place; `dbscan`: visit, mỗi
  cụm là một place). `models/base.py` giữ interface và hợp đồng dữ liệu chung. Tham số ở
  `models_tuning/<tên>/v_*/config.yaml`.
- `home_office`, `confidence`: bước chung sau khi đã có place: chọn home / office, confidence của từng dự đoán.
- `evaluation`: chỉ số đánh giá; `run`: chạy một model trên một split và ghi kết quả.
- `tuning`: phép đo khi chọn tham số (`common` dùng chung, `stay_point` / `dbscan` riêng từng model).
"""
