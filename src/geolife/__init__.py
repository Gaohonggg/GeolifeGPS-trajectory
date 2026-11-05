"""GeoLife: tìm home / office từ quỹ đạo GPS.

Các module theo thứ tự pipeline:

- `io`: đọc dữ liệu thô (.plt, labels.txt) và output của preprocess.
- `preprocess`: các bước làm sạch (notebook `preprocess/v_*/preprocess.ipynb` gọi lần lượt).
- `timezone`, `calendar`: giờ local theo toạ độ, lịch ngày làm việc theo quốc gia.
- `stays`, `places`, `home_office`: các bước của model.
- `models`: ghép các bước thành model có version (`models/<tên>/v_*/config.yaml`).
- `evaluation`: chỉ số đánh giá; `run`: chạy một model trên một split và ghi kết quả.
"""
