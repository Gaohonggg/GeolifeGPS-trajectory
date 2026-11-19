# Cỡ task: số đo RAM và thời gian

Tài liệu này đo API dưới giới hạn CPU / RAM giống một ECS task để chọn cỡ task. Đo ngày 2026-11-16, commit `3f3e739`.

## Cách đo

| | |
| --- | --- |
| **Script** | `scripts/measure_sizing.py` |
| **Image** | `geolife-api:local` (arm64), mỗi cấu hình chạy một container mới với `--cpus`, `--memory`, không cho swap |
| **Máy** | Docker Desktop trên Apple Silicon (VM 12 CPU, 12,5 GB RAM) |
| **DB** | Postgres 17 trong compose, đã nạp 182 user (24 091 430 điểm; bảng `gps_points` kể cả khoá chính chiếm 2,7 GB) |
| **Model** | Nạp từ registry: version 1 = `stay_point` v1, 2 = `stay_point` v2, 3 = `dbscan` v1, 4 = `dbscan` v2 |
| **RAM đỉnh** | Đọc `/sys/fs/cgroup/memory.peak` trong container: đỉnh kể từ lúc container khởi động |
| **Thời gian** | Đo ở phía client, từ lúc gửi tới lúc nhận xong response của `POST /v1/users/{id}/predictions` (không truyền `start` / `end`, tức dùng toàn bộ điểm của user) |

Ba user đại diện, chọn theo số điểm:

| Nhãn | `user_id` | Số điểm |
| --- | --- | --- |
| Trung vị | 83 | 34 960 |
| Phân vị 90 | 14 | 388 211 |
| Lớn nhất | 153 | 2 156 929 |

Mỗi container gọi lần lượt ba user theo thứ tự tăng dần số điểm (mỗi user hai lần), rồi gọi nhiều request đồng thời cho user lớn nhất.

```bash
uv run python scripts/measure_sizing.py --cpus 0.5 --memory 2g --versions 1 2 3 4
```

## B1. RAM đỉnh theo tải

**Xét:** RAM đỉnh (MB) ở giới hạn 0,5 vCPU / 2 GB.

| Tải | `stay_point` v1 | `stay_point` v2 | `dbscan` v1 | `dbscan` v2 |
| --- | --- | --- | --- | --- |
| Sau khi khởi động (đã nạp model, đã chạy thử) | 318 | 321 | 317 | 322 |
| User trung vị (35 nghìn điểm) | 391 | 388 | 391 | 401 |
| User phân vị 90 (388 nghìn điểm) | 575 | 567 | 585 | 589 |
| User lớn nhất (2,16 triệu điểm) | 1 219 | 1 215 | 1 351 | 1 370 |
| 2 request đồng thời của user lớn nhất | 1 827 | 1 591 | 2 047 (chạm trần) | Container bị giết vì hết RAM |

Cùng phép đo ở các giới hạn RAM khác:

| Giới hạn RAM | Tải | Kết quả |
| --- | --- | --- |
| 1 GB | User lớn nhất, một request | Bị giết vì hết RAM (`stay_point` v1, `stay_point` v2, `dbscan` v2) |
| 4 GB | 2 request đồng thời của user lớn nhất | 1 869 MB (`stay_point` v1), 1 926 MB (`stay_point` v2), 2 150 MB (`dbscan` v1), 2 215 MB (`dbscan` v2) |
| 4 GB | 4 request đồng thời của user lớn nhất, `dbscan` v2 | 3 742 MB |

**Output cho thấy:**

- RAM nền sau khởi động khoảng 320 MB, như nhau giữa các model. Hai version của cùng một thuật toán dùng RAM gần như bằng nhau.
- RAM tăng gần tuyến tính theo tổng số điểm đang được xử lý: khoảng 0,42 KB mỗi điểm với `stay_point`, 0,49 KB với `dbscan`. Bốn request đồng thời (8,6 triệu điểm) dùng 3 742 MB, khớp với ước lượng 320 + 8,6 triệu × 0,4 KB.
- 1 GB không chứa nổi một request của user lớn nhất. 2 GB chứa được mọi request đơn lẻ, nhưng không chứa được hai request đồng thời của user lớn nhất khi chạy `dbscan`.
- RAM không phụ thuộc số vCPU.

Đỉnh của 2 request đồng thời dao động giữa các lần đo (1 591–1 926 MB với `stay_point` v2): hai request chỉ cộng dồn RAM khi giai đoạn tốn RAM nhất của chúng trùng nhau, và điều đó tuỳ thời điểm. Thiết kế phải tính theo trường hợp trùng hoàn toàn.

**⇒ Quy tắc ước lượng:** RAM đỉnh ≈ 320 MB + 0,5 KB × tổng số điểm của các request đang chạy.

## B2. Thời gian theo số vCPU

**Xét:** thời gian của lần gọi thứ hai (giây), `stay_point` v1 / `stay_point` v2 / `dbscan` v2.

| User | 0,25 vCPU | 0,5 vCPU | 1 vCPU |
| --- | --- | --- | --- |
| Trung vị (35 nghìn điểm) | 0,6 / 0,6 / 0,6 | 0,13 / 0,18 / 0,20 | 0,06 / 0,07 / 0,07 |
| Phân vị 90 (388 nghìn điểm) | 3,0 / 3,0 / 3,7 | 0,92 / 1,10 / 1,11 | 0,50 / 0,54 / 0,51 |
| Lớn nhất (2,16 triệu điểm) | 18,8 / 22,3 / 26,1 | 6,7 / 7,6 / 8,0 | 3,0 / 3,3 / 3,6 |

Request đồng thời của user lớn nhất, thời gian của request chậm nhất (giây):

| Cấu hình | `stay_point` v1 | `stay_point` v2 | `dbscan` v1 | `dbscan` v2 |
| --- | --- | --- | --- | --- |
| 2 request, 0,5 vCPU | 15,3 | 16,4 | 19,5 | Bị giết (2 GB) |
| 2 request, 1 vCPU | 6,7 | 6,9 | 8,2 | 7,6 |
| 4 request, 1 vCPU | | | | 18,8 |

Thời gian từ lúc container khởi động tới lúc `/v1/health` trả `ok` (gồm tải model từ registry và chạy thử để numba biên dịch): 34–36 giây ở 0,25 vCPU, 20–22 giây ở 0,5 vCPU, 17–19 giây ở 1 vCPU.

**Output cho thấy:**

- Thời gian tỉ lệ nghịch với số vCPU: gấp đôi vCPU thì thời gian giảm khoảng một nửa. Việc suy luận nặng về CPU và chạy trên một nhân.
- Request đồng thời chia nhau CPU: N request cùng lúc thì mỗi request chậm đi khoảng N lần, tổng số request xử lý được mỗi giây không tăng.
- Với user lớn nhất, `stay_point` v2 chậm hơn v1 10–20% (neo động phải cập nhật tâm sau mỗi điểm), `dbscan` v2 chậm hơn `stay_point` v1 20–40%. Với user nhỏ, mọi version gần như bằng nhau.
- Ở 0,5 vCPU, request đơn lẻ nặng nhất mất 7–8 giây, còn cách xa timeout 60 giây của ALB.

## B3. Chọn cỡ task

| Vai trò | vCPU / RAM | Lý do |
| --- | --- | --- |
| **API** (`api-blue`, `api-green`) | **0,5 / 2 GB** | 2 GB chứa được mọi request đơn lẻ (đỉnh 1 370 MB); 1 GB thì không. 0,5 vCPU cho request nặng nhất 7–8 giây; 0,25 vCPU đẩy lên 19–26 giây và khởi động lâu hơn khoảng 70% |
| **Worker** | **1 / 2 GB** | Mỗi lúc xử lý một job nên 2 GB đủ; worker chuyên xử lý user nặng, 1 vCPU giảm một nửa thời gian mỗi job |
| **Seed, migrate** (task `geolife-ops`) | 1 / 2 GB | Seed đo ở B4: đỉnh 783 MB khi nạp toàn bộ; migrate không nạp dữ liệu. Dùng chung một task definition |
| **Drift** | 0,25 / 1 GB | Chưa đo; không nạp model |

Hai hệ quả cho thiết kế:

- **API phải giới hạn tổng số điểm đang xử lý đồng thời.** Với 2 GB, ngân sách là (2 048 − 320 − 230 dự trữ) / 0,5 KB ≈ 3 triệu điểm. Số điểm của mỗi user đã có sẵn trong bảng `users` (`n_points`), nên API biết trước khi đọc điểm. Request vượt ngân sách thì chờ; không có giới hạn này, hai request nặng trùng nhau là đủ làm task bị giết.
- **`health_check_grace_period_seconds` đặt 120 giây**, gấp khoảng 6 lần thời gian khởi động đo được, để bù cho CPU của Fargate chậm hơn máy đo.

## B4. Seed: RAM và thời gian nạp vào RDS

Đo ngày 2026-11-18. Seed đọc `points.parquet` (605 MB nén, 23 row group khoảng 1 triệu dòng) và ghi vào Postgres bằng `COPY` theo lô 500 nghìn dòng.

**RAM đỉnh** (container local, `--memory 2g`, nạp toàn bộ 182 user; RSS đỉnh của process và bộ nhớ Arrow đang cấp phát):

| `ParquetFile` | RSS đỉnh | Bộ nhớ Arrow trong vòng lặp | Trên Fargate 1 vCPU / 2 GB |
| --- | --- | --- | --- |
| Mặc định (`pre_buffer=True`) | 1 361 MB | Tăng đều tới ~630 MB | Bị giết (exit 137) khi đọc từ S3 |
| `pre_buffer=False` | 783 MB | Giữ quanh 80 MB | — |

Với `pre_buffer=True`, pyarrow đọc trước các vùng của file và giữ chúng tới hết vòng lặp, nên bộ nhớ tăng theo kích thước file nén thay vì theo kích thước một lô. Đọc từ S3 thêm bộ đệm mạng nên vượt 2 GB. Seed đặt `pre_buffer=False`.

**Thời gian trên AWS** (task Fargate ARM 1 vCPU đọc S3, RDS `db.t4g.micro` gp3 20 GB; tính từ lúc container chạy tới lúc dừng):

| Lệnh | Số điểm | Thời gian |
| --- | --- | --- |
| `migrate` | — | ~11 giây |
| `seed --split holdout` | 5 639 032 | ~111 giây |
| `seed --replace` (toàn bộ) | 24 091 430 | ~531 giây |

Lần nạp toàn bộ chạy bằng image còn `pre_buffer=True`, với RAM nâng lên 4 GB cho riêng lần đó; chưa đo lại với `pre_buffer=False`. Ở lần holdout, vòng đọc và `COPY` xong sau 13 giây, phần còn lại (cập nhật thống kê bảng `users`, commit, `ANALYZE`) chiếm phần lớn thời gian. Thêm khoảng 30 giây để Fargate cấp phát và kéo image trước khi container chạy.

## B5. Thời gian trên AWS

Đo ngày 2026-11-18, image `2cba159e21cb`, service `api-blue` (`stay_point` v1, Fargate ARM 0,5 vCPU / 2 GB) sau ALB, RDS `db.t4g.micro` (2 vCPU, 1 GB RAM) gp3 20 GB (3 000 IOPS, 125 MB/s). Client gọi tuần tự từ máy đo qua internet, mỗi user ba lần.

**Thời gian một request** (giây, ba lần gọi):

| User | Số điểm | Trên AWS | Ở local, 0,5 vCPU (B2) |
| --- | --- | --- | --- |
| 83 (trung vị) | 34 960 | 0,50 / 0,46 / 0,40 | 0,13 |
| 14 (phân vị 90) | 388 211 | 16,3 / 15,9 / 15,6 | 0,92 |
| 153 (lớn nhất) | 2 156 929 | 26,6 / 27,3 / 26,8 | 6,7 |
| `/v1/health` | — | 0,16 / 0,20 / 0,17 | — |

User 14 chậm gấp 17 lần ở local dù số điểm chỉ bằng 18% user 153, nên phần chậm thêm không nằm ở model.

**Thời gian đọc điểm từ RDS** (`Database.fetch_points`, chạy trong một task ở cùng VPC):

| User | Số trang chứa điểm của user | Thời gian đọc | Kế hoạch truy vấn |
| --- | --- | --- | --- |
| 83 | 361 | 0,15 giây | Index scan trên khoá chính |
| 14 | 4 003 | 15,2 / 14,9 giây | Parallel seq scan cả bảng rồi sort: đọc 230 921 trang (1,8 GB) từ đĩa |
| 153 | 22 320 | 22,5 giây | Parallel seq scan cả bảng rồi sort |

⇒ Trên AWS, thời gian request bị chi phối bởi việc đọc DB: user 153 mất 26,8 giây, trong đó 22,5 giây là đọc điểm. Phần dưới giải thích vì sao Postgres chọn đọc cả bảng.

### Postgres đọc điểm của một user như thế nào

- **Trang.** Postgres lưu bảng thành các trang 8 KB và luôn đọc theo trang. `gps_points` có 248 704 trang (1,9 GB), index khoá chính `(user_id, ts_utc)` thêm 725 MB.
- **Bộ nhớ đệm.** Trang đã đọc nằm lại trong `shared_buffers` (180 MB trên `db.t4g.micro`) và page cache của hệ điều hành. Trang không có ở đó phải đọc từ ổ gp3, tối đa 125 MB/s. Bảng lớn hơn cả RAM của instance (1 GB), nên mỗi lần quét cả bảng đều đọc lại từ đĩa: 1,8 GB ở 125 MB/s mất khoảng 15 giây. Ở local (VM 12,5 GB RAM) cả bảng nằm trong bộ nhớ đệm, nên B2 không thấy chênh lệch này.
- **Hai cách lấy điểm của một user:**
  - *Seq scan*: đọc mọi trang của bảng, lọc theo `user_id`, rồi sort theo `ts_utc`. Chi phí tỉ lệ với kích thước bảng, không phụ thuộc user. Parallel seq scan chia việc cho 2 worker, nhưng các worker dùng chung một ổ đĩa. Sort cần nhiều hơn `work_mem` (4 MB) nên ghi file tạm ra đĩa (25 MB với user 14, 273 MB với user 153).
  - *Index scan* trên khoá chính: tìm `user_id` trong B-tree rồi đọc đúng các trang chứa điểm của user, theo sẵn thứ tự `ts_utc` nên không cần sort. Seed nạp điểm theo thứ tự user, nên điểm của một user nằm liền nhau: user 14 gọn trong 4 003 trang, user 153 trong 22 320 trang (`correlation` của `user_id` trong `pg_stats` là 1,0).
- **Planner chọn kế hoạch theo chi phí ước lượng**, không đo thời gian thật. Chi phí tính bằng đơn vị quy ước: `seq_page_cost = 1` cho mỗi trang đọc tuần tự, `random_page_cost = 4` cho mỗi trang đọc ngẫu nhiên, cộng chi phí CPU cho mỗi dòng. Kế hoạch có tổng chi phí thấp nhất được chạy.

### Vì sao planner ước lượng sai

Chi phí đọc heap của index scan được nội suy giữa hai trường hợp, với trọng số là bình phương độ tương quan giữa thứ tự index và thứ tự vật lý ([`cost_index`](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/backend/optimizer/path/costsize.c)):

| Trường hợp | Giả định | Số trang ước lượng (user 153) |
| --- | --- | --- |
| Xấu nhất | Mỗi dòng nằm ở một trang ngẫu nhiên; công thức Mackert–Lohman tính cả việc trang bị đẩy khỏi cache, với cache bằng `effective_cache_size` (360 MB) | 1 810 983 trang × `random_page_cost` |
| Tốt nhất | Các dòng nằm liền nhau | 21 588 trang × `seq_page_cost` |

`correlation` của `user_id` là 1,0, đáng lẽ chi phí nằm hẳn ở trường hợp tốt nhất. Nhưng khi index có nhiều cột, Postgres nhân độ tương quan của cột đầu với 0,75 ([`btcostestimate`](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/backend/utils/adt/selfuncs.c)). Trọng số còn 0,75² ≈ 0,56, nên 44% chi phí của trường hợp xấu nhất vẫn được cộng vào. Tính lại theo công thức này ra đúng chi phí planner báo (lệch dưới 0,01%). Nếu dùng tương quan 1,0, index scan của user 153 chỉ tốn khoảng 90 nghìn đơn vị.

**Chi phí planner ước lượng** (`EXPLAIN`, không thực thi) so với thời gian đọc thật:

| User | Seq scan: chi phí ước lượng | Index scan: chi phí ước lượng | Seq scan: thời gian thật | Index scan: thời gian thật |
| --- | --- | --- | --- | --- |
| 83 | — | 75 323 (được chọn) | — | 0,15 giây |
| 14 | 431 078 (được chọn) | 592 611 | 15,2 giây | 0,40 giây |
| 153 | 724 053 (được chọn) | 3 250 112 | 22,5 giây | 1,8 giây |

Planner tính index scan của user 153 đắt gấp 4,5 lần seq scan, trong khi thực tế nó nhanh hơn 12 lần. Hai giả định cộng dồn: `random_page_cost = 4` là giá trị cho ổ quay, và hệ số 0,75 làm phần lớn số trang bị tính như đọc ngẫu nhiên.

### Thử cấu hình planner

Cùng truy vấn, đặt cấu hình trong session (`EXPLAIN ANALYZE`):

| Cấu hình | User 14 | User 153 |
| --- | --- | --- |
| Mặc định của RDS (`random_page_cost = 4`, 2 worker song song) | 15,2 giây, seq scan | 18,7–22,5 giây, seq scan |
| `random_page_cost = 1.1` | 1,3 giây, index scan | 18,7 giây, vẫn seq scan (ước lượng: seq 699 374, index 929 117) |
| `random_page_cost = 1.1`, `max_parallel_workers_per_gather = 0` | 0,26 giây, index scan | 8,0 giây, seq scan + sort |
| Chỉ tắt seq scan (`enable_seqscan = off`) | Bitmap heap scan + sort (chỉ `EXPLAIN`) | Bitmap heap scan + sort (chỉ `EXPLAIN`) |
| Tắt seq scan và bitmap scan | 0,40 giây, index scan | 1,8 giây, index scan |

Bitmap heap scan đọc trang theo thứ tự vật lý nên không giữ thứ tự `ts_utc`; planner phải sort thêm. Muốn có index scan thì phải tắt cả hai.

RDS báo `CPUCreditBalance = 0` trong suốt phép đo (T4g của RDS chạy ở chế độ unlimited: không bị hãm CPU, phần vượt baseline tính phí riêng) và `FreeableMemory` khoảng 100 MB.

### Cách cải thiện

| Cách | Tác dụng | Chọn |
| --- | --- | --- |
| `random_page_cost = 1.1` trong parameter group của RDS | Đúng với ổ SSD (tài liệu Postgres gợi ý giá trị thấp như 1.1 cho SSD), áp cho mọi truy vấn. Không đủ với user lớn nhất | Có |
| `SET LOCAL enable_seqscan = off`, `enable_bitmapscan = off` trong `fetch_points` | Index scan cho mọi user: nhanh nhất ở cả ba user đo. `SET LOCAL` chỉ có hiệu lực tới hết transaction, không ảnh hưởng truy vấn khác dùng chung connection. Truy vấn luôn lọc theo cột đầu của khoá chính và cần thứ tự của khoá chính, nên index scan luôn là cách đọc đúng | Có |
| Instance có RAM chứa được bảng và index (2,6 GB; từ `db.t4g.medium`, 4 GB) | Seq scan đọc từ bộ nhớ, nhưng vẫn quét cả bảng cho mỗi request. Giá theo giờ gấp 4 lần trở lên, và bảng tăng theo dữ liệu | Không |
| Index riêng trên `user_id` (một cột, tương quan 1,0) | Planner chọn đúng index, nhưng tốn thêm vài trăm MB và vẫn phải sort theo `ts_utc` | Không |
| Partition `gps_points` theo user | Seq scan chỉ quét partition của user, nhưng phải đổi schema và seed | Không |

## Giới hạn của phép đo

- **Thời gian ở B2 là số của máy đo, không phải của Fargate.** CPU Apple Silicon nhanh hơn Graviton, và Postgres ở đó chạy cùng máy, cả bảng nằm trong bộ nhớ đệm. Số trên AWS ở B5.
- **RAM chuyển sang Fargate được**: cùng image arm64, cùng dữ liệu.
- **Mỗi ô là một hoặc hai lần đo**, không phải phân bố. Các lần lặp lại lệch nhau dưới 5% về RAM và khoảng 10% về thời gian.
- **Chỉ đo request dùng toàn bộ điểm của user.** Request có `start` / `end` đọc ít điểm hơn, nên đây là trường hợp nặng nhất của mỗi user.
