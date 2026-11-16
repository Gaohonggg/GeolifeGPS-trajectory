# Cỡ task của API: số đo RAM và thời gian

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
| **Seed, migrate, drift** | 0,5 / 2 GB; 0,25 / 0,5 GB; 0,25 / 1 GB | Chưa đo. Seed đọc parquet theo lô 500 nghìn dòng; migrate và drift không nạp model |

Hai hệ quả cho thiết kế:

- **API phải giới hạn tổng số điểm đang xử lý đồng thời.** Với 2 GB, ngân sách là (2 048 − 320 − 230 dự trữ) / 0,5 KB ≈ 3 triệu điểm. Số điểm của mỗi user đã có sẵn trong bảng `users` (`n_points`), nên API biết trước khi đọc điểm. Request vượt ngân sách thì chờ; không có giới hạn này, hai request nặng trùng nhau là đủ làm task bị giết.
- **`health_check_grace_period_seconds` đặt 120 giây**, gấp khoảng 6 lần thời gian khởi động đo được, để bù cho CPU của Fargate chậm hơn máy đo.

## Giới hạn của phép đo

- **Thời gian là số của máy đo, không phải của Fargate.** CPU Apple Silicon nhanh hơn Graviton, và Postgres ở đây chạy cùng máy thay vì là RDS `db.t4g.micro` qua mạng. Thời gian trên AWS sẽ dài hơn; cần đo lại khi service đã chạy trên Fargate.
- **RAM chuyển sang Fargate được**: cùng image arm64, cùng dữ liệu.
- **Mỗi ô là một hoặc hai lần đo**, không phải phân bố. Các lần lặp lại lệch nhau dưới 5% về RAM và khoảng 10% về thời gian.
- **Chỉ đo request dùng toàn bộ điểm của user.** Request có `start` / `end` đọc ít điểm hơn, nên đây là trường hợp nặng nhất của mỗi user.
