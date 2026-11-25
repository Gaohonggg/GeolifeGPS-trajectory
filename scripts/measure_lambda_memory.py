"""Đo RAM đỉnh và thời gian của handler Lambda trong image của API, dưới giới hạn RAM / CPU như một function.

    uv run python scripts/measure_lambda_memory.py --image geolife-api:<sha> --versions 1 3
    uv run python scripts/measure_lambda_memory.py --image geolife-api:<sha> --versions 3 --users 153 --repeat 8
    uv run python scripts/measure_lambda_memory.py --image geolife-api:<sha> --versions 3 --users 153 --points s3

Mỗi model version chạy trong một container mới (`docker run --memory --cpus`, không swap). Trong container, một
driver Python lấy `geolife_api.lambda_handlers.api` (pha init: đọc cấu hình, nạp model từ S3, chạy thử) rồi gọi
handler bằng event HTTP API v2 cho từng user theo thứ tự tăng dần số điểm, mỗi user `--repeat` lần. Sau init và
sau mỗi lần gọi, driver đọc `/sys/fs/cgroup/memory.peak`: RAM đỉnh của container kể từ lúc khởi động, nên với thứ
tự tăng dần số điểm, giá trị sau mỗi user là RAM đỉnh khi xử lý user đó.

Nguồn điểm: `--points local` mount `data/serving/v_1/` vào container (không phụ thuộc đường mạng tới S3);
`--points s3` đọc `s3://<bucket>/data/serving/v_1` qua cùng đường đọc trên Lambda.

Model nạp từ bản phát hành trên S3 (`models/geolife_home_office/v=<n>/model`). Credential AWS lấy từ profile hiện
tại (boto3) và truyền vào container bằng biến môi trường.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
SERVING = ROOT / "data" / "serving" / "v_1"
USERS = [83, 14, 153]     # trung vị, phân vị 90, lớn nhất theo số điểm

# Chạy trong container. In mỗi phép đo thành một dòng JSON có tiền tố để tách khỏi log của app.
DRIVER = r"""
import json, sys, time
t0 = time.perf_counter()
from geolife_api import lambda_handlers
t_import = time.perf_counter() - t0
handler = lambda_handlers.api
t_init = time.perf_counter() - t0

def peak_mb():
    return int(open("/sys/fs/cgroup/memory.peak").read()) / 2**20

def event(user):
    path = f"/v1/users/{user}/predictions"
    return {"version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "",
            "headers": {"host": "local"}, "isBase64Encoded": False,
            "requestContext": {"http": {"method": "POST", "path": path, "protocol": "HTTP/1.1",
                                        "sourceIp": "127.0.0.1", "userAgent": "measure"},
                               "requestId": "m", "routeKey": "$default", "stage": "$default"}}

class Ctx:
    aws_request_id = "m"

def emit(**kw):
    print("MEASURE " + json.dumps(kw), flush=True)

emit(stage="init", import_s=round(t_import, 2), init_s=round(t_init, 2), peak_mb=round(peak_mb()))
for user in json.loads(sys.argv[1]):
    for attempt in range(1, int(sys.argv[2]) + 1):
        t = time.perf_counter()
        r = handler(event(user), Ctx())
        body = json.loads(r["body"])
        emit(stage="request", user=user, attempt=attempt, status=r["statusCode"], n_points=body.get("n_points"),
             seconds=round(time.perf_counter() - t, 2), peak_mb=round(peak_mb()))
"""


def aws_env(session: boto3.Session) -> list[str]:
    c = session.get_credentials().get_frozen_credentials()
    env = {"AWS_ACCESS_KEY_ID": c.access_key, "AWS_SECRET_ACCESS_KEY": c.secret_key,
           "AWS_REGION": session.region_name, "AWS_DEFAULT_REGION": session.region_name}
    if c.token:
        env["AWS_SESSION_TOKEN"] = c.token
    return [x for k, v in env.items() for x in ("-e", f"{k}={v}")]


def run(image: str, version: int, users: list[int], repeat: int, points: str, memory: str, cpus: str,
        bucket: str, creds: list[str]) -> list[dict]:
    cmd = ["docker", "run", "--rm", "--platform", "linux/arm64", "--memory", memory, "--memory-swap", memory,
           "--cpus", cpus, *creds,
           "-e", f"MODEL_URI=s3://{bucket}/models/geolife_home_office/v={version}/model"]
    if points == "local":
        cmd += ["-v", f"{SERVING}:/data:ro", "-e", "POINTS_URI=/data"]
    else:
        cmd += ["-e", f"POINTS_URI=s3://{bucket}/data/serving/v_1"]
    cmd += ["--entrypoint", "python", image, "-c", DRIVER, json.dumps(users), str(repeat)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    rows = [json.loads(line.removeprefix("MEASURE ")) for line in proc.stdout.splitlines()
            if line.startswith("MEASURE ")]
    if proc.returncode != 0:
        # 137: container bị giết vì vượt giới hạn RAM
        rows.append({"stage": "exit", "returncode": proc.returncode, "stderr": proc.stderr[-2000:]})
    return [{"version": version, "points": points, "memory": memory, "cpus": cpus, **r} for r in rows]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--versions", type=int, nargs="+", default=[1, 3], help="registry version đã phát hành lên S3")
    ap.add_argument("--users", type=int, nargs="+", default=USERS)
    ap.add_argument("--repeat", type=int, default=2, help="số lần gọi mỗi user")
    ap.add_argument("--points", choices=["local", "s3"], default="local")
    ap.add_argument("--memory", default="2048m", help="RAM của function")
    ap.add_argument("--cpus", default="1.15", help="Lambda cấp vCPU theo RAM: 2 048 MB ≈ 1,15 vCPU")
    ap.add_argument("--out", type=Path, help="ghi thêm các dòng JSON vào file này")
    a = ap.parse_args(argv)

    session = boto3.Session()
    bucket = f"geolife-{session.client('sts').get_caller_identity()['Account']}-artifacts"
    creds = aws_env(session)
    for v in a.versions:
        for row in run(a.image, v, a.users, a.repeat, a.points, a.memory, a.cpus, bucket, creds):
            line = json.dumps(row, ensure_ascii=False)
            print(line, flush=True)
            if a.out:
                with a.out.open("a") as f:
                    f.write(line + "\n")


if __name__ == "__main__":
    main()
