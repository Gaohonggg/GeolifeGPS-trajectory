# Cỡ function: số đo RAM và thời gian

Lambda cấp RAM cố định cho mỗi function (128 MB – 10 240 MB) và cấp vCPU theo tỉ lệ RAM: 1 769 MB ứng với 1 vCPU. Request vượt RAM thì environment bị dừng và client nhận `500` của API Gateway, không theo contract ([`request_flow.md`](request_flow.md), mục 4). Trang này đo image của API dưới giới hạn RAM / CPU của một function để chọn RAM.

Một execution environment xử lý một request tại một thời điểm và có RAM riêng, nên RAM của function chỉ cần chứa **một** request lớn nhất, cộng phần RAM tích luỹ khi environment được dùng lại cho nhiều request.

## Cách đo

| | |
| --- | --- |
| **Script** | [`scripts/measure_lambda_memory.py`](../../../scripts/measure_lambda_memory.py) |
| **Image** | `make aws-build` (`linux/arm64`), build từ code của commit thêm trang này. Kích thước image 353 MB |
| **Container** | Mỗi model version một container mới, `--memory 2048m --memory-swap 2048m --cpus 1.15` (function 2 048 MB ≈ 1,15 vCPU) trừ khi ghi khác |
| **Máy** | Docker Desktop trên Apple Silicon (VM 12 CPU, 12,5 GB RAM) |
| **Cách gọi** | Driver trong container lấy `lambda_handlers.api` (pha init: đọc cấu hình, nạp model từ S3, chạy thử), rồi gọi handler bằng event HTTP API v2 `POST /v1/users/{id}/predictions` không có `start` / `end` |
| **Model** | Bản phát hành trên S3: registry v1 = `stay_point` v1, registry v3 = `dbscan` v1 |
| **Nguồn điểm** | `data/serving/v_1/` mount vào container (mục L4 so với đọc thẳng từ S3) |
| **RAM đỉnh** | `/sys/fs/cgroup/memory.peak`: đỉnh của container kể từ lúc khởi động. Gọi user theo thứ tự tăng dần số điểm, nên giá trị đọc sau mỗi user là RAM đỉnh khi xử lý user đó |

Ba user đại diện, chọn theo số điểm:

| Nhãn | `user_id` | Số điểm | File parquet |
| --- | --- | --- | --- |
| Trung vị | 83 | 34 960 | 0,90 MB |
| Phân vị 90 | 14 | 388 211 | 9,9 MB |
| Lớn nhất | 153 | 2 156 929 | 61,0 MB |

```bash
make aws-build
```

```bash
uv run python scripts/measure_lambda_memory.py --image geolife-api:<sha> --versions 1 3
```

## L1. RAM đỉnh theo user

**Xét:** RAM đỉnh (MB) ở giới hạn 2 048 MB; mỗi user gọi hai lần, ghi lần 1 / lần 2.

| Tải | `stay_point` v1 (registry v1) | `dbscan` v1 (registry v3) |
| --- | --- | --- |
| Sau pha init (đã nạp model, đã chạy thử) | 279 | 278 |
| User trung vị (35 nghìn điểm) | 324 / 325 | 321 / 323 |
| User phân vị 90 (388 nghìn điểm) | 466 / 487 | 489 / 525 |
| User lớn nhất (2,16 triệu điểm) | 1 113 / 1 181 | 1 257 / 1 401 |

**Output cho thấy:**

- RAM nền sau pha init khoảng 280 MB, như nhau giữa hai model.
- RAM tăng gần tuyến tính theo số điểm của request: (1 181 − 279) / 2,16 triệu ≈ 0,43 KB mỗi điểm với `stay_point`; (1 401 − 278) / 2,16 triệu ≈ 0,53 KB với `dbscan`.
- Lần gọi thứ hai cao hơn lần đầu (đến +144 MB với user 153): RAM đã cấp cho request trước chưa trả hết về hệ điều hành, request sau cấp thêm ở chỗ khác.

## L2. RAM khi environment được dùng lại

Trên Lambda, một environment ấm nhận nhiều request liên tiếp. **Xét:** RAM đỉnh (MB) sau mỗi lần gọi user 153, tám lần liên tiếp trong một container.

```bash
uv run python scripts/measure_lambda_memory.py --image geolife-api:<sha> --versions 1 3 --users 153 --repeat 8
```

| Lần gọi | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `stay_point` v1 | 1 041 | 1 173 | 1 184 | 1 191 | 1 211 | 1 334 | 1 334 | 1 334 |
| `dbscan` v1 | 1 182 | 1 386 | 1 393 | 1 393 | 1 412 | 1 418 | 1 418 | 1 418 |

**Output cho thấy:**

- RAM đỉnh tăng qua vài lần gọi đầu rồi đứng yên từ lần thứ 6: 1 334 MB với `stay_point`, 1 418 MB với `dbscan`. Trong tám lần gọi không thấy RAM tăng tiếp sau mức đó.
- Mức ổn định cao hơn lần gọi đầu 200–300 MB, nên phải chọn RAM theo mức ổn định chứ không theo một lần đo.

## L3. Giới hạn RAM thấp hơn

**Xét:** `dbscan` v1, user 153 gọi hai lần, giới hạn 1 536 MB.

| Giới hạn | Lần 1 | Lần 2 | Kết quả |
| --- | --- | --- | --- |
| 1 536 MB | 1 203 MB | 1 433 MB | Chạy được, dư 103 MB |

Mức ổn định ở L2 (1 418 MB) cũng chỉ dư 118 MB dưới 1 536 MB; dao động giữa các lần đo (1 401 và 1 433 MB cho cùng lần gọi thứ hai) cùng cỡ với phần dư đó.

## L4. Đọc điểm từ S3

**Xét:** `dbscan` v1, user 153 gọi hai lần, nguồn điểm là `s3://…/data/serving/v_1` thay cho thư mục mount. Đường đọc S3 tải byte qua một đối tượng `bytes` của Python rồi copy vào buffer của pyarrow ([`serving_data.md`](serving_data.md), mục 5), nên có thể tốn thêm RAM tạm thời.

```bash
uv run python scripts/measure_lambda_memory.py --image geolife-api:<sha> --versions 3 --users 153 --points s3
```

So với cùng phép đo (`dbscan` v1, container chỉ gọi user 153) khi đọc từ thư mục mount (L2, L3):

| Nguồn điểm | Lần 1 | Lần 2 |
| --- | --- | --- |
| Thư mục mount, giới hạn 2 048 MB (L2) | 1 182 MB | 1 386 MB |
| Thư mục mount, giới hạn 1 536 MB (L3) | 1 203 MB | 1 433 MB |
| S3, giới hạn 2 048 MB | 1 203 MB | 1 344 MB |

**Output cho thấy:**

- RAM đỉnh khi đọc từ S3 nằm trong khoảng dao động của khi đọc từ thư mục: phần copy qua `bytes` (tối đa 61 MB) không làm tăng RAM đỉnh tới mức đo được. Đỉnh rơi vào lúc chạy model, khi dữ liệu đã nằm trong DataFrame và buffer tải về không còn được dùng.
- Thời gian của hai request này (145 và 176 giây) là thời gian tải 61 MB qua đường mạng từ máy đo tới Singapore (~0,4 MB/s), không phản ánh Lambda.

## L5. Thời gian

Số đo trên CPU Apple Silicon dưới giới hạn 1,15 vCPU; Graviton của Lambda chậm hơn. Chỉ dùng để so giữa các phần; thời gian trên Lambda đo sau khi deploy.

**Pha init** (một lần cho mỗi environment):

| Phần | Thời gian |
| --- | --- |
| Import `geolife_api.lambda_handlers` (FastAPI, Mangum, boto3, pyarrow, pandas, MLflow) | 0,84–0,90 giây |
| Toàn bộ init: import, tải model từ S3, import code thuật toán, chạy thử (numba biên dịch) | 6,8–7,5 giây |

Tải model đi qua đường mạng từ máy đo tới S3 ở Singapore; trên Lambda, model tải từ S3 cùng region. Trần của pha init trên Lambda là 10 giây.

Đo riêng ngày 2026-11-23 trên máy, ngoài container (không giới hạn CPU, mỗi lần một process mới, cache numba rỗng; số ghi theo `stay_point` v1 / `dbscan` v1):

| Phần | Thời gian |
| --- | --- |
| Import thư viện và code thuật toán (numpy, pandas, pyarrow, mlflow, fastapi, boto3, numba, sklearn, scipy, holidays, timezonefinder) | 1,4 / 1,6 giây; trong đó mlflow 0,4–0,5 giây, code thuật toán kèm sklearn, scipy, holidays, timezonefinder 0,7 giây |
| Lần predict đầu trên dữ liệu giả 4 ngày, gồm numba biên dịch | 0,34 / 0,29 giây |
| Cùng lần predict đó khi cache của numba đã có | 0,14 / 0,15 giây |

**Một request** (environment đã ấm, lần gọi thứ hai, giây):

| User | `stay_point` v1 | `dbscan` v1 |
| --- | --- | --- |
| Trung vị (35 nghìn điểm) | 0,03 | 0,04 |
| Phân vị 90 (388 nghìn điểm) | 0,13 | 0,19 |
| Lớn nhất (2,16 triệu điểm) | 0,98 | 1,86 |

**Output cho thấy:**

- Numba biên dịch chỉ thêm khoảng 0,2 giây; phần lớn pha init là import và tải model.
- Ở local, đọc điểm từ thư mục mount gần như không tốn thời gian; trên Lambda, thời gian đọc từ S3 cộng thêm vào cột trên.

## Kết luận

| | |
| --- | --- |
| **RAM của function API** | **2 048 MB** (≈ 1,15 vCPU) |
| Lý do | Request lớn nhất ổn định ở 1 334 MB (`stay_point`) / 1 418 MB (`dbscan`) khi environment được dùng lại (L2). 2 048 MB dư 630 MB cho dao động và model nặng hơn; 1 536 MB chỉ dư khoảng 100 MB (L3) |
| Không chọn cao hơn | Model chạy trên một nhân; từ 1 769 MB Lambda đã cấp đủ 1 vCPU, thêm RAM không làm request nhanh hơn mà tăng chi phí theo GB-giây |

**⇒ Quy tắc ước lượng:** RAM đỉnh ≈ 280 MB + 0,5 KB × số điểm của request, cộng 200–300 MB khi environment đã xử lý nhiều request lớn.
