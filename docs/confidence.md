# Confidence của dự đoán home / office

| | |
| --- | --- |
| **Code** | [`src/geolife/confidence.py`](../src/geolife/confidence.py), được model gọi ngay sau khi chọn home / office (`StayPointModel.label`) |
| **Tham số** | Khối `confidence` trong `models_tuning/<tên>/v_<k>/config.yaml`: `n_boot: 200`, `block: week`, `seed: 0` |

Mỗi lần model dự đoán đều trả về confidence, không có bước chạy riêng. Confidence chỉ đọc bảng lát giờ và bảng place mà model
đã tạo, nên dùng được cho mọi cách tạo stay (v_1 neo điểm đầu, v_2 neo tâm).

## 1. Confidence là gì

> Nếu user được quan sát ở những tuần khác (lấy mẫu lại từ chính các tuần đã có), bao nhiêu phần trăm số lần model vẫn chọn
> **đúng place** đã dự đoán?

**Cách tính**, cho từng user:
1. **Gom theo tuần.** Từ các lát giờ, tính cho mỗi (tuần, place) số giờ và số đêm (home) hoặc số ngày làm việc (office).
   Home dùng giờ trong khung đêm của mọi ngày; office dùng giờ trong khung hành chính của ngày làm việc.
2. **Lấy mẫu lại.** Bốc lại các tuần của user, có hoàn lại, bốc đủ số tuần đang có. Làm 200 lần.
3. **Chọn lại** home / office ở mỗi lần mẫu, theo đúng luật của model:
   - place phải đủ `min_nights` đêm (`min_workdays` ngày). Tuần được bốc lặp lại thì đêm / ngày của nó cũng cộng lặp lại;
   - office phải cách home **của chính lần mẫu đó** hơn `same_place_m`;
   - chọn place nhiều giờ nhất. Không còn place nào hợp lệ thì lần đó tính là không khớp.
4. **`confidence`** = số lần chọn đúng place đã dự đoán / 200. Dự đoán bị abstain thì confidence để trống.

Lấy mẫu theo **tuần** chứ không theo ngày vì các ngày trong cùng tuần thường giống nhau (cùng một đợt công tác, cùng một tuần nghỉ):
bốc từng ngày sẽ coi chúng như bằng chứng độc lập và cho confidence lạc quan quá mức.

Mỗi user có bộ sinh số ngẫu nhiên riêng, lấy từ `seed` và mã user. Cùng dữ liệu luôn cho cùng confidence, và confidence của một
user không phụ thuộc vào việc chạy chung với những user nào.

**Hai cột chẩn đoán** đi kèm, tính trên toàn bộ dữ liệu, không gộp vào confidence. Chúng giúp đọc vì sao confidence thấp:

| Cột | Định nghĩa | Thấp nghĩa là |
| --- | --- | --- |
| `regularity` | Số đêm (ngày làm việc) ở place được chọn / số đêm (ngày làm việc) user có dữ liệu trong khung giờ đó | User không về place này đều đặn |
| `margin` | (giờ place thứ nhất − giờ place thứ hai) / giờ place thứ nhất, trong các place đủ điều kiện; chỉ có một place thì = 1 | Có một place khác gần như ngang ngửa |

## 2. Ví dụ

Hai user tự tạo, mỗi user có 4 tuần dữ liệu, vai trò home, `min_nights` = 3. Số liệu dưới đây chạy bằng chính hàm trong code.

### Ví dụ 1: có một tuần về quê

| Tuần | Place 0 (nhà riêng) | Place 1 (nhà bố mẹ) |
| --- | --- | --- |
| T1 | 50 h / 6 đêm | 8 h / 1 đêm |
| T2 | 45 h / 5 đêm | 16 h / 2 đêm |
| T3 (về quê) | 10 h / 1 đêm | 40 h / 5 đêm |
| T4 | 55 h / 6 đêm | 0 |
| **Tổng** | **160 h / 18 đêm** | **64 h / 8 đêm** |

Cả hai place đủ 3 đêm, place 0 nhiều giờ hơn, nên model chọn home = **place 0**.

Một vài lần lấy mẫu lại (mỗi lần bốc 4 tuần, có hoàn lại):

| Lần | Tuần bốc được | Giờ place 0 | Giờ place 1 | Chọn | Khớp? |
| --- | --- | --- | --- | --- | --- |
| 1 | T1, T2, T3, T4 | 160 | 64 | 0 | ✓ |
| 2 | T4, T4, T2, T1 | 205 | 24 | 0 | ✓ |
| 3 | T3, T3, T1, T2 | 115 | 104 | 0 | ✓ (sát nút) |
| 4 | T3, T3, T2, T2 | 110 | 112 | 1 | ✗ |
| 5 | T3, T3, T3, T1 | 80 | 128 | 1 | ✗ |

Place 0 chỉ thua khi tuần về quê bị bốc từ 3 lần trở lên, hoặc bốc 2 lần cùng với 2 lần T2. Duyệt hết 4⁴ = 256 cách bốc thì
place 0 thắng **92,6%**; 200 lần lấy mẫu trong code cho **0,905**. `margin` = (160 − 64) / 160 = 0,6.

### Ví dụ 2: sống luân phiên hai nơi

| Tuần | Place 0 | Place 1 |
| --- | --- | --- |
| T1 | 45 h / 5 đêm | 15 h / 2 đêm |
| T2 | 20 h / 2 đêm | 40 h / 5 đêm |
| T3 | 40 h / 5 đêm | 20 h / 2 đêm |
| T4 | 25 h / 3 đêm | 35 h / 4 đêm |
| **Tổng** | **130 h / 15 đêm** | **110 h / 13 đêm** |

Model vẫn chọn place 0, nhưng chỉ hơn 20 h. Bốc thêm một lần T2 hoặc T4 là đủ để place 1 thắng. Duyệt hết 256 cách bốc thì
place 0 thắng **70,3%**; code cho **0,73**. `margin` = 20 / 130 = 0,15.

Hai user có cùng dự đoán "home = place 0" và cùng 4 tuần dữ liệu, nhưng confidence cho thấy dự đoán thứ hai mong manh hơn nhiều.

### Office

Tính giống hệt, với giờ hành chính của ngày làm việc. Khác một điểm: trong mỗi lần mẫu, các place nằm trong `same_place_m`
quanh home **của lần mẫu đó** bị loại khỏi ứng viên office. Vì vậy home không chắc chắn cũng kéo confidence của office xuống.

## 3. Kết quả

Phân vị của confidence trên các dự đoán (không tính abstain), từ `metrics.json`:

| | Home p10 / p25 / p50 | Office p10 / p25 / p50 |
| --- | --- | --- |
| v_1 `dev` | 0,60 / 0,75 / 0,93 | 0,38 / 0,64 / 0,88 |
| v_2 `dev` | 0,68 / 0,77 / 0,93 | 0,42 / 0,64 / 0,87 |
| v_1 `holdout` | 0,51 / 0,55 / 0,75 | 0,48 / 0,54 / 0,65 |
| v_2 `holdout` | 0,54 / 0,60 / 0,85 | 0,45 / 0,53 / 0,62 |

- Office có confidence thấp hơn home: ít ngày làm việc được ghi hơn, và phụ thuộc thêm vào home.
- `holdout` thấp hơn `dev` vì user `holdout` có ít dữ liệu hơn (median 18 ngày so với 24), không phải vì model kém hơn.
- Thời gian tính confidence trên `dev` là khoảng 0,1 s, rất nhỏ so với 7–10 s của toàn bộ lần chạy.

## 4. Output

`predictions.csv` của mỗi lần chạy có thêm ba cột `confidence`, `regularity`, `margin`. Các cột cũ (place, toạ độ, lý do abstain)
không đổi so với trước khi có confidence. `metrics.json` có thêm phân vị confidence trong phần `home_office`.

## 5. Giới hạn

- **Confidence không phải xác suất đúng.** GeoLife không có nhãn home / office, nên không kiểm được confidence 0,95 có nghĩa là
  đúng 95% hay không. Nó chỉ đo độ ổn định trong dữ liệu đã thấy: dùng để xếp hạng / lọc dự đoán, và không biết trước việc user
  chuyển nhà / đổi chỗ làm sau đó.
- Chỉ đo độ ổn định với những tuần đã có. User có ít tuần (vd. 2 tuần) cho confidence dao động mạnh; user chỉ có 1 tuần thì
  mọi lần mẫu đều giống nhau và confidence = 1, dù rất ít bằng chứng. Luật `min_nights` / `min_workdays` của model chặn bớt
  trường hợp này, và `regularity` / số ngày (`days`) nên được đọc kèm.
- Không phân biệt giờ có điểm GPS thật với giờ suy ra trong khoảng không ghi bên trong stay (đến `max_gap`).
- Không bắt được sai có hệ thống: ví dụ user làm ca đêm có "home" ổn định ở chỗ làm.
