"""Đo cold start và thời gian request của API trên Lambda qua HTTP API.

    uv run python scripts/measure_lambda_latency.py --url <url của HTTP API> [--cold 6] [--users 83 14 153] [--repeat 4]

Hai pha:
1. Cold start: gửi `--cold` request đồng thời (user đầu tiên trong `--users`) để Lambda dựng environment mới. Pha này
   chỉ đo được cold start khi alias live vừa trỏ sang một Lambda version chưa có environment nào (sau promote / deploy).
2. Khi ấm: với mỗi user, gọi tuần tự `--repeat` lần; bỏ request nào có header `X-Cold-Start`.

Sau mỗi pha, đọc log của function trong khoảng thời gian của pha đó: dòng `platform.report` (thời gian, RAM, init),
`platform.initReport` (init quá trần 10 giây), log thời gian của pha init (`importS`, `downloadS`, `loadS`, `warmUpS`,
`modelReady`) và thời gian request đầu chờ model khi pha init kết thúc trước (`modelWaitS`).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
import httpx

LOG_GROUP = "/aws/lambda/geolife-api"
# CloudWatch Logs nhận log trễ vài giây sau khi request xong
LOG_DELAY_S = 20


def call(url: str, user: int) -> dict:
    t = time.perf_counter()
    r = httpx.post(f"{url}/v1/users/{user}/predictions", timeout=60)
    return {"user": user, "status": r.status_code, "client_s": time.perf_counter() - t,
            "cold": r.headers.get("x-cold-start") == "1"}


def read_logs(logs, start_ms: int, end_ms: int) -> list[dict]:
    """Các dòng log JSON của function trong [start_ms, end_ms], kèm tên log stream (một stream ~ một environment)."""
    out = []
    for page in logs.get_paginator("filter_log_events").paginate(
            logGroupName=LOG_GROUP, startTime=start_ms, endTime=end_ms):
        for e in page["events"]:
            try:
                msg = json.loads(e["message"])
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                out.append(msg | {"stream": e["logStreamName"]})
    return out


def reports(lines: list[dict]) -> list[dict]:
    return [line["record"] | line["record"]["metrics"] for line in lines if line.get("type") == "platform.report"]


def fmt(values: list[float], digits: int = 2) -> str:
    if not values:
        return "-"
    lo, hi = min(values), max(values)
    return f"{lo:.{digits}f}" if round(lo, digits) == round(hi, digits) else f"{lo:.{digits}f}–{hi:.{digits}f}"


def cold_phase(url: str, user: int, n: int, logs) -> None:
    t0 = int(time.time() * 1000) - 1000
    with ThreadPoolExecutor(n) as pool:
        results = list(pool.map(lambda _: call(url, user), range(n)))
    t1 = int(time.time() * 1000)
    time.sleep(LOG_DELAY_S)
    lines = read_logs(logs, t0, t1 + 60_000)

    timeouts = [line for line in lines if line.get("type") == "platform.initReport"
                and line["record"].get("status") == "timeout" and line["record"].get("phase") == "init"]
    init_logs = [line for line in lines if "initS" in line]
    model_logs = [line for line in lines if "loadS" in line]
    waits = [line["modelWaitS"] for line in lines if "modelWaitS" in line]
    rep = [r for r in reports(lines) if "initDurationMs" in r]

    print(f"\n## Cold start: {n} request đồng thời, user {user}")
    print(f"- HTTP: {sorted(r['status'] for r in results)}; có X-Cold-Start: {sum(r['cold'] for r in results)}/{n}")
    print(f"- Thời gian phía client (s): {', '.join(f'{r['client_s']:.1f}' for r in sorted(results, key=lambda r: r['client_s']))}")
    print(f"- Init quá trần 10 giây (Lambda init lại trong request): {len(timeouts)}")
    print(f"- initDurationMs của init thành công (s): {fmt([r['initDurationMs'] / 1000 for r in rep])}")
    print(f"- Pha init kết thúc khi model chưa nạp xong: {sum(not line.get('modelReady', True) for line in init_logs)}"
          f"/{len(init_logs)}; request đầu chờ model (s): {fmt(waits)}")
    print(f"- Import geolife_api (s): {fmt([line['importS'] for line in init_logs])}")
    print(f"- Pha init theo log của handler, từ lúc import (s): {fmt([line['initS'] for line in init_logs])}")
    print(f"- Tải model (s): {fmt([line['downloadS'] for line in model_logs])}")
    print(f"- Nạp model (s): {fmt([line['loadS'] for line in model_logs])}")
    print(f"- Chạy thử (s): {fmt([line['warmUpS'] for line in model_logs])}")
    print(f"- RAM sau request đầu (MB): {fmt([r['maxMemoryUsedMB'] for r in reports(lines)], 0)}")


def warm_phase(url: str, users: list[int], repeat: int, logs) -> None:
    print(f"\n## Khi ấm: mỗi user {repeat} lần, tuần tự")
    print("| User | Client (s) | Lambda durationMs (s) | RAM tối đa (MB) |")
    print("| --- | --- | --- | --- |")
    for user in users:
        call(url, user)   # environment vừa phục vụ user này một lần, giống trạng thái khi đã dùng lại
        t0 = int(time.time() * 1000)
        results = [call(url, user) for _ in range(repeat)]
        t1 = int(time.time() * 1000)
        time.sleep(LOG_DELAY_S)
        rep = [r for r in reports(read_logs(logs, t0, t1 + 5_000)) if "initDurationMs" not in r]
        warm = [r["client_s"] for r in results if not r["cold"] and r["status"] == 200]
        print(f"| {user} | {fmt(warm)} (median {statistics.median(warm):.2f}) | "
              f"{fmt([r['durationMs'] / 1000 for r in rep])} | {fmt([r['maxMemoryUsedMB'] for r in rep], 0)} |")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="URL của HTTP API (make aws-url)")
    ap.add_argument("--cold", type=int, default=6, help="số request đồng thời ở pha cold start; 0 bỏ pha này")
    ap.add_argument("--users", type=int, nargs="+", default=[83, 14, 153])
    ap.add_argument("--repeat", type=int, default=4)
    a = ap.parse_args(argv)

    url = a.url.rstrip("/")
    logs = boto3.Session(region_name=os.environ.get("AWS_REGION")).client("logs")
    if a.cold:
        cold_phase(url, a.users[0], a.cold, logs)
    if a.repeat:
        warm_phase(url, a.users, a.repeat, logs)


if __name__ == "__main__":
    main()
