# Quy ước đánh giá và các giả định

GeoLife **không có nhãn home/office**. Tài liệu này cố định cách đánh giá **trước khi xây model**, để kết quả sau này không bị chọn lọc theo hướng có lợi. Nội dung gồm:

- cái gì được coi là "đúng";
- đánh giá trên tập user nào;
- dùng chỉ số nào;
- confidence nghĩa là gì và giới hạn của nó ở đâu;
- các giả định đã đặt ra.

Mỗi quy ước đều ghi lý do và bằng chứng. Số liệu lấy từ:
- [EDA findings](eda_findings.md), ký hiệu "EDA mục n";
- [`preprocess/v_1/preprocess.ipynb`](../preprocess/v_1/preprocess.ipynb), ký hiệu "PP-n" (bước n). Quy tắc làm sạch dữ liệu nằm ở [preprocess_v1.md](preprocess_v1.md).

Các model được so sánh: **B0** (lưới ô ~200 m theo khung giờ, không dùng stay-point), **B1** (stay-point + rule), **M1** (clustering hồ sơ thời gian của place).

---

## 1. Định nghĩa bài toán

| Khái niệm | Định nghĩa | Lý do / bằng chứng |
| --- | --- | --- |
| **Đêm / ngày làm việc có dữ liệu** | Đêm có ít nhất một điểm GPS trong khung 22:00–06:00 local (gán cho ngày bắt đầu); ngày làm việc có ít nhất một điểm trong khung 09:00–18:00. Đây là cột `nights`, `workdays` trong `users.parquet` | Cùng định nghĩa ở EDA mục 12 và PP-8. Biết được trước khi chạy model, nên dùng chung cho tier, abstain và confidence |
| **Stay** | Đoạn liên tiếp trong chuỗi điểm của user, các điểm nằm trong bán kính D = 200 m quanh điểm đầu và kéo dài ≥ T = 20 phút. Chạy trên **toàn chuỗi của user**, không chạy riêng từng file. Bỏ stay có khoảng không ghi bên trong > 48 h | Thuật toán của Li et al. (2008). Chạy trên toàn chuỗi vì phần lớn thời gian dừng nằm trong khoảng không ghi giữa hai file (EDA mục 6, mục 17). D, T: EDA mục 20. max_gap: EDA mục 21 |
| **Place** | Cụm các stay của cùng user, gom bằng DBSCAN (haversine, eps = 200 m) | Cùng thang đo với D; dao động GPS khi đứng yên có p95 = 149 m (EDA mục 16) |
| **Home** | Place có nhiều giờ stay nhất trong **khung đêm 22:00–06:00 local** | Khung 22–06 nằm trong lõi của các stay qua đêm (EDA mục 22) |
| **Office** | Place **khác home** có nhiều giờ stay nhất trong **khung 09:00–18:00 của ngày làm việc**, và có stay ở đó trong **≥ 3 ngày làm việc khác nhau**. Ngày làm việc theo lịch chính thức của Trung Quốc | Khung 09–18 khớp giờ của stay ban ngày (EDA mục 22). Lịch chính thức đổi trạng thái của gần 1/10 số điểm so với T2–T6 (EDA mục 11). Office ứng viên chỉ có 1–2 ngày thì 1/5 là chuyến đi cách home > 50 km; từ 3 ngày tỉ lệ này còn 5–8% (EDA mục 24) |
| **Abstain** | Không trả home khi user có < 3 đêm có dữ liệu; không trả office khi user có < 3 ngày làm việc có dữ liệu, hoặc không có place nào thoả điều kiện office. Kết quả là `null` kèm lý do (`insufficient_nights`, `insufficient_workdays`, `no_distinct_office`), không phải một dự đoán có confidence thấp | Với 1–2 đêm, home tìm được chỉ trùng đáp án 41–52%; từ 3 đêm mới đạt 60% (EDA mục 23). Gần 1/3 user ở home trong phần lớn giờ hành chính, nên "không có office tách khỏi nhà" là kết quả hợp lệ, không phải lỗi (EDA mục 24) |

B0 không có stay. B0 dùng cùng khung giờ, cùng lịch và cùng quy tắc abstain; "place" của B0 là ô lưới.

**Đơn vị đánh giá:** một cặp (user, vai trò), với vai trò là home hoặc office. Model trả về toạ độ. Hai dự đoán được coi là cùng một chỗ khi cách nhau ≤ 200 m.

## 2. Tập dữ liệu dùng cho đánh giá

Cách chia tập được tạo tự động trong PP-8 và lưu ở `data/preprocess/v_1/split.json`.

| Tập | Nội dung | Được dùng để |
| --- | --- | --- |
| `dev` | 131 user, 103 nhóm | Chỉnh ngưỡng và rule, fit clustering (M1), debug. Được xem tuỳ ý |
| `holdout` | 51 user, 45 nhóm | Chỉ chạy model một lần, sau khi đã chốt tham số trên `dev` |
| `manual_eval` (nằm trong holdout) | 28 user: 14 tier A + 14 tier B | Đánh giá thủ công. Danh sách được **cố định trước khi xây model** |

Lý do của từng quy ước:

- **Chia theo nhóm user, không chia theo từng user.** Khoảng 12% dữ liệu là file chép y hệt giữa các user, nối 52 user thành 18 nhóm (EDA mục 4). Nếu chia theo từng user, cùng một trajectory sẽ nằm cả ở `dev` lẫn `holdout`.
- **Ép nhóm lớn nhất vào `dev`.** Nhóm này có 15 user, gồm các power user 128, 153, 163, và chiếm khoảng 1/4 số điểm (EDA mục 4). Nếu nhóm này rơi vào holdout, kết quả đánh giá sẽ phản ánh vài người thay vì cả tập.
- **Phân tầng theo tier.** Tier tính từ số đêm và số ngày làm việc có dữ liệu:
  - A: ≥ 10 đêm và ≥ 10 ngày làm việc (64 user);
  - B: ≥ 3 và ≥ 3 (43 user);
  - C: còn lại (75 user).

  Mốc 3 là mức tối thiểu để home tìm được trùng đáp án quá nửa số lần. Mốc 10 là chỗ đường cong bắt đầu đi ngang: 76% ở 10 đêm, 81% ở 15–20 đêm (EDA mục 23). Phân tầng giúp holdout có đủ user đánh giá được.
- **Mẫu thủ công không chọn tier C và không chọn user có > 50% điểm là bản sao.** Tier C phần lớn sẽ abstain. User bản sao thì trùng kết quả với user khác, nên sẽ bị đếm hai lần.
- **Chọn mẫu ngẫu nhiên với seed cố định (42)** theo thứ tự ưu tiên tier A rồi tới B. Không ai chọn tay user nào.

## 3. Quy trình đánh giá thủ công

Với mỗi user trong `manual_eval`, người chấm xem một bản đồ OpenStreetMap. Dữ liệu GeoLife dùng hệ WGS84 nên khớp trực tiếp với OSM. Bản đồ AMap/Baidu thì lệch 300–700 m (EDA mục 8), nên **không được dùng**.

Bản đồ gồm:
- toàn bộ stay của user, tô màu theo giờ local và đánh dấu ngày làm việc / ngày nghỉ;
- các dự đoán home/office của **mọi model** (B0, B1, M1), gán nhãn ẩn danh (X, Y, Z) và xáo thứ tự theo từng user. Người chấm không biết dự đoán nào thuộc model nào, nên việc so sánh không bị thiên vị.

Người chấm gán cho mỗi dự đoán một trong ba nhãn:

| Nhãn | Home | Office |
| --- | --- | --- |
| **Đúng** | Khu dân cư hoặc ký túc xá theo OSM (`landuse=residential`, `building=apartments/dormitory`…). User có stay qua đêm ở đây trong nhiều đêm khác nhau | Toà văn phòng, khuôn viên trường hoặc viện nghiên cứu. User có mặt ở đây ban ngày, lặp lại qua nhiều ngày làm việc |
| **Sai** | Rõ ràng không phải nơi ở: sân bay, ga tàu, khách sạn khi đi du lịch, văn phòng, đường giao thông | Rõ ràng không phải nơi làm việc: nhà, trung tâm thương mại, ga, sân bay |
| **Không xác định** | Bằng chứng không đủ, hoặc có nhiều nơi ở hợp lý (ví dụ chuyển nhà giữa kỳ) | Như cột bên trái |

Với office trả về `null` (`no_distinct_office`), người chấm cũng gán nhãn: **Đúng** khi bản đồ cho thấy user không có nơi nào ngoài home được lặp lại ban ngày; **Sai** khi có một nơi như vậy mà model bỏ qua.

Ghi chép được lưu thành bảng gồm user, vai trò, model ẩn danh, nhãn, lý do một dòng và ảnh chụp bản đồ. Bảng này đi kèm báo cáo, nên người khác chấm lại được.

**Giới hạn:**
- Chỉ có một người chấm.
- Người chấm biết đây là dữ liệu MSRA, nên biết trước khu Haidian có nhiều văn phòng (EDA mục 8).
- Nếu có người chấm thứ hai thì báo thêm Cohen's κ.

## 4. Chỉ số

| Chỉ số | Công thức | Tập | Ý nghĩa và giới hạn |
| --- | --- | --- | --- |
| **Precision thủ công** | Đúng / (Đúng + Sai), tính riêng cho từng model × vai trò | `manual_eval` | Chỉ số chính. Với n ≤ 28, kết quả luôn báo kèm **khoảng tin cậy Wilson 95%**. Ví dụ 22/28 cho khoảng [0,60; 0,90], nên hai model chỉ khác nhau thật khi hai khoảng ít chồng lấn |
| Tỉ lệ không xác định | Không xác định / tổng | `manual_eval` | Báo cáo riêng, không gộp vào phần sai |
| **Coverage** | % user có dự đoán (không abstain) | holdout | Một model abstain nhiều thì precision tự nhiên cao hơn, nên luôn báo hai chỉ số này cùng nhau |
| Độ ổn định theo thời gian | % user có home ở nửa đầu và nửa sau thời gian trùng nhau (≤ 200 m) | holdout | Proxy không cần nhãn. Mốc tham chiếu với cách tìm home ở EDA: 60,5% cho mọi user, 63,5% cho user có ≥ 10 đêm (EDA mục 23). Chỉ số này đo tính nhất quán, không đo độ đúng: một model luôn chọn cùng một chỗ sai vẫn đạt điểm ổn định cao |
| Độ đồng thuận giữa các model | % user mà hai model cho cùng một chỗ, tính từng cặp B0–B1, B1–M1, B0–M1 | holdout | Chỗ các model bất đồng là chỗ nên ưu tiên chấm thủ công |
| Sanity check theo nhãn phương tiện | % giờ ở home/office dự đoán rơi vào đoạn có nhãn phương tiện cơ giới | user có nhãn | Kết quả phải gần 0. Nhãn phương tiện không phải nhãn home/office, chỉ bắt được lỗi thô |

## 5. Confidence: định nghĩa và giới hạn

Confidence được tính **sau khi model đã chọn chỗ**, bằng cùng một công thức cho cả B0, B1 và M1. Nhờ vậy, confidence của các model so sánh được với nhau, và không phụ thuộc vào cách bên trong của từng model.

```
conf_home = share × support
  share   = số giờ stay trong khung đêm nằm trong 200 m quanh home dự đoán
            / tổng số giờ stay trong khung đêm của user                 (độ tập trung, 0–1)
  support = min(1, số đêm có dữ liệu / 10)                              (lượng bằng chứng, 0–1)
```

Office dùng cùng công thức, thay giờ đêm bằng giờ hành chính và thay số đêm bằng số ngày làm việc có dữ liệu. Giờ stay lấy từ bảng stay của B1 (mục 1), dùng chung cho mọi model.

**Lý do chọn hai thành phần:**
- **share** cao nghĩa là có một nơi áp đảo về số giờ. Share thấp nghĩa là user có nhiều chỗ ngủ: đi công tác, ký túc xá cộng nhà riêng. Với cách tìm home ở EDA, home chiếm median 68% số giờ đêm (EDA mục 19).
- **support** dùng cùng đơn vị với tier và abstain (mục 1). Nó bão hoà ở 10 đêm vì từ 10 đêm trở đi, thêm dữ liệu chỉ làm tỉ lệ tìm đúng home tăng thêm khoảng 5 điểm % (EDA mục 23).

**Giới hạn, cần ghi rõ khi báo cáo:**
1. **Đây không phải xác suất đúng.** Không có nhãn thì không thể calibrate. Câu "conf = 0,8" không có nghĩa là đúng 80% số lần.
2. Confidence đo mức nhất quán **bên trong dữ liệu của chính user đó**. Nếu dữ liệu sai một cách nhất quán, confidence vẫn cao. Ví dụ: user chỉ bật GPS ở ký túc xá trong một kỳ thực tập.
3. Mốc 10 và phép nhân hai thành phần là lựa chọn thiết kế, có bằng chứng ở EDA mục 23 nhưng không được tối ưu hoá. Với office, đường cong vẫn còn tăng sau 10 ngày, nên support của office bão hoà hơi sớm.
4. Cách kiểm tra duy nhất có sẵn là **tính đơn điệu**: trên `manual_eval`, precision ở nhóm confidence cao phải ≥ precision ở nhóm confidence thấp. Với n = 28, phép kiểm tra này chỉ phát hiện được sai lệch lớn.

## 6. Các giả định đã đặt ra

| # | Giả định | Bằng chứng | Rủi ro nếu sai |
| --- | --- | --- | --- |
| G1 | Timestamp trong `.plt` là UTC | Theo UTC, đỉnh hoạt động rơi vào 0–2h. Đổi sang giờ local thì đỉnh về 8–9h và 17–19h, khớp nhịp đi làm (EDA mục 7) | Mọi khung giờ lệch 8 tiếng |
| G2 | Toạ độ là WGS84 | Header file ghi WGS 84. Khi vẽ, quỹ đạo khớp đường của OSM (EDA mục 8) | Lệch 300–700 m nếu thực tế là GCJ-02 |
| G3 | Mỗi user có **một** home và **một** office (hoặc không có office) trong toàn bộ thời gian | Kể cả user có ≥ 10 đêm, home ở hai nửa thời gian chỉ trùng 63,5%; tỉ lệ tìm đúng home đi ngang ở khoảng 81% chứ không lên 100% (EDA mục 23) | Bỏ sót trường hợp chuyển nhà, đổi việc hoặc có hai nơi ngủ. Đây là giới hạn đã biết. Hướng mở rộng: tính home theo từng giai đoạn |
| G4 | Giờ làm việc là 09–18 vào ngày làm việc chính thức. Người làm ca không theo khung này | EDA mục 22 | Office của người làm đêm sẽ bị nhầm thành home |
| G5 | Khoảng không ghi ≤ 48 h mà user xuất hiện lại trong 200 m thì user đã ở yên chỗ đó trong suốt khoảng đó | Gap càng dài càng ít thông tin, tới 48 h thì bằng mức nền. Đổi max_gap trong 24–72 h làm home đổi ở khoảng 1/10 user (EDA mục 21) | Ước lượng thừa thời gian ở home nếu user đi đâu đó rồi về mà không bật GPS |
| G6 | File trùng giữa các user là cùng một dữ liệu. Không xác định được chủ thật nên **giữ ở cả hai user** | EDA mục 4 | Hai user có cùng home. Chỉ ảnh hưởng tới user có tỉ lệ trùng cao, nên các user này không nằm trong mẫu thủ công |
| G7 | Nhãn phương tiện chỉ dùng cho sanity check, không dùng làm nhãn train | Chỉ 69/182 user có nhãn. Các đoạn nhãn dài và thô, kể cả lúc đỗ xe (EDA mục 14, mục 20) | — |
| G8 | Điểm nằm ngoài Trung Quốc dùng quy tắc T2–T6, không áp lịch nghỉ lễ của nước sở tại | Chỉ khoảng 3% số điểm ở ngoài Trung Quốc (EDA mục 7) | Ngày lễ ở Mỹ/châu Âu bị coi là ngày làm việc. Ảnh hưởng nhỏ |

## Nguồn

- Li, Q., Zheng, Y., Xie, X., Chen, Y., Liu, W., Ma, W.-Y. (2008). [Mining user similarity based on location history](https://dl.acm.org/doi/10.1145/1463434.1463477). ACM SIGSPATIAL GIS. Thuật toán stay-point.
