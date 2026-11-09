# dbscan v_2: cách chọn tham số

| | |
| --- | --- |
| **Model** | Như [dbscan v_1](dbscan_v1.md), chỉ khác toạ độ đại diện của ô lưới |
| **Dữ liệu** | preprocess `v_1` ([preprocess_v1.md](../preprocess_v1.md)) |
| **Tham số** | [`models/dbscan/v_2/config.yaml`](../../models/dbscan/v_2/config.yaml) |
| **Tái lập** | [`models/dbscan/v_2/tuning.ipynb`](../../models/dbscan/v_2/tuning.ipynb): mọi bảng dưới đây, chỉ chạy trên `dev` (135 user) |
| **Code** | [`clusters.py`](../../src/geolife/clusters.py) (`CELL_CENTERS`) |
| **Chỉ số** | Định nghĩa ở [evaluation.md](../evaluation.md), tính trên visit như trên stay |

| Tham số | v_2 | Khác v_1? |
| --- | --- | --- |
| cell_center | `weighted`: trung bình có trọng số thời gian của các điểm trong ô | **có** (v_1: tâm hình học của ô) |
| eps / min_time | 100 m / 240 phút | không |
| T / bridge | 20 phút / 10 phút | không |
| max_gap | 24 h | không |
| cell_m | 30 m | không |
| Khung đêm / khung hành chính | [21, 9) mọi ngày / [9, 19) ngày làm việc | không |
| min_nights / min_workdays | 2 / 2 | không |

## Khác v_1 ở đâu

Toạ độ của mỗi ô lưới, dùng để tính khoảng cách giữa các ô trong DBSCAN, là **Σ(w·lat)/Σw, Σ(w·lon)/Σw** trên các điểm trong ô
(w = số giây tới điểm kế tiếp), thay cho tâm hình học của ô. Ô chỉ gồm điểm có w = 0 (ngay trước một khoảng không ghi dài) dùng
trung bình thường của các điểm.

**Kỳ vọng:** khi điểm dồn về một góc ô, tâm có trọng số vẫn nằm đúng chỗ đó, còn tâm hình học lệch tới nửa đường chéo ô. Vì vậy
v_2 có thể dùng ô lớn hơn (ít ô hơn, chạy nhanh hơn) mà kết quả không đổi. B7 kiểm tra kỳ vọng này.

Toạ độ của visit và của place vẫn tính lại từ các điểm thật, giống v_1. Hai version chỉ khác ở **cách các ô ở rìa cụm được gom**.

Mọi bước dùng đúng định nghĩa và quy tắc chọn của v_1. Bên dưới chỉ ghi số liệu và kết luận.

---

## B1. Khoảng ứng viên của eps

Như v_1 (EDA 14, không phụ thuộc toạ độ ô): **eps ∈ {50, 100, 200, 300} m.**

## B2–B4. eps và min_time

% place rộng hơn 500 m:

| eps \ min_time | 10 | 30 | 60 | 120 | 240 | 480 |
| --- | --- | --- | --- | --- | --- | --- |
| 50 m | 17,8% | 7,4% | 4,0% | 1,9% | 1,0% | 0,7% |
| 100 m | 26,7% | 17,6% | 12,2% | 7,4% | **4,1%** | 3,4% |
| 200 m | 38,5% | 33,1% | 26,4% | 18,3% | 16,0% | 12,6% |
| 300 m | 46,0% | 39,2% | 35,7% | 30,9% | 27,0% | 23,1% |

Bảng gần như trùng v_1 (lệch ≤ 1,5 điểm % ở mọi ô). eps = 200 m và 300 m bị loại vì không đạt ≤ 5% ở bất kỳ min_time nào.

| eps / min_time | Visit / ngày | Stay giả | Phân mảnh | Visit ≥ 6 h | Place rộng (p95) |
| --- | --- | --- | --- | --- | --- |
| 50 m / 60 phút | 1,23 | 58,4% | 3,0% | 4.319 | 387 m |
| **100 m / 240 phút** | 1,16 | 58,5% | 1,6% | **5.158** | 447 m |

**⇒ Chọn eps = 100 m, min_time = 240 phút** (như v_1): nhiều visit dài hơn 19%, phân mảnh thấp hơn, stay giả gần như bằng.

## B5. T và bridge

Phân mảnh ở T = 20 phút: 5,6% (bridge = 0) → 3,2% (2 phút) → **1,6% (10 phút)** → 1,2% (30 phút). Stay giả 58,2–59,2% ở T = 10–30
phút, 61,0% ở 60 phút.

**⇒ Chọn bridge = 10 phút, T = 20 phút** (như v_1).

## B6. max_gap

Tỉ lệ quay lại đúng chỗ không phụ thuộc toạ độ ô (như v_1: đứng yên quanh 9–11% từ 24 h). Số visit dài: 3.346 (12 h) → 5.158
(24 h) → 5.453 (48 h).

**⇒ Chọn max_gap = 24 h** (như v_1).

## B7. cell_m: kiểm tra kỳ vọng của v_2

| cell_m | Phân cụm | Home trùng mốc v_2 | Office trùng mốc v_2 | Office trùng mốc v_1 |
| --- | --- | --- | --- | --- |
| 10 m | 36 s | 100% | 100% | 100% |
| 20 m | 18 s | 98,9% | 96,3% | 97,5% |
| **30 m** | 13 s | 97,9% | 95,1% | 97,5% |
| 50 m | 9 s | 94,6% | 86,4% | 91,0% |
| 100 m | 5 s | 77,8% | 62,9% | 63,2% |

*(mốc: cùng version với lưới 10 m; trùng = hai place cách nhau ≤ 200 m)*

**Output cho thấy:** kỳ vọng **không đúng**. Ô 50 m vẫn không đạt quy tắc (office 86,4%), và ở ô 20–50 m office của v_2 còn lệch mốc
nhiều hơn v_1. Một khả năng: ở ô lớn, toạ độ ô bị kéo về chỗ ghi dày trong ô, nên khoảng cách giữa các ô lân cận không còn đều, và
việc hai ô có là láng giềng hay không đổi nhiều hơn so với lưới đều. Điều này chưa được kiểm chứng.

**⇒ Chọn cell_m = 30 m** (như v_1).

## B8. Khung đêm và khung hành chính

Visit qua đêm phủ ≥ 60% các giờ 21:00 (61%) tới hết 08:00 (68%). Visit ban ngày của ngày làm việc phủ ≥ 40% các giờ 09:00 (43%) tới
hết 18:00 (44%).

**⇒ Chọn khung đêm [21, 9), khung hành chính [9, 19)** (như v_1).

## B9. min_nights / min_workdays

| k | 1 | **2** | 3 | 5 | 10 |
| --- | --- | --- | --- | --- | --- |
| Home trùng mốc | 70% | **75%** | 81% | 86% | 90% |
| Office trùng mốc | 57% | **66%** | 70% | 76% | 82% |

**⇒ Chọn min_nights = min_workdays = 2** (như v_1).

## Giả định của model

Như v_1 (G1–G4). Thêm:

| # | Giả định | Bằng chứng | Hệ quả nếu sai |
| --- | --- | --- | --- |
| G5 | Tâm có trọng số thời gian là vị trí đại diện tốt hơn của ô | Không có: B7 cho thấy nó không giúp dùng ô lớn hơn | Chỗ ghi dày (đi lại trong nhà 1 điểm / giây) kéo toạ độ ô về phía nó |

## Kết quả (chạy một lần, sau khi chốt tham số)

```bash
uv run python -m geolife.run --model dbscan --version 2 --split dev
```

```bash
uv run python -m geolife.run --model dbscan --version 2 --split holdout
```

| | `dev` (135 user) | `holdout` (47 user) |
| --- | --- | --- |
| Số visit / visit mỗi ngày | 10.837 / 1,16 | 2.269 / 1,27 |
| Stay giả | 58,5% | 19,6% |
| Phân mảnh | 1,6% | 1,9% |
| Visit ≥ 6 h | 5.158 | 795 |
| User có home / office | 93 / 83 | 33 / 23 |
| Confidence median home / office | 1,00 / 0,93 | 0,89 / 0,87 |
| Thời gian chạy | 13,8 s | 5,0 s |

So với v_1, home / office cùng place (≤ 200 m) ở 95,7% / 97,5% user trên `dev` và 97,0% / 100% trên `holdout`.

Kết quả ở `results/data_v1/dbscan_v2/{dev,holdout}/`. So sánh với stay_point làm sau.
