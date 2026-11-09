# dbscan v_1: cách chọn tham số

| | |
| --- | --- |
| **Model** | GPS → trọng số thời gian → ô lưới → DBSCAN (mỗi cụm là một place) → visit → home / office |
| **Dữ liệu** | preprocess `v_1` ([preprocess_v1.md](../preprocess_v1.md)) |
| **Tham số** | [`models_tuning/dbscan/v_1/config.yaml`](../../models_tuning/dbscan/v_1/config.yaml) |
| **Tái lập** | [`models_tuning/dbscan/v_1/tuning.ipynb`](../../models_tuning/dbscan/v_1/tuning.ipynb): mọi bảng dưới đây, chỉ chạy trên `dev` (135 user) |
| **Code** | [`models/dbscan.py`](../../src/geolife/models/dbscan.py), [`home_office.py`](../../src/geolife/home_office.py), [`calendar.py`](../../src/geolife/calendar.py) |
| **Chỉ số** | Định nghĩa ở [evaluation.md](../evaluation.md), tính trên visit như trên stay |

| Tham số | Giá trị | Bước |
| --- | --- | --- |
| cell_center | `grid`: tâm hình học của ô | định nghĩa của version |
| eps / min_time | 100 m / 240 phút | B1–B4 |
| T / bridge | 20 phút / 10 phút | B5 |
| max_gap | 24 h | B6 |
| cell_m | 30 m | B7 |
| Khung đêm / khung hành chính | [21, 9) mọi ngày / [9, 19) ngày làm việc | B8 |
| min_nights / min_workdays | 2 / 2 | B9 |

## Model làm gì

Khác stay_point ở chỗ không đi tìm từng lần dừng quanh một neo, mà tìm những **chỗ user ở lâu trên toàn bộ lịch sử**, rồi mới cắt
chuỗi điểm thành các lần ở lại.

1. **Trọng số thời gian.** Mỗi điểm nặng bằng số giây tới điểm kế tiếp. Khoảng không ghi dài hơn **max_gap** thì điểm đó nặng 0
   (không biết user ở đâu, cùng quy tắc với stay_point). Mật độ vì vậy là **thời gian lưu lại**, không phụ thuộc thiết bị ghi
   1 giây hay 5 giây một điểm (EDA 5).
2. **Ô lưới.** Gộp điểm vào ô cạnh **cell_m**, cộng trọng số trong ô. DBSCAN chạy trên ô vì một vùng nhà có hàng trăm nghìn điểm
   (user lớn nhất có 2,2 triệu điểm). Toạ độ đại diện của ô ở version này là **tâm hình học** của ô.
3. **DBSCAN có trọng số** (khoảng cách haversine): ô là lõi khi tổng thời gian trong bán kính **eps** quanh nó ≥ **min_time**.
   Các ô lõi liền nhau và các ô nằm trong eps của chúng tạo thành một cụm. **Mỗi cụm là một place**: không có bước gom place riêng
   như `place_eps` của stay_point.
4. **Visit.** Mỗi điểm nhận nhãn của ô chứa nó. Đoạn điểm liên tiếp cùng cụm là một visit. Đoạn nhiễu (ngoài mọi cụm) chen giữa
   ngắn hơn **bridge** thì nối vào visit. Gặp cụm khác, nhiễu lâu hơn bridge, hoặc khoảng không ghi dài hơn max_gap thì visit kết
   thúc. Chỉ giữ visit dài ≥ **T**. Toạ độ visit = trung bình có trọng số thời gian của các điểm thuộc cụm trong visit.
5. **Home / office và confidence:** dùng lại nguyên các bước của stay_point (`home_office.label_roles`), trên bảng visit thay cho
   bảng stay.

**Lỗi đặc trưng của DBSCAN là nối chuỗi:** các ô lõi liền nhau nối thành một cụm kéo dài, ví dụ dọc đường đi làm hằng ngày (ô ven
đường tích đủ thời gian sau nhiều ngày), hoặc nối nhà với các chỗ lân cận. Toạ độ của một cụm dài rơi vào giữa hai nơi. Các bước
B2–B4 đo trực tiếp điều này bằng **kích thước place**: với mỗi place có tổng thời gian visit ≥ 10 h, khoảng cách xa nhất từ một
visit tới tâm place; `wide_share` = % place rộng hơn 500 m.

**Lưu ý khi đọc chỉ số stay giả:** chỉ số đếm theo số điểm. Visit của dbscan bắt đầu ngay khi điểm vào vùng cụm, nên gồm cả đoạn xe
chạy vào / ra trong vùng đó (ghi dày), trong khi thời gian ở yên thường nằm trong khoảng không ghi (ít điểm). Trên `dev`, visit bị
tính là giả có median dài 10,0 h (visit không giả: 4,4 h). Vì vậy stay giả của dbscan (≈ 59%) cao hơn stay_point (47%) mà không có nghĩa là nhận nhầm nhiều
hơn; trong doc này chỉ dùng nó để so giữa các bộ tham số của dbscan.

---

## B1. Khoảng ứng viên của eps

**Định nghĩa:** eps phải chứa được dao động của GPS khi user đứng yên, nếu không các ô của cùng một chỗ không nối được với nhau.

**Xét:** EDA 14: bán kính chứa 90% số điểm trong cửa sổ 10 phút đứng yên có p50 = 16 m, p90 = 71 m, p95 = 149 m, p99 = 746 m.

**⇒ Ứng viên eps ∈ {50, 100, 200, 300} m**, như D của stay_point.

## B2. Lưới eps × min_time

**Định nghĩa:** mọi cặp eps × min_time ∈ {10, 30, 60, 120, 240, 480} phút. Các tham số khác lấy giá trị đã chốt (chúng được chọn ở
B5–B9 rồi chạy lại toàn bộ notebook để kiểm tra mọi bước vẫn chọn ra cùng giá trị).

**Xét:** % place rộng hơn 500 m:

| eps \ min_time | 10 | 30 | 60 | 120 | 240 | 480 |
| --- | --- | --- | --- | --- | --- | --- |
| 50 m | 19,1% | 7,1% | 3,5% | 1,9% | 0,7% | 0,5% |
| 100 m | 27,2% | 17,4% | 12,4% | 7,5% | **4,3%** | 3,6% |
| 200 m | 37,8% | 33,0% | 25,9% | 18,4% | 16,0% | 12,2% |
| 300 m | 45,7% | 39,7% | 35,5% | 30,6% | 26,7% | 22,9% |

**Output cho thấy:**
- Nối chuỗi rất rõ khi min_time nhỏ: ở 10 phút, place rộng nhất (p95) dài 1,5–7,7 km tuỳ eps.
- Tăng min_time làm place gọn lại ở mọi eps (eps = 100 m: p95 từ 2.444 m xuống 436 m); eps càng lớn càng dễ nối chuỗi.
- Số visit / ngày (0,86–1,39) thấp hơn stay_point (≈ 2,1): một chỗ chỉ thành place khi user ở đó **tổng cộng** ≥ min_time, nên chỗ
  ghé một lần ngắn không thành place.
- Phân mảnh rất thấp (0,2–3,1%) ở mọi cặp.

## B3. Chọn min_time cho từng eps: chống nối chuỗi

**Quy tắc:** với mỗi eps, lấy min_time nhỏ nhất mà ≤ 5% số place rộng hơn 500 m (5 lần eps = 100 m, lớn hơn một toà nhà / khu nhà).
eps không đạt ở mọi min_time thì loại.

**Output cho thấy:** eps = 50 m đạt từ 60 phút (3,5%), eps = 100 m từ 240 phút (4,3%). eps = 200 m và 300 m không đạt ở bất kỳ
min_time nào (thấp nhất 12,2% và 22,9%): loại.

## B4. Chọn eps

**Quy tắc:** như D của stay_point: nhiều visit dài ≥ 6 h nhất, miễn là stay giả không tăng quá 3 điểm % so với eps nhỏ nhất còn lại.

| eps / min_time | Visit / ngày | Stay giả | Phân mảnh | Visit ≥ 6 h | Place rộng (p95) |
| --- | --- | --- | --- | --- | --- |
| 50 m / 60 phút | 1,22 | 58,7% | 3,0% | 4.293 | 382 m |
| **100 m / 240 phút** | 1,14 | 58,6% | 1,4% | **5.155** | 471 m |

**Output cho thấy:** eps = 100 m có nhiều visit dài hơn 20%, phân mảnh bằng một nửa, stay giả gần như bằng.

**⇒ Chọn eps = 100 m, min_time = 240 phút.** Một chỗ thành place khi user ở trong bán kính 100 m quanh nó tổng cộng ≥ 4 giờ.

## B5. Chọn T và bridge

**Xét:** phân mảnh theo T × bridge (phân cụm chạy một lần, chỉ đổi cách cắt visit):

| T \ bridge | 0 | 2 phút | 10 phút | 30 phút |
| --- | --- | --- | --- | --- |
| 10 phút | 7,5% | 4,0% | 1,6% | 1,2% |
| 20 phút | 5,6% | 3,1% | **1,4%** | 1,1% |
| 30 phút | 4,5% | 2,7% | 1,3% | 0,9% |
| 60 phút | 3,0% | 1,9% | 0,9% | 0,7% |

**Output cho thấy:**
- bridge quyết định phân mảnh: từ 0 lên 10 phút giảm 4,2 điểm %, từ 10 lên 30 chỉ thêm 0,3 điểm % và bắt đầu nối cả những lần ra
  ngoài thật.
- T không làm giảm stay giả (58,1–59,3% ở T = 10–30 phút, 61,3% ở 60 phút) và không đổi số visit dài; T chỉ bỏ visit ngắn
  (1,36 → 1,14 visit / ngày từ 10 lên 20 phút).

**⇒ Chọn bridge = 10 phút, T = 20 phút.** T giữ như stay_point: dữ liệu không cho lý do đổi, và giữ chung T thì hai model cùng
định nghĩa "một lần dừng có ý nghĩa".

## B6. Chọn max_gap

**Xét:** % cặp điểm liên tiếp mà điểm sau cách điểm trước ≤ 100 m, theo độ dài khoảng không ghi; và chỉ số visit theo max_gap.

| Khoảng không ghi | < 1 h | 1–3 h | 3–6 h | 6–12 h | 12–24 h | 24–48 h | 48–72 h | 3–7 ngày | > 7 ngày |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Quay lại đúng chỗ | 64% | 45% | 32% | 28% | 18% | 11% | 10% | 11% | 9% |

| max_gap | 6 h | 12 h | **24 h** | 48 h | 72 h |
| --- | --- | --- | --- | --- | --- |
| Visit ≥ 6 h | 701 | 3.378 | 5.155 | 5.455 | 5.528 |
| Stay giả | 58,7% | 59,5% | 58,6% | 57,9% | 57,9% |

**Output cho thấy:** tỉ lệ quay lại đứng yên quanh 9–11% từ 24 h trở đi (mức "tình cờ"); số visit dài tăng 53% từ 12 lên 24 h
nhưng chỉ 6% từ 24 lên 48 h.

**⇒ Chọn max_gap = 24 h** (như stay_point).

## B7. Chọn cell_m

**Quy tắc:** lấy lưới 10 m làm mốc; chọn cell_m lớn nhất mà home và office đều trùng mốc ≥ 95% (hai place cách nhau ≤ 200 m) và
số user chỉ một bên có dự đoán ≤ 5%.

| cell_m | Ô / user (median) | Phân cụm | Home trùng mốc | Office trùng mốc | Chỉ một bên (home / office) |
| --- | --- | --- | --- | --- | --- |
| 10 m | 12.642 | 37 s | 100% | 100% | 0 / 0 |
| 20 m | 8.149 | 19 s | 97,9% | 97,5% | 1 / 3 |
| **30 m** | 5.699 | 13 s | 97,9% | 97,5% | 1 / 2 |
| 50 m | 3.455 | 8 s | 95,7% | 91,0% | 1 / 5 |
| 100 m | 1.723 | 5 s | 72,5% | 63,2% | 14 / 28 |

**Output cho thấy:** tới 30 m kết quả gần như không đổi mà thời gian phân cụm giảm gần 3 lần. Ô 50 m bắt đầu lệch office. Ô 100 m
lớn hơn eps nên các ô gần như không còn láng giềng: số visit giảm 37%.

**⇒ Chọn cell_m = 30 m.**

## B8. Khung đêm và khung hành chính

**Quy tắc:** như stay_point: khung đêm = giờ được ≥ 60% số visit qua đêm phủ; khung hành chính = giờ được ≥ 40% số visit ban ngày
của ngày làm việc phủ (3.108 visit qua đêm của 77 user; 1.529 visit ban ngày của 60 user).

| Giờ | 8 | 9 | 18 | 19 | 20 | 21 | 22 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Visit qua đêm | **68** | 47 | 25 | 35 | 47 | **60** | 75 |
| Visit ban ngày, ngày làm việc | 23 | **44** | **45** | 26 | 16 | 5 | 0 |

**Output cho thấy:** cả hai khung rộng hơn stay_point một giờ ([22, 9) và [9, 18)). Visit bắt đầu ngay khi user vào vùng của place,
nên dài hơn stay một chút ở hai đầu.

**⇒ Chọn:** khung đêm **[21, 9)**, mọi ngày; khung hành chính **[9, 19)**, chỉ ngày làm việc.

## B9. Cần bao nhiêu đêm / ngày làm việc?

**Quy tắc:** như stay_point: với user có ≥ 20 đêm ở home (48 user) / ≥ 20 ngày làm việc ở office (30 user), rút k ngày, chọn lại
và so với kết quả dùng toàn bộ dữ liệu; chọn k nhỏ nhất mà cả hai vai trò trùng ≥ 60%.

| k | 1 | **2** | 3 | 5 | 10 |
| --- | --- | --- | --- | --- | --- |
| Home trùng mốc | 72% | **77%** | 82% | 88% | 91% |
| Office trùng mốc | 57% | **64%** | 71% | 75% | 84% |

**⇒ Chọn min_nights = min_workdays = 2** (stay_point: 3). Home ổn định sớm hơn vì mỗi place gom mọi lần ở lại quanh nó, kể cả
những lần ngắn hơn một stay.

## Giả định của model

| # | Giả định | Bằng chứng | Hệ quả nếu sai |
| --- | --- | --- | --- |
| G1 | Chỗ user ở lâu tổng cộng (≥ 4 h trong 100 m) là một place | B3–B4 | Chỗ ghé một lần dài < 4 h, hoặc nhiều lần rất ngắn, không thành place |
| G2 | Place ≤ 500 m là một nơi thật, không phải hai nơi bị nối | B3: ≤ 5% place rộng hơn 500 m | Còn 4,3% place rộng; home / office ở các place đó có toạ độ lệch về giữa |
| G3 | Toạ độ tâm ô đủ gần vị trí thật của các điểm | B7: ô 30 m đổi kết quả < 3% so với ô 10 m | Ở rìa cụm, một ô có thể bị gán sai cụm |
| G4 | Thời gian trong khoảng không ghi ≤ 24 h là ở lại chỗ cũ | B6 | Như stay_point |

## Kết quả (chạy một lần, sau khi chốt tham số)

```bash
uv run python -m geolife.run --model dbscan --version 1 --split dev
```

```bash
uv run python -m geolife.run --model dbscan --version 1 --split holdout
```

| | `dev` (135 user) | `holdout` (47 user) |
| --- | --- | --- |
| Số visit / visit mỗi ngày | 10.653 / 1,14 | 2.288 / 1,28 |
| Stay giả | 58,6% | 21,0% |
| Phân mảnh | 1,4% | 1,8% |
| Visit ≥ 6 h | 5.155 | 820 |
| User có home / office | 93 / 82 | 33 / 23 |
| Confidence median home / office | 1,00 / 0,83 | 0,93 / 0,86 |
| Thời gian chạy | 15,2 s | 5,2 s |

Kết quả ở `results/data_v1/dbscan_v1/{dev,holdout}/`. So sánh với stay_point làm sau.
