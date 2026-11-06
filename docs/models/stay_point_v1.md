# stay_point v_1: cách chọn tham số

| | |
| --- | --- |
| **Model** | GPS → stay ([Li et al., 2008](#nguồn)) → place → home / office |
| **Dữ liệu** | preprocess `v_1` ([preprocess_v1.md](../preprocess_v1.md)) |
| **Tham số** | [`models/stay_point/v_1/config.yaml`](../../models/stay_point/v_1/config.yaml) |
| **Tái lập** | [`models/stay_point/v_1/tuning.ipynb`](../../models/stay_point/v_1/tuning.ipynb): mọi bảng / hình dưới đây, chỉ chạy trên `dev` (135 user) |
| **Code** | [`stays.py`](../../src/geolife/stays.py), [`places.py`](../../src/geolife/places.py), [`home_office.py`](../../src/geolife/home_office.py), [`calendar.py`](../../src/geolife/calendar.py) |
| **Chỉ số** | Định nghĩa ở [evaluation.md](../evaluation.md) |

| Tham số | Giá trị | Bước |
| --- | --- | --- |
| T | 20 phút | B3 |
| D | 200 m | B1, B4 |
| max_gap | 24 h | B5 |
| Khung đêm / khung hành chính | [22, 9) mọi ngày / [9, 18) ngày làm việc | B6 |
| place_eps | 200 m | B7 |
| min_nights / min_workdays | 3 / 3 | B8 |

## Model làm gì

1. **Stay:** đoạn điểm liên tiếp nằm trong bán kính **D** quanh điểm đầu, kéo dài ≥ **T**. Chạy trên chuỗi đã ghép mọi file của user theo thời gian,
   vì thời gian ở nhà / chỗ làm nằm chủ yếu trong khoảng không ghi giữa hai file (EDA 6). Khoảng không ghi > **max_gap** thì cắt stay.
2. **Place:** gom stay của cùng user. Lấy stay dài nhất làm tâm, kéo mọi stay chưa gán trong bán kính **place_eps**, lặp lại. Khác DBSCAN
   (`min_samples = 1`), place không "nối chuỗi" được, nên toạ độ không bị kéo vào giữa nhà và chỗ làm.
3. **Home / office, một lượt cho cả hai:** cắt mỗi stay thành các lát theo giờ local **một lần**, rồi gắn hai cờ trên cùng bảng:
   - `home` = lát nằm trong khung đêm, **mọi ngày** (kể cả ngày nghỉ lễ, cuối tuần);
   - `office` = lát nằm trong khung hành chính **của ngày làm việc**. Ngày làm việc lấy theo lịch của **đúng quốc gia của stay** (từ timezone):
     T2–T6 trừ ngày nghỉ lễ, cộng ngày làm bù (Trung Quốc).

   Gom theo place một lần, ra cùng lúc giờ / số đêm cho home và giờ / số ngày làm việc cho office. Không lọc dữ liệu rồi chạy lại cho từng vai trò:
   hai vai trò chỉ khác nhau ở cột trọng số.
   - **Home** = place nhiều giờ đêm nhất, có ≥ **min_nights** đêm.
   - **Office** = place nhiều giờ hành chính nhất, cách home > 200 m, có ≥ **min_workdays** ngày làm việc.
   - Không đủ điều kiện thì trả `null` kèm lý do (abstain), không đoán.

---

## B1. Khoảng ứng viên của D

**Định nghĩa:** D phải chứa được dao động của GPS khi user đứng yên. Nếu không, một lần dừng bị chẻ thành nhiều mảnh.

**Xét:** EDA 14 (dữ liệu thô) đo bán kính chứa 90% số điểm trong 13.236 cửa sổ 10 phút đứng yên:

| Phân vị | p50 | p75 | p90 | p95 | p99 |
| --- | --- | --- | --- | --- | --- |
| Bán kính p90 (m) | 16 | 32 | 71 | 149 | 746 |

**Output cho thấy:** D = 50 m chỉ chứa khoảng 3/4 số cửa sổ; từ ~150 m thì chứa 95%. Phần đuôi tới hàng trăm mét là do ở trong nhà / multipath.

**⇒ Ứng viên D ∈ {50, 100, 200, 300} m.** EDA chỉ cho khoảng. Giá trị cụ thể được chọn ở B4 bằng chỉ số stay.

## B2. Khả năng tạo stay khi thay đổi D và T

**Định nghĩa:** số stay, và số stay trên mỗi (user, ngày) có dữ liệu. Mỗi người thường chỉ dừng ở vài nơi mỗi ngày, nên số stay / ngày quá cao là dấu hiệu
phân mảnh, hoặc nhận nhầm lúc dừng đèn đỏ / kẹt xe là một lần dừng.

**Xét:** số stay / ngày (số stay ở dòng dưới):

| D \ T | 5' | 10' | 20' | 30' | 60' |
| --- | --- | --- | --- | --- | --- |
| 50 m | 3,46 (32.337) | 1,95 | 1,14 | 0,84 | 0,53 |
| 100 m | 4,18 (39.110) | 2,54 | 1,63 | 1,27 | 0,86 |
| 200 m | 4,90 (45.851) | 3,06 | 2,11 (19.784) | 1,73 | 1,24 |
| 300 m | 5,30 (49.638) | 3,27 | 2,33 | 1,95 | 1,44 |

**Output cho thấy:**
- Số stay nhạy với T hơn nhiều so với D: tăng T từ 5 lên 60 phút làm số stay giảm 3–6 lần; tăng D từ 50 lên 300 m chỉ tăng 1,5–2,7 lần.
- Ở T = 5 phút có 3,5–5,3 stay mỗi ngày: quá nhiều so với nhịp sống bình thường.

**⇒ Chọn T trước (B3), rồi mới chọn D (B4).**

## B3. Chọn T: tỉ lệ stay giả

**Định nghĩa:**
- Dùng nhãn phương tiện (53 user có nhãn trong `dev`) để kiểm tra chéo.
- Stay **trong vùng có nhãn**: ≥ 50% số điểm của stay nằm trong khoảng có nhãn.
- **Stay giả:** stay trong vùng có nhãn mà ≥ 50% số điểm mang nhãn **di chuyển**: phương tiện cơ giới (bus, car, taxi, subway, train, ...) hoặc xe đạp.
  Không tính `walk`: đi bộ loanh quanh trong một nơi (khuôn viên, trung tâm thương mại) vẫn là đang ở nơi đó.

**Xét:** D = 100 và D = 200 (hai giá trị giữa của B1):

| T | 5' | 10' | 20' | 30' | 60' |
| --- | --- | --- | --- | --- | --- |
| % stay giả, D = 100 m | 44,3% | 43,0% | **43,3%** | 45,4% | 49,0% |
| % stay giả, D = 200 m | 46,9% | 46,2% | **46,9%** | 48,5% | 52,1% |

**Output cho thấy:**
- Mức stay giả khá cao (43–52%). Một phần là nhiễu nhãn: khoảng nhãn `bike` / `car` thường trùm cả lúc xe đã dựng / đỗ và cả khoảng không ghi (EDA 12),
  nên chỉ số này chỉ dùng để **so sánh giữa các T**, không đọc như tỉ lệ lỗi thật.
- Từ T = 5 đến T = 20 stay giả gần như **không đổi** (chênh dưới 1 điểm %).
- Từ T = 30 trở đi stay giả **tăng rõ** (D = 200: 48,5% ở 30 phút, 52,1% ở 60 phút): T lớn loại bớt stay thật ngắn nhưng giữ lại các stay dài dưới nhãn
  di chuyển (xe dựng / đỗ lâu).

**⇒ Chọn T = 20 phút:** giá trị lớn nhất trước khi stay giả bắt đầu tăng. Trong vùng phẳng 5–20 phút, T lớn hơn cho ít stay vụn hơn
(B2: từ 3,06 xuống 2,11 stay / ngày khi T đi từ 10 lên 20 phút, D = 200) mà stay giả không tăng.

## B4. Chọn D: phân mảnh, stay giả và stay dài

**Định nghĩa:** với T = 20, xét lại D bằng ba chỉ số:
- **Phân mảnh:** % stay bắt đầu ≤ 15 phút sau stay trước và có tâm cách stay trước ≤ 250 m, tức là một lần dừng bị chẻ đôi. Định nghĩa cố định, không phụ thuộc D.
- **Stay giả:** như B3.
- **Stay dài:** số stay ≥ 6 giờ. Thời gian ở nhà / chỗ làm nằm trong các stay này.

**Xét:**

| D | Stay / ngày | Phân mảnh | Stay giả | Stay dài ≥ 6 h |
| --- | --- | --- | --- | --- |
| 50 m | 1,14 | 14,9% | **43,0%** | 1.702 |
| 100 m | 1,63 | 14,1% | 43,3% | 3.071 |
| **200 m** | 2,11 | 13,3% | 46,9% | **4.829** |
| 300 m | 2,33 | 11,6% | 50,2% | 5.825 |

**Output cho thấy:**
- Phân mảnh giảm chậm khi tăng D: chỉ từ 14,9% xuống 11,6% khi D đi từ 50 lên 300 m.
- Stay giả gần như không đổi tới 100 m (43,0% → 43,3%), rồi tăng khoảng 3,5 điểm % mỗi bước (46,9% ở 200 m, 50,2% ở 300 m).
- Nhưng **số stay dài tăng rất mạnh tới 200 m** (3.071 → 4.829, +57%), rồi chậm lại (→ 5.825 ở 300 m, +21%).
  Nguyên nhân: điểm trước và sau một khoảng không ghi qua đêm thường lệch nhau nhiều hơn so với khi đứng yên liên tục, nên D nhỏ làm đứt các stay qua đêm.
  Trên `dev` (với các tham số khác đã chốt), user có home / office: 77 / 61 ở D = 100, 88 / 76 ở D = 200, 92 / 78 ở D = 300.
- Từ 200 lên 300 m, lợi ích về stay dài nhỏ dần (+21%), trong khi stay giả vẫn tăng cùng mức và bán kính bắt đầu gộp hai nơi khác nhau.

**⇒ Chọn D = 200 m:** đổi 3,6 điểm % stay giả lấy thêm hơn một nửa số stay dài. Giá trị này cũng chứa được p95 dao động khi đứng yên (149 m, B1).

## B5. Chọn max_gap: sau một khoảng không ghi, user có còn ở đúng chỗ cũ không?

**Định nghĩa:** stay được phép kéo qua khoảng không ghi (EDA 6), nhưng khoảng càng dài thì càng ít bằng chứng user đã ở yên. Đo, với mọi cặp điểm liên tiếp
có khoảng không ghi ≥ 10 phút, % cặp mà điểm sau cách điểm trước ≤ D ("quay lại đúng chỗ").

**Xét:**

| Khoảng không ghi | 10'–1 h | 1–3 h | 3–6 h | 6–12 h | 12–24 h | 24–48 h | 48–72 h | 3–7 ngày | > 7 ngày |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Số cặp | 14.174 | 5.329 | 2.749 | 5.149 | 4.781 | 1.163 | 339 | 384 | 307 |
| % quay lại đúng chỗ | 72% | 61% | 47% | 44% | 32% | **22%** | 19% | 18% | 18% |

| max_gap | 6 h | 12 h | **24 h** | 48 h | 72 h | không giới hạn |
| --- | --- | --- | --- | --- | --- | --- |
| Stay / ngày | 1,65 | 1,92 | 2,11 | 2,14 | 2,15 | 2,17 |
| Phân mảnh | 15,5% | 14,0% | 13,3% | 13,2% | 13,2% | 13,2% |
| Stay giả | 41,7% | 45,7% | 46,9% | 46,9% | 46,8% | 46,8% |
| Stay dài ≥ 6 h | 161 | 2.888 | **4.829** | 5.133 | 5.210 | 5.356 |

**Output cho thấy:**
- Tỉ lệ quay lại đúng chỗ giảm dần theo độ dài khoảng không ghi, rồi từ 24 h trở đi **gần như đứng yên ở 18–22%**. Đó là mức "tình cờ":
  sau hơn một ngày, việc user ở đúng chỗ cũ không còn nói gì về việc họ đã ở yên suốt khoảng đó (phần lớn chỉ là đã về nhà).
- Chỉ số stay bão hoà sau 24 h: tăng lên 48 h chỉ thêm 6% số stay dài; phân mảnh và stay giả gần như không đổi. Hạ xuống 12 h làm mất 40% số stay dài (mất các đêm dài).

**⇒ Chọn max_gap = 24 h.**

## B6. Khung đêm và khung hành chính

**Định nghĩa:** không giả định trước khung giờ, mà nhìn vào chính các stay dài (bước này chỉ cần stay từ B1–B5, chưa cần place, nên làm trước place_eps):
- **Stay qua đêm:** dài 6–24 giờ và có chứa 03:00 local (3.136 stay, 81 user).
- **Stay ban ngày của ngày làm việc:** bắt đầu từ 06:00, kết thúc trước 22:00 cùng ngày, dài ≥ 3 giờ, rơi vào ngày làm việc theo lịch của đúng quốc gia
  (1.762 stay, 66 user).

Với mỗi giờ, đo % số stay của loại đó phủ giờ này. Tính theo từng user rồi lấy trung bình, để vài power user không lấn át.

**Quy tắc chọn:**
- **Khung đêm** = các giờ được ≥ **60%** số stay qua đêm phủ. Ngưỡng chặt hơn vì giờ ngủ khá đồng đều giữa mọi người, và khung đêm quyết định home:
  chỉ nên lấy phần lõi của đêm.
- **Khung hành chính** = các giờ được ≥ **40%** số stay ban ngày phủ. Ngưỡng nhẹ hơn vì giờ đến / về chỗ làm lệch nhau nhiều giữa mọi người
  (người đến 8h, người 10h); ngưỡng cao sẽ cắt mất đầu / cuối ngày làm việc của nhiều người.

**Xét (% stay phủ giờ đó):**

| Giờ | 6 | 7 | 8 | 9 | 10 | 11–16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 0–5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Stay qua đêm | 94 | 83 | **67** | 45 | 31 | 13–25 | 16 | 21 | 30 | 40 | 53 | **67** | 80 | 92–98 |
| Stay ban ngày, ngày làm việc | 3 | 8 | 22 | **42** | 57 | 66–75 | **61** | 39 | 23 | 14 | 5 | 0 | 0 | 0 |

**Output cho thấy:**
- Stay qua đêm phủ ≥ 80% các giờ 23:00–07:00. Giờ đạt ngưỡng 60% là **22:00 (67%) tới hết 08:00 (67%)**; 21:00 (53%) và 09:00 (45%) không đạt.
- Stay ban ngày phủ ≥ 57% các giờ 10:00–17:00. Giờ đạt ngưỡng 40% là **09:00 (42%) tới hết 17:00 (61%)**; 18:00 (39%) không đạt.
- Hai khung không chồng nhau.

**⇒ Chọn:**
- **Khung đêm [22, 9)**, tức 22:00–09:00, áp cho **mọi ngày**, kể cả ngày nghỉ lễ và cuối tuần.
- **Khung hành chính [9, 18)**, tức 09:00–18:00, chỉ áp cho **ngày làm việc**: ngày làm bù được tính, còn ngày nghỉ lễ rơi vào T2–T6 thì không.

## B7. Chọn place_eps

**Định nghĩa:** place_eps quá nhỏ thì một nơi bị chia thành nhiều place, giờ bị chia ra và home có thể nhảy sang nơi khác. Quá lớn thì hai nơi khác nhau
(nhà và quán đầu ngõ) bị gộp làm một. Dùng khung giờ đã chọn ở B6, đo số user có home / office, và % user có toạ độ home / office dịch > 200 m
so với place_eps liền trước.

**Xét:**

| place_eps | Place / user (median) | User có home | User có office | Home dịch so với bước trước | Office dịch so với bước trước |
| --- | --- | --- | --- | --- | --- |
| 50 m | 25 | 74 | 54 | – | – |
| 100 m | 19 | 85 | 63 | 9,5% | 13,0% |
| **200 m** | 14,5 | 88 | 76 | **2,4%** | **4,8%** |
| 300 m | 13 | 88 | 78 | 3,4% | 6,7% |
| 500 m | 11 | 89 | 75 | 4,5% | 5,3% |

**Output cho thấy:**
- 50 m chia một nơi thành nhiều place: chỉ 74 user có home, 54 user có office.
- Từ 100 lên 200 m, home và office đều ổn định nhất (2,4% và 4,8%), và số user có home đạt mức trần (88, không tăng ở 300 m).
- Từ 200 m trở lên home lại bắt đầu dịch (3,4% rồi 4,5%), vì bán kính lớn gộp nhà với các nơi gần nhà.

**⇒ Chọn place_eps = 200 m:** vùng ổn định nhất của cả home và office, cùng thang đo với D.

## B8. Cần bao nhiêu đêm / ngày làm việc?

**Định nghĩa:** với user có nhiều dữ liệu (≥ 20 đêm có giờ ở home, ≥ 20 ngày làm việc có giờ ở office), lấy home / office tính từ **toàn bộ** dữ liệu làm mốc.
Rút ngẫu nhiên k đêm (hoặc k ngày làm việc), chọn lại home / office chỉ từ giờ trong k ngày đó, rồi đo % lần trùng mốc (cùng place). Lặp 30 lần mỗi user.
Dùng khung giờ của B6 và place_eps của B7.

**Xét:**

| k | 1 | 2 | **3** | 5 | 10 |
| --- | --- | --- | --- | --- | --- |
| Home trùng mốc (48 user) | 49% | 55% | **61%** | 70% | 84% |
| Office trùng mốc (37 user) | 48% | 59% | **64%** | 70% | 80% |

**Output cho thấy:** với 1 đêm / ngày, kết quả không hơn đoán. Độ trùng tăng nhanh ở vài ngày đầu rồi chậm lại.

**⇒ Chọn min_nights = min_workdays = 3:** mốc đầu tiên mà cả hai vai trò đều trùng ≥ 60%. Dưới mốc này model abstain.
Đây là mức tối thiểu, không phải mức tin cậy cao: với 3 đêm vẫn còn khoảng 2/5 trường hợp khác với khi có đủ dữ liệu.

---

## Giả định của model

| # | Giả định | Bằng chứng | Hệ quả nếu sai |
| --- | --- | --- | --- |
| G1 | User ở yên trong khoảng không ghi khi điểm trước và sau khoảng đó cách nhau ≤ D và khoảng đó ≤ 24 h | 60% gap 4–24 h giữa hai file có hai đầu cách nhau < 0,5 km (EDA 6); B5 | User đi rồi quay lại đúng chỗ: thời gian đi bị tính là ở yên |
| G2 | Home là place có nhiều giờ nhất trong khung đêm, mọi ngày | B6 | Người làm ca đêm: home và office bị đảo |
| G3 | Office là place có nhiều giờ nhất trong khung hành chính của ngày làm việc, cách home > 200 m | B6 | Người làm việc tại nhà / không đi làm: không có office (abstain `no_distinct_office`) |
| G4 | Ngày làm việc theo lịch chính thức của quốc gia nơi stay diễn ra, có ngày làm bù | Lịch Trung Quốc đã đối chiếu tay hai kỳ Quốc khánh (EDA 10) | Lịch các nước khác (~3% số điểm) chưa đối chiếu tay |
| G5 | ≥ 3 đêm (ngày làm việc) là đủ để trả home (office) | B8 | Với 3–5 đêm, khoảng 1/3 trường hợp khác với khi có đủ dữ liệu |
| G6 | File trùng giữa các user là dữ liệu của cả hai user | Không biết ai là chủ thật (EDA 4) | Các user bản sao có cùng home / office |

## Kết quả trên `holdout` (chạy một lần, sau khi chốt tham số)

```bash
uv run python -m geolife.run --model stay_point --version 1 --split holdout
```

| | `dev` (135 user) | `holdout` (47 user) |
| --- | --- | --- |
| Số stay / stay mỗi ngày | 19.784 / 2,11 | 3.871 / 2,16 |
| Stay giả | 46,9% | 17,4% |
| Phân mảnh | 13,3% | **19,4%** |
| Stay dài ≥ 6 h | 4.829 | 632 |
| User có home / office | 88 / 76 | 25 / 18 |
| Lý do abstain home | 32 thiếu đêm, 15 không có stay đêm | 22 thiếu đêm |
| Thời gian chạy | 7,5 s | 2,0 s |

- Số stay mỗi ngày ổn định giữa hai tập.
- **Phân mảnh trên holdout cao hơn rõ (19,4% so với 13,3%)**, còn **stay giả thấp hơn nhiều (17,4% so với 46,9%)**. Holdout có ít dữ liệu mỗi user hơn (median 18 ngày so với 24) và không
  có power user, nên đây có thể là khác biệt về thiết bị / thói quen ghi chứ không phải do tham số. Nếu muốn giảm phân mảnh, đó là việc của v_2
  (ví dụ gộp hai stay liên tiếp gần nhau), không chỉnh lại v_1 dựa trên holdout.
- Holdout chỉ có 16 user có nhãn, nên tỉ lệ stay giả trên holdout có sai số lớn. Khoảng cách lớn về stay giả giữa hai tập cũng cho thấy chỉ số này phụ thuộc nhiều vào thói quen gán nhãn của từng user (ví dụ có gán `bike` / `car` trùm cả lúc đỗ hay không), thêm một lý do chỉ dùng nó để so sánh tương đối trong cùng một tập.

## Nguồn

- Li, Q., Zheng, Y., Xie, X., Chen, Y., Liu, W., Ma, W.-Y. (2008). Mining user similarity based on location history. *ACM SIGSPATIAL GIS*.
- Zheng, Y., Xie, X., Ma, W.-Y. (2010). GeoLife: A Collaborative Social Networking Service among User, Location and Trajectory. *IEEE Data Engineering Bulletin*.
