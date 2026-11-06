# stay_point v_2: neo động (tâm), cách chọn tham số

| | |
| --- | --- |
| **Model** | GPS → stay (**neo động**) → place → home / office |
| **Dữ liệu** | preprocess `v_1` ([preprocess_v1.md](../preprocess_v1.md)) |
| **Tham số** | [`models/stay_point/v_2/config.yaml`](../../models/stay_point/v_2/config.yaml) |
| **Tái lập** | [`models/stay_point/v_2/tuning.ipynb`](../../models/stay_point/v_2/tuning.ipynb): mọi bảng / hình dưới đây, chỉ chạy trên `dev` (135 user) |
| **Code** | [`stays.py`](../../src/geolife/stays.py) (`_stays_centroid_anchor`), các bước sau như v_1; phép đo tuning: [`tuning.py`](../../src/geolife/tuning.py) |
| **Chỉ số** | Định nghĩa ở [evaluation.md](../evaluation.md) |
| **Quy trình chọn** | Cùng các bước B1–B8 và **cùng quy tắc chọn** với [stay_point_v1.md](stay_point_v1.md). Quy tắc được giữ nguyên, không đổi theo kết quả của v_2 |

| Tham số | Giá trị | Bước |
| --- | --- | --- |
| anchor | `centroid` | thiết kế |
| T | 20 phút | B3 |
| D | 200 m | B1, B4 |
| max_gap | 24 h | B5 |
| Khung đêm / khung hành chính | [22, 9) mọi ngày / [9, 18) ngày làm việc | B6 |
| place_eps | **300 m** | B7 |
| min_nights / min_workdays | 3 / 3 | B8 |

## Model làm gì

Giống v_1 ở mọi bước, trừ cách tìm stay.

**v_1 (neo cố định):** neo là điểm đầu `i` của stay. Điểm `j` được nhận khi `d(p_i, p_j) ≤ D`.

**v_2 (neo động):** neo là **tâm của các điểm đã nhận vào stay**: trung bình lat, lon, mỗi điểm nặng như nhau. Tâm được tính lại **sau mỗi điểm được nhận**.

```
i = 0
while i < n:
    tổng_lat, tổng_lon, k = lat[i], lon[i], 1            # neo ban đầu = điểm i
    j = i + 1
    while j < n và t[j] − t[j−1] ≤ max_gap và d((tổng_lat / k, tổng_lon / k), p_j) ≤ D:
        cộng p_j vào tổng; k += 1; j += 1                # neo dịch theo điểm mới
    nếu t[j−1] − t[i] ≥ T: ghi stay (i, j−1); i = j
    ngược lại: i += 1
```

- **Thời gian không đổi:** stay bắt đầu ở điểm đầu `i` và T đo từ đó, như v_1. Chỉ có toạ độ của neo là động.
- **Toạ độ của stay** là trung bình các điểm của nó (như v_1). Với v_2, giá trị này trùng với neo cuối cùng.
- Cắt stay tại khoảng không ghi > max_gap, cách lùi `i += 1`, độ phức tạp: như v_1. Cập nhật tâm tốn O(1) mỗi bước nhờ cộng dồn.

**Hành vi đã biết (chưa xử lý ở v_2):**
- Khi điểm đầu là một fix lệch ở mép đám mây dao động, v_1 đặt neo sai và chẻ một lần dừng thành hai. v_2 kéo neo về giữa nên không chẻ.
- Khi user đi chậm theo một đường thẳng, tâm đi theo sau khoảng nửa quãng, nên stay có thể dài tới ~2D (v_1 tối đa D).

---

## B1. Khoảng ứng viên của D

Dùng lại nguyên B1 của v_1, vì đây là dữ liệu thô, không phụ thuộc cách đặt neo. Dao động khi đứng yên (EDA 14): bán kính p90 có p50 = 16 m,
p90 = 71 m, p95 = 149 m, p99 = 746 m.

**⇒ Ứng viên D ∈ {50, 100, 200, 300} m.**

## B2. Khả năng tạo stay khi thay đổi D và T

**Định nghĩa:** số stay trên mỗi (user, ngày) có dữ liệu. max_gap giữ ở 24 h.

**Xét:** số stay / ngày:

| D \ T | 5' | 10' | 20' | 30' | 60' |
| --- | --- | --- | --- | --- | --- |
| 50 m | 3,53 | 1,94 | 1,11 | 0,82 | 0,51 |
| 100 m | 4,43 | 2,55 | 1,60 | 1,25 | 0,83 |
| 200 m | 5,25 | 3,08 | 2,08 (19.507) | 1,70 | 1,21 |
| 300 m | 4,98 | 3,26 | 2,27 | 1,91 | 1,42 |

**Output cho thấy:**
- Số stay nhạy với T hơn nhiều so với D: tăng T từ 5 lên 60 phút làm số stay / ngày giảm 3,5–7 lần.
- Ở T = 5 phút có 3,5–5,2 stay mỗi ngày: quá nhiều so với nhịp sống bình thường.
- Ở T = 5, D = 300 tạo **ít** stay hơn D = 200 (4,98 so với 5,25). Neo tâm đi theo các điểm, nên với bán kính lớn, nhiều mảnh ngắn
  được nối thành một stay dài hơn.

**⇒ Chọn T trước (B3), rồi mới chọn D (B4).**

## B3. Chọn T: tỉ lệ stay giả

**Định nghĩa:** như v_1. Stay giả là stay nằm trong vùng có nhãn (≥ 50% số điểm có nhãn) mà ≥ 50% số điểm mang nhãn di chuyển.
**Quy tắc chọn:** T lớn nhất trước khi stay giả bắt đầu tăng.

**Xét:**

| T | 5' | 10' | 20' | 30' | 60' |
| --- | --- | --- | --- | --- | --- |
| % stay giả, D = 100 m | 44,1% | 43,0% | **42,1%** | 44,1% | 47,6% |
| % stay giả, D = 200 m | 50,0% | 46,8% | **47,3%** | 48,8% | 52,8% |

**Output cho thấy:**
- Mức stay giả cao (42–53%) vì nhãn nhiễu, nên chỉ dùng để so sánh giữa các T.
- Từ T = 10 đến T = 20, stay giả gần như không đổi: chênh dưới 1 điểm %.
- Từ T = 30 trở đi, stay giả tăng rõ.

**⇒ Chọn T = 20 phút.**

## B4. Chọn D: phân mảnh, stay giả và stay dài

**Định nghĩa:** như v_1, với T = 20.

**Xét:**

| D | Stay / ngày | Phân mảnh | Stay giả | Stay dài ≥ 6 h | User có home / office |
| --- | --- | --- | --- | --- | --- |
| 50 m | 1,11 | 13,1% | 41,2% | 1.624 | – |
| 100 m | 1,60 | 11,4% | 42,1% | 2.942 (+81%) | 77 / 60 |
| **200 m** | 2,08 | 8,3% | 47,3% | **4.728 (+61%)** | 87 / 78 |
| 300 m | 2,27 | 5,7% | 51,5% | 5.710 (+21%) | 93 / 77 |

**Output cho thấy:**
- Phân mảnh giảm mạnh khi tăng D: từ 13,1% xuống 5,7% khi D đi từ 50 lên 300 m.
- Stay giả gần như không đổi tới 100 m, rồi tăng 4–5 điểm % mỗi bước.
- Số stay dài tăng mạnh tới 200 m (+61%), sau đó chậm lại (+21%).

**⇒ Chọn D = 200 m:** đổi 5,1 điểm % stay giả lấy thêm hơn một nửa số stay dài. Lên 300 m thì lợi ích về stay dài nhỏ dần, office không tăng,
trong khi stay giả vẫn tăng cùng mức.

## B5. Chọn max_gap

**Định nghĩa:** như v_1. Bảng "quay lại đúng chỗ sau khoảng không ghi" chỉ dùng dữ liệu điểm, không phụ thuộc neo, nên trùng v_1:
72% (< 1 h), 44% (6–12 h), 32% (12–24 h), 22% (24–48 h), rồi đứng yên quanh 18% (mức "tình cờ").

**Xét:**

| max_gap | 6 h | 12 h | **24 h** | 48 h | 72 h | không giới hạn |
| --- | --- | --- | --- | --- | --- | --- |
| Stay / ngày | 1,65 | 1,91 | 2,08 | 2,11 | 2,12 | 2,13 |
| Phân mảnh | 9,5% | 8,6% | 8,3% | 8,3% | 8,3% | 8,3% |
| Stay giả | 42,1% | 45,8% | 47,3% | 47,2% | 47,2% | 47,2% |
| Stay dài ≥ 6 h | 216 | 2.863 | 4.728 | 5.016 | 5.087 | 5.224 |

**Output cho thấy:**
- Chỉ số stay bão hoà sau 24 h: lên 48 h chỉ thêm 6% số stay dài, còn phân mảnh và stay giả không đổi.
- Hạ xuống 12 h làm mất 39% số stay dài.

**⇒ Chọn max_gap = 24 h.**

## B6. Khung đêm và khung hành chính

**Định nghĩa và quy tắc:** như v_1.
- Khung đêm = các giờ được ≥ 60% số stay qua đêm phủ (3.044 stay, 80 user).
- Khung hành chính = các giờ được ≥ 40% số stay ban ngày của ngày làm việc phủ (1.741 stay, 63 user).

**Xét (% stay phủ giờ đó):**

| Giờ | 7 | 8 | 9 | 10 | 17 | 18 | 21 | 22 | 23 | 0–6 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Stay qua đêm | 83 | **67** | 45 | 31 | 17 | 22 | 54 | **68** | 81 | 92–98 |
| Stay ban ngày, ngày làm việc | 8 | 24 | **45** | 61 | **62** | 39 | 5 | 0 | 0 | 0–3 |

**Output cho thấy:**
- Các giờ đạt ngưỡng 60% của stay qua đêm kéo dài từ 22:00 tới hết 08:00.
- Các giờ đạt ngưỡng 40% của stay ban ngày kéo dài từ 09:00 tới hết 17:00.

**⇒ Chọn:** khung đêm **[22, 9)**, áp cho mọi ngày; khung hành chính **[9, 18)**, chỉ áp cho ngày làm việc.

## B7. Chọn place_eps

**Định nghĩa và quy tắc:** như v_1. Chọn ở chỗ thay đổi so với giá trị liền trước nhỏ nhất cho cả home và office, khi số user có home đã chạm trần.

**Xét:**

| place_eps | Place / user | User có home | User có office | Home dịch so với bước trước | Office dịch so với bước trước |
| --- | --- | --- | --- | --- | --- |
| 50 m | 26 | 76 | 52 | – | – |
| 100 m | 20 | 82 | 60 | 3,9% | 7,7% |
| 200 m | 16 | 86 | 75 | 6,1% | 8,5% |
| **300 m** | 14 | 87 | 78 | **4,7%** | **5,4%** |
| 500 m | 11 | 88 | 73 | 5,7% | 8,2% |

**Output cho thấy:**
- Bước 100 → 200 m chưa ổn định: home dịch 6,1%, office dịch 8,5%.
- Bước 200 → 300 m ổn định nhất cho cả hai vai trò, và số user có home đã chạm trần (86 → 87 → 88).
- Lên 500 m thì cả hai lại dịch nhiều hơn.

**⇒ Chọn place_eps = 300 m.** Đây là tham số duy nhất (ngoài `anchor`) có giá trị khác v_1. Lý do: tâm của từng stay phụ thuộc vào các điểm
mà stay đó gom được, nên các stay của cùng một nơi nằm tản hơn quanh nơi đó, và cần bán kính gom lớn hơn để gom chúng lại.

## B8. Cần bao nhiêu đêm / ngày làm việc?

**Định nghĩa và quy tắc:** như v_1, dùng các tham số đã chọn ở B1–B7. Chọn k nhỏ nhất mà cả home và office đều trùng mốc ≥ 60%.

**Xét:**

| k | 1 | 2 | **3** | 5 | 10 |
| --- | --- | --- | --- | --- | --- |
| Home trùng mốc (49 user) | 50% | 59% | **64%** | 74% | 85% |
| Office trùng mốc (36 user) | 50% | 61% | **67%** | 72% | 81% |

**⇒ Chọn min_nights = min_workdays = 3.** Với k = 2, home chỉ trùng 59%.

---

## Giả định của model

Như [stay_point_v1.md](stay_point_v1.md) (G1–G6), cộng thêm:

| # | Giả định | Bằng chứng | Hệ quả nếu sai |
| --- | --- | --- | --- |
| G7 | Tâm theo số điểm là vị trí đại diện của stay đang hình thành | Đơn giản, nhất quán với toạ độ stay của v_1 | Chỗ ghi dày (vd. đi lại trong nhà, 1 điểm/giây) kéo tâm về phía nó hơn các khoảng không ghi dài chỉ có 2 điểm |
| G8 | Điểm đi chậm nằm trong D quanh tâm vẫn là "đang ở yên" | Không chống neo trôi ở v_2 | Đi bộ chậm / kẹt xe có thể bị gộp thành stay dài tới ~2D |

## Kết quả (chạy một lần, sau khi chốt tham số)

```bash
uv run python -m geolife.run --model stay_point --version 2 --split dev
```

```bash
uv run python -m geolife.run --model stay_point --version 2 --split holdout
```

| | `dev` (135 user) | `holdout` (47 user) |
| --- | --- | --- |
| Số stay / stay mỗi ngày | 19.507 / 2,08 | 3.719 / 2,08 |
| Stay giả | 47,3% | 19,1% |
| Phân mảnh | 8,3% | 12,2% |
| Stay dài ≥ 6 h | 4.728 | 631 |
| User có home / office | 87 / 78 | 25 / 19 |
| Thời gian chạy | 10,6 s | 2,9 s |

Kết quả ở `results/data_v1/stay_point_v2/{dev,holdout}/`. So sánh và đánh giá với v_1 làm sau.
