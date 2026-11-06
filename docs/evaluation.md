# Đánh giá và các giả định

GeoLife **không có nhãn home / office**, nên không đo được độ chính xác của home / office. Ở giai đoạn này chỉ đánh giá **bước tạo stay**, là nền của
mọi bước sau. Chỉ số home / office (khi có cách kiểm chứng) sẽ bổ sung sau.

Code: [`src/geolife/evaluation.py`](../src/geolife/evaluation.py). Chạy: [`src/geolife/run.py`](../src/geolife/run.py).

## 1. Chỉ số

| Chỉ số | Định nghĩa | Dùng để |
| --- | --- | --- |
| **Tỉ lệ tạo stay** | Số stay, và số stay / số (user, ngày local) có dữ liệu | Xem có bị phân mảnh hay nhận nhầm lúc di chuyển là dừng không. Một người thường chỉ dừng ở vài nơi mỗi ngày |
| **Tỉ lệ stay giả** | Trong các stay có ≥ 50% số điểm nằm trong khoảng có nhãn phương tiện: % stay có ≥ 50% số điểm mang nhãn di chuyển (bike, bus, car, taxi, subway, train, airplane, motorcycle, boat). Không tính `walk`: đi bộ loanh quanh trong một nơi vẫn là đang ở nơi đó | Stay mà thực ra user đang di chuyển |
| Phân mảnh *(phụ)* | % stay bắt đầu ≤ 15 phút sau stay trước và tâm cách stay trước ≤ 250 m | Một lần dừng bị chẻ đôi. Định nghĩa cố định, không phụ thuộc tham số của model, nên so sánh được giữa các bộ tham số |
| Stay dài *(phụ)* | Số stay ≥ 6 giờ | Thời gian ở nhà / chỗ làm nằm trong các stay dài; tham số làm mất stay dài thì hại cho bước home / office |

Ngoài chỉ số, mỗi lần chạy ghi thêm **mô tả output** home / office: bao nhiêu user có dự đoán, lý do abstain. Đây không phải chỉ số đúng / sai.

**Đọc chỉ số thế nào:**
- Các chỉ số dùng để **so sánh tương đối giữa các bộ tham số**, không phải độ chính xác tuyệt đối.
- Stay giả chỉ đo được ở user có nhãn (69/182), và nhãn được ghi độc lập với GPS (EDA 12). Khoảng nhãn thường trùm cả lúc xe đã dựng / đỗ và cả khoảng không ghi, nên tỉ lệ này bị thổi phồng bởi nhiễu nhãn: chỉ dùng để so sánh giữa các bộ tham số, không đọc như tỉ lệ lỗi thật. Tính theo thời gian thay vì số điểm sẽ bớt nhiễu hơn (chưa làm).
- Chỉ số gộp theo stay nên user nhiều dữ liệu có trọng số lớn hơn. Power user lớn nhất nằm ở `dev`, không ở `holdout` ([preprocess_v1.md](preprocess_v1.md), mục 2.7).

## 2. Dùng dữ liệu thế nào

| Tập | Dùng để |
| --- | --- |
| `dev` (135 user, 53 có nhãn) | Tuning: chạy độ nhạy tham số, xem tuỳ ý |
| `holdout` (47 user, 16 có nhãn) | Chạy **một lần** sau khi đã chốt tham số. Kết quả holdout không được dùng để chỉnh lại version đó; muốn đổi thì tạo version mới và tuning lại trên `dev` |

Chia theo nhóm user, không theo từng user: file trùng và user gần trùng luôn nằm cùng một phía (kiểm tra rò rỉ ở preprocess PP-10).

```bash
uv run python -m geolife.run --model stay_point --version 1 --split dev
```

```bash
uv run python -m geolife.run --model stay_point --version 1 --split holdout
```

Kết quả ghi vào `results/data_v<d>/<model>_v<k>/<split>/`: `predictions.csv` (home / office theo user) và `metrics.json` (tham số, chỉ số, mô tả output, thời gian chạy).

## 3. Giả định của bước đánh giá

| Giả định | Vì sao chấp nhận | Hệ quả nếu sai |
| --- | --- | --- |
| Nhãn phương tiện đủ đúng để kiểm tra chéo stay giả | Nhãn do chính người dùng ghi | Nhãn ghi lệch giờ với GPS (EDA 12) làm tỉ lệ stay giả nhiễu |
| User trong `dev` và `holdout` đến từ cùng một phân bố | Chia ngẫu nhiên theo nhóm, có phân tầng (preprocess PP-10) | Holdout ít dữ liệu mỗi user hơn (median 18 ngày so với 24) và không có power user, nên chỉ số có thể lệch vì khác biệt dữ liệu, không phải vì tham số |

Giả định của từng model (khi nào user được coi là ở yên, home / office là gì...) nằm trong doc của model đó.

## 4. Chưa làm

- Kiểm tra thủ công trên mẫu (đối chiếu home / office với bản đồ) để có chỉ số đúng / sai cho home / office.
- Confidence cho từng dự đoán.
