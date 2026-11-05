# Preprocess v_1

Biến các file `.plt` thô thành một bảng điểm sạch, có giờ local đúng, cộng với cách chia `dev` / `holdout` không rò rỉ.

| | |
| --- | --- |
| **Code** | Hàm của từng bước: [`src/geolife/preprocess.py`](../src/geolife/preprocess.py); đọc dữ liệu: [`io.py`](../src/geolife/io.py); timezone: [`timezone.py`](../src/geolife/timezone.py) |
| **Chạy và kiểm tra** | [`preprocess/v_1/preprocess.ipynb`](../preprocess/v_1/preprocess.ipynb), gọi lần lượt từng bước và in mẫu sau mỗi bước. Ký hiệu **PP-n** = bước n của notebook |
| **Tham số** | [`preprocess/v_1/config.yaml`](../preprocess/v_1/config.yaml) |
| **Bằng chứng từ dữ liệu thô** | [EDA findings](eda_findings.md), ký hiệu **EDA n** |

```bash
uv run jupyter nbconvert --to notebook --execute --inplace preprocess/v_1/preprocess.ipynb
```

## Nguyên tắc

1. **Mục tiêu là tìm nơi dừng lâu**, không phải tái tạo chính xác quỹ đạo. Chỉ xoá những gì chắc chắn sai hoặc chắc chắn không thể là một lần dừng.
2. **Ngưỡng chỉ được chọn ở vùng không nhạy:** dịch ngưỡng quanh giá trị đã chọn mà kết quả gần như không đổi.
3. **Preprocess không chứa giả định của bài toán home/office.** Khung đêm, khung hành chính, ngày làm việc, số đêm tối thiểu... đều thuộc về
   model và được chọn ở bước tuning của model.
4. **Output chỉ có những gì bước sau dùng.** Mỗi file output ghi rõ ai dùng nó.

---

## 1. Pipeline

| Bước | Quy tắc | Tham số | Tác động |
| --- | --- | --- | --- |
| PP-1 | Đọc raw; bỏ altitude; nhãn phương tiện đọc riêng, không gắn vào điểm | | 24.876.978 điểm, 18.670 file, 182 user |
| PP-2 | Bỏ toạ độ ngoài miền, năm ngoài 2007–2012; bỏ trùng `(user, ts_utc)`, giữ điểm đầu | | −4 điểm; −698.900 điểm trùng (2,81%) |
| PP-3 | Tìm file trùng giữa các user: **chỉ đánh dấu** | khoá: tên + số điểm + điểm đầu + thời điểm cuối | 1.679 file, 44 cặp user |
| PP-4 | Loại file chuyến bay | median tốc độ của file > 300 km/h | −19 file, −72.863 điểm |
| PP-5 | Loại file lỗi nặng | spike ≥ 1% **và** ≥ 10 spike | −1 file, −8.091 điểm |
| PP-6 | Xoá spike A → B → A | 150 km/h, tỉ lệ quay về 0,3 | −133 điểm |
| PP-7 | Xoá điểm không có liên kết hợp lý nào nhưng có bước nhảy > 400 km/h; **giữ** bước nhảy giữa hai đoạn dài | 400 km/h, khoảng không ghi 5 phút, 1 điểm | −5.557 điểm; giữ 1.148 bước nhảy |
| PP-8 | Giờ local theo timezone thật của từng toạ độ (có DST) | làm tròn toạ độ 4 chữ số | 26 timezone, 0 điểm không tra được |
| PP-9 | User gần trùng (cùng chỗ cùng lúc) + file trùng → nhóm user | ≥ 10% số phút có dữ liệu | 139 nhóm, 19 nhóm có > 1 user |
| PP-10 | Chia `dev` / `holdout` theo nhóm, kiểm tra rò rỉ | holdout 30% user, seed 42 | 135 / 47 user, 0 nhóm nằm hai phía |
| PP-11 | Ghi output | | **24.091.430 điểm (96,84%)**, 18.649 file, 182 user |

---

## 2. Quy tắc và bằng chứng

### 2.1 Trùng timestamp (PP-2)

- **Vấn đề:** 698.900 điểm (2,81%) trùng giây với điểm khác của cùng user. Với dt = 0, tốc độ thành vô hạn và làm hỏng mọi quy tắc tốc độ phía sau.
- **Quy tắc:** với mỗi `(user, ts_utc)` giữ điểm xuất hiện đầu tiên.
- **Bằng chứng:** 99,5% điểm trùng giây cách điểm đầu cùng giây < 10 m, median 0,5 m (EDA 3). Giữ điểm nào cũng không đổi vị trí dừng.
  Hai file của cùng user không bao giờ chồng lấn thời gian (EDA 2), nên khoá theo user tương đương khoá theo file.
- **Kiểm tra:** sau bước này không còn dt ≤ 0.

Các lỗi giá trị khác: 1 điểm `lat = 400,17` và 3 điểm năm 2000 của user 163 (lỗi đồng hồ; mọi dữ liệu khác nằm trong 2007–2012, EDA 3) bị xoá.
**Altitude bị bỏ hẳn:** bài toán không cần, và cột này không đáng tin (−777 ở 0,22% điểm, max 32.767 là tràn `int16`, EDA 3).

### 2.2 File chuyến bay: median tốc độ > 300 km/h (PP-4)

- **Vấn đề:** phần lớn điểm > 300 km/h nằm trong các chuyến bay không có nhãn (EDA 13). Điểm đang bay không thể là nơi dừng.
- **Quy tắc:** loại cả file khi median tốc độ của file > 300 km/h.
- **Bằng chứng:**
  - Median theo file có một **khoảng trống tự nhiên**: không file nào trong 250–450 km/h. Phía mặt đất cao nhất là 225 km/h (file `train` tối đa 206);
    phía chuyến bay thấp nhất là 474 km/h. Mọi ngưỡng 250, 300, 450 đều cho cùng **19 file**.
  - 800 km/h (tốc độ hành trình) là sai mốc: một file bay còn chứa lăn bánh, cất / hạ cánh, nên median thấp hơn nhiều. Ngưỡng 800 chỉ bắt 3/7 file có nhãn `airplane`; ngưỡng 300 bắt 6/7.
  - File `airplane` thứ 7 có median 6 km/h (phần lớn là thời gian dưới mặt đất). Đoạn bay của nó bị xoá ở PP-7.

### 2.3 File lỗi nặng: điều kiện AND (PP-5)

- **Vấn đề:** spike tập trung trong vài file; riêng file `62_20080926000623` chứa 577 spike trên 8.091 điểm (7,1%), toạ độ nhảy qua lại Bắc Kinh – Tây An (EDA 13).
- **Quy tắc:** loại cả file khi tỉ lệ spike ≥ 1% **và** số spike ≥ 10.
- **Bằng chứng:** phân bố số spike / file: 99 file có 1 spike, 6 file có 2, 2 file có 3–5, **0** file có 6–10, 2 file > 10.

| Điều kiện | File bị loại | Vấn đề |
| --- | --- | --- |
| ≥ 1% **hoặc** ≥ 10 | 6 | Loại nhầm file ngắn có 1–3 spike (1 spike / 5 điểm = 20%), và file dài 16 spike / 4.271 điểm (0,37%) |
| ≥ 1% **và** ≥ 10 | 1 | Chỉ đúng file lỗi. Các file khác chỉ cần xoá điểm spike ở PP-6 |

### 2.4 Spike A → B → A (PP-6)

- **Quy tắc:** B là spike khi tốc độ A→B và B→C đều > 150 km/h và C quay về gần A: d(A, C) < 0,3 · d(A, B). Lặp tối đa 3 lần (vòng 2 không còn spike).
- **Bằng chứng (bảng độ nhạy ở PP-5):**

| v \ ratio | 0,1 | 0,3 | 0,5 |
| --- | --- | --- | --- |
| 100 km/h | 677 | 951 | 1.196 |
| **150 km/h** | 624 | **710** | 767 |
| 200 km/h | 604 | 620 | 630 |
| 300 km/h | 594 | 595 | 595 |

  - Lõi khoảng 600 spike không đổi khi tăng ngưỡng tới 300 km/h: đó là các cú nhảy lớn, chắc chắn sai.
  - Hạ xuống 100 km/h làm số file bị ảnh hưởng tăng gần 3 lần (293 so với 109), tức là bắt đầu chạm vào chuyển động thật.
  - Ở 150 / 0,3 chỉ 2 spike rơi vào đoạn có nhãn `train` / `airplane`.
- 710 spike, trong đó 577 thuộc file đã loại ở PP-5, nên PP-6 xoá **133** điểm.

### 2.5 Điểm có tốc độ > 400 km/h (PP-7)

**Ngưỡng 400 km/h:** tàu là phương tiện mặt đất nhanh nhất (p99 ≈ 210 km/h, EDA 11). Số liên kết vượt ngưỡng có nhãn `train`:
80 ở 250 km/h, 51 ở 300, **17** ở 400. Ngưỡng thấp hơn bắt đầu chạm tàu / xe thật.

**Tốc độ là thuộc tính của một liên kết giữa hai điểm, không phải của một điểm.** Một liên kết > 400 km/h chỉ nói rằng *một trong hai đầu* sai,
không nói đầu nào. Phiên bản cũ xoá mọi điểm có tốc độ vào > 400 rồi lặp lại, gây **xoá dây chuyền**: xoá xong thì điểm kế tiếp lại thành "quá tốc độ"
(6.697 → 702 → 444 điểm qua 3 vòng, vẫn còn tốc độ 57.654 km/h).

**Quy tắc mới:** cắt mỗi file thành các **đoạn** tại bước nhảy > 400 km/h và tại khoảng không ghi > 5 phút. Trong một đoạn, các điểm nối nhau bằng
liên kết hợp lý, tức là tự nhất quán.

| Trường hợp | Ví dụ ở PP-7 | Xử lý |
| --- | --- | --- |
| Đoạn chỉ có **1 điểm**, có ít nhất một đầu là bước nhảy: điểm không có liên kết hợp lý nào | Điểm lạc đơn lẻ; đoạn bay trong file hỗn hợp (chuỗi điểm 1-điểm liên tiếp > 400 km/h); fix sai ngay sau khoảng không ghi 1.408 s, cách 1,2 km rồi nhảy về đúng chỗ cũ trong 8 s | **Xoá** (5.557 điểm) |
| Bước nhảy giữa hai đoạn **≥ 2 điểm** ("chỉ một phía"): cả hai phía đều tự nhất quán | Đang đi 20–40 km/h, nhảy 650 m trong 5 s, rồi tiếp tục đi bình thường ở chỗ mới: mất tín hiệu rồi bắt lại | **Giữ cả hai phía** (1.148 bước nhảy, 116 user) |

**Vì sao chỉ đoạn 1 điểm:** đoạn 1 điểm có thời lượng 0 s. Đoạn 2–3 điểm chỉ có ~100 đoạn, thời lượng median 5–25 s nhưng có đoạn tới 5 phút,
nghĩa là có thể là một chỗ dừng thật. Đoạn 1 điểm là mức chắc chắn sai mà không cần đoán.

**Vì sao giữ bước nhảy một phía mà không đánh dấu:** vị trí ở cả hai phía đều đúng; chỉ tốc độ của đúng một liên kết là vô nghĩa. Bước stay chỉ dùng
vị trí và thời gian, và output không có cột tốc độ, nên không cần cờ nào.

**Vì sao cắt cả tại khoảng không ghi > 5 phút:** liên kết qua khoảng không ghi dài luôn có "tốc độ" thấp, nên một fix sai ngay sau khi bắt lại tín hiệu
sẽ trông như hợp lý nếu chỉ xét tốc độ. Độ nhạy: 5.921 / 5.557 / 5.445 / 5.346 điểm bị xoá với ngưỡng 1 / 5 / 10 / 30 phút. Chênh lệch là vài trăm điểm
trên 24 triệu.

**Kiểm tra chéo:** trong 5.557 điểm bị xoá chỉ có 34 điểm có nhãn (17 `walk`, 7 `bus`...).

### 2.6 Giờ local theo timezone thật của toạ độ (PP-8)

- **Vấn đề:** timestamp gốc là UTC. 97% điểm ở UTC+8, nhưng phần còn lại nằm ở 25 timezone khác, có nơi dùng DST (EDA 8).
- **Quy tắc:** tra timezone IANA bằng `timezonefinder` (ranh giới timezone thật) cho từng toạ độ duy nhất (làm tròn ~11 m), rồi đổi giờ theo đúng timezone
  đó tại đúng thời điểm. **Không có giả định "mọi điểm là giờ Trung Quốc".**
- **Kiểm tra:** 26 timezone, 0 điểm không tra được; `America/Los_Angeles` có cả −7 và −8 (DST); tra mất 5 giây.
- **Quốc gia và lịch nghỉ lễ không làm ở đây.** Output giữ `tz`; model suy ra quốc gia từ `tz` (bảng `zone.tab` của `tzdata`) và tra lịch nghỉ lễ của đúng
  nước đó. Mọi timezone trong dữ liệu đều map được sang quốc gia, trừ `Etc/GMT-10` (12 điểm trên biển).

### 2.7 Nhóm user và chia dev / holdout (PP-3, PP-9, PP-10)

Mục tiêu: tham số chọn trên `dev` không được "nhìn thấy trước" `holdout`.

| Rủi ro | Bằng chứng | Xử lý |
| --- | --- | --- |
| **File trùng y hệt** ở nhiều user | 1.679 file, 2,97 triệu điểm (~12%), 44 cặp user (EDA 4) | Giữ ở cả hai user (không biết ai là chủ thật), nối thành nhóm |
| **User gần trùng**: không có file trùng nhưng cùng chỗ cùng lúc (file cắt khác nhau, hai thiết bị đi cùng nhau) | Đo theo (phút, ô ~100 m): 15 cặp không có file trùng nhưng chung ≥ 10% thời gian, ví dụ user 49 và 122 chung 96% | Cặp chung ≥ 10% được nối vào nhóm |
| **User chiếm quá nhiều dữ liệu** | User 153 chiếm 9% số điểm; 15 user chiếm 50% (EDA 1) | Nhóm chiếm > 5% số điểm bị ép vào `dev` (nhóm 20 user gồm 128, 153, 163) |
| Hai phía khác phân bố | | Phân tầng theo (có nhãn phương tiện) × (số ngày có dữ liệu, 3 khoảng) |

| Split | User | Nhóm | User có nhãn | Điểm | Median ngày có dữ liệu | User lớn nhất |
| --- | --- | --- | --- | --- | --- | --- |
| dev | 135 | 100 | 53 | 18,45 triệu (76,6%) | 24 | 9,0% số điểm |
| holdout | 47 | 39 | 16 | 5,64 triệu (23,4%) | 18 | 4,4% số điểm |

**Kiểm tra rò rỉ (PP-10):**
- 0 nhóm nằm ở cả hai phía; 0 cặp có file trùng nằm ở hai phía. Điều này chỉ xác nhận cách gán nhóm nhất quán. Hai kiểm tra dưới đây xem phần có thể bị bỏ sót.
- `holdout` chỉ dùng **một lần**, sau khi đã chốt tham số model trên `dev`.

Hai kiểm tra sau được chạy **một lần** (hash trên file thô, colocation trên `points.parquet` của v_1) để làm bằng chứng cho cách làm hiện tại. Chúng không phải bước của pipeline, và không có trong notebook.

**Khoá file trùng có đúng không? So với hash nội dung.** Khoá metadata (tên, số điểm, điểm đầu, thời điểm cuối) chưa so từng dòng, nên được đối chiếu với
hash toàn bộ chuỗi (timestamp, lat, lon) của từng file thô:

| | File trùng |
| --- | --- |
| Theo metadata | 1.679 |
| Theo hash nội dung | 1.677 |
| Hash bắt được mà metadata bỏ sót | **0** |
| Metadata bắt mà hash không | 2 (1 cặp) |

Cặp lệch là `128_20070728225925` và `153_20070728225925`: 70 dòng giống hệt nhau trừ 1 dòng lệch đúng 1 giây, tức vẫn là một file bị chép.
⇒ Khoá metadata không bỏ sót và không bắt nhầm, nên **giữ nguyên, không đổi sang hash** (hash còn quá khắt khe ở trường hợp lệch 1 giây).

**Lưới colocation có bỏ sót không? Thử ở nhiều độ phân giải.** Lưới (1 phút, ô ~100 m) có thể bỏ sót hai điểm sát nhau nằm hai bên ranh giới ô / phút.
Lưới thô hơn chỉ làm `share` tăng, nên là cận trên của phần bị bỏ sót:

| Lưới | Cặp ≥ 10% chưa chung nhóm | Cặp hai phía | Cặp hai phía ≥ 10% | `share` lớn nhất ở hai phía |
| --- | --- | --- | --- | --- |
| 1 phút, ~111 m (dùng để gộp nhóm) | 0 | 126 | 0 | 5,3% (user 3–5) |
| 2 phút, ~222 m | 1 | 179 | 0 | 8,1% (user 101–174) |
| 5 phút, ~555 m | 3 | 292 | 1 | 10,5% (user 101–174) |
| 10 phút, ~1,1 km | 7 | 377 | 1 | 11,3% (user 101–174) |

- Nới gấp đôi cả không gian lẫn thời gian vẫn không có cặp hai phía nào chung ≥ 10%: phần bị bỏ sót do ranh giới ô / phút là nhỏ.
- Ở lưới ≥ 5 phút / ≥ 500 m, `share` tăng cả với những người chỉ cùng khu làm việc (EDA 9: 165/182 user từng qua cùng một khu ở Haidian), nên không
  dùng lưới thô để gộp nhóm. Cặp duy nhất vượt 10% ở lưới thô là user 101 (`dev`) – 174 (`holdout`): chưa xem tay để biết có đi cùng nhau thật không.

⇒ **Giữ nguyên lưới (1 phút, ~100 m).** Kết luận đúng mức: kiểm tra ở nhiều độ phân giải không phát hiện cặp hai phía nào chung ≥ 10%, trừ cặp 101–174
ở lưới thô. Đây không phải là chứng minh hoàn toàn không có rò rỉ.

---

## 3. Output `data/preprocess/v_1/`

| File | Nội dung | Ai dùng |
| --- | --- | --- |
| `points.parquet` | `user, traj_id, ts_utc, ts_local, tz, lat, lon`, sort theo `(user, ts_utc)` | Model: input duy nhất |
| `labels.parquet` | Nhãn phương tiện gốc: `user, start_utc, end_utc, mode` | Chỉ đánh giá (stay giả). Tách khỏi điểm để model không thấy nhãn |
| `users.parquet` | `n_points, n_trajs, days, point_share, has_labels, dup_share, group, group_size, split` | Chọn user theo split |
| `report.json` | Config đã dùng, số liệu từng bước, danh sách file bị loại kèm lý do | Kiểm tra / tái lập |

So với phiên bản trước, đã bỏ: `is_workday`, `in_china`, `calendar_cn.parquet` (lịch thuộc về model), tier và `nights / workdays` (dựa trên khung giờ
của model), `manual_eval`, các cột `dt_s, dist_m, speed_kmh, jump_in, mode` (không bước nào dùng), `trajectories.parquet` (gộp vào `report.json`).

**Quản lý version:** mỗi version có `config.yaml` + notebook riêng ở `preprocess/v_<n>/` và output riêng ở `data/preprocess/v_<n>/`. Khi đã có model
chạy trên một version, đổi bất kỳ tham số nào thì tạo version mới.

## 4. Cố ý không làm

| Không làm | Lý do |
| --- | --- |
| Làm mượt toạ độ (moving average, Kalman) | Dao động khi đứng yên p95 = 149 m (EDA 14), nằm trong bán kính stay. Làm mượt có thể dịch vị trí hoặc xoá một lần dừng ngắn |
| Resample, nội suy | Tần suất ghi khác nhau giữa thiết bị và năm (EDA 5). Model tính theo thời lượng, không đếm điểm. Nội suy qua khoảng không ghi tạo điểm không có thật |
| Cắt trajectory tại gap dài | Phần lớn thời gian dừng nằm trong khoảng không ghi giữa hai file (EDA 6, 7). Giới hạn gap là tham số của model (`max_gap`) |
| Lọc theo khu vực Bắc Kinh | 31 user có < 50% số điểm ở Bắc Kinh (EDA 9) |
| Xoá mọi đoạn tốc độ cao (xe, tàu) | Đoạn di chuyển vốn không tạo stay. Xoá có thể tạo **stay giả**: hai đầu chuyến đi khứ hồi thành hai điểm liên tiếp gần nhau |
| Xoá file trùng giữa user | Không biết ai là chủ thật; xử lý bằng chia tập theo nhóm |

## 5. Giới hạn đã biết

1. Đoạn bay ngắn lúc cất / hạ cánh (< 400 km/h) vẫn còn. Chúng là đoạn di chuyển nên không tạo stay.
2. File trùng giữ ở cả hai user, nên các user bản sao sẽ có cùng home / office.
3. Lịch nghỉ lễ ngoài Trung Quốc lấy từ thư viện `holidays`, chưa đối chiếu tay (chiếm ~3% số điểm).
