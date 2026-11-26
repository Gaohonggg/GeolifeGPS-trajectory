"""Kiểm canary qua HTTP API: request tới alias live chia theo Lambda version thế nào, version mới có lỗi hay chậm hơn.

    uv run python scripts/canary_check.py [-n 100] [--url <url của HTTP API>]

Gọi tuần tự `-n` request predict, user trải đều trên danh sách user của bản dữ liệu đang phục vụ. Gọi tuần tự nên
mỗi Lambda version chỉ cần một environment; request đầu tiên tới mỗi environment mới có header `X-Cold-Start`.

Lambda version thực thi từng request đọc từ log, không từ response (response lỗi không chứa model):
header `apigw-requestid` → access log của HTTP API (`lambdaRequestId`) → dòng `platform.report` của function, nằm
trong log stream có tên chứa Lambda version (`2026/11/26/[6]…`). Request bị từ chối trước khi vào function
(throttling, reserved concurrency) không có Lambda version.

Điều kiện chốt canary, so version của alias challenger với version của live:
- tỉ lệ request tới version mới sát `canary_weight`;
- version mới không có 5xx;
- latency p95 phía client của các request không cold start không quá 1,5 lần version cũ. Version mới nhận ít
  request hơn nên tỉ lệ cold start của nó cao hơn; gộp cả cold start thì p95 của nó luôn thua.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field

import boto3
import httpx

from geolife import publish
from geolife.paths import ROOT

APP_DIR = ROOT / "infra" / "app"
FUNCTION_LOGS = "/aws/lambda/geolife-api"
ACCESS_LOGS = "/aws/apigateway/geolife-api"
# Log tới CloudWatch Logs trễ sau khi request xong; access log của HTTP API có thể trễ hơn một phút.
LOG_POLL_S = 15
LOG_WAIT_S = 180
MAX_P95_RATIO = 1.5
STREAM_VERSION = re.compile(r"\[(\d+|\$LATEST)\]")


@dataclass
class Call:
    user: int
    status: int
    client_s: float
    cold: bool
    apigw_id: str | None
    model: str | None
    lambda_version: str | None = None
    duration_ms: float | None = None


@dataclass
class Group:
    calls: list[Call] = field(default_factory=list)

    @property
    def warm_client_s(self) -> list[float]:
        return [c.client_s for c in self.calls if not c.cold and c.status < 500]


def p(values: list[float], q: float) -> float | None:
    """Phân vị theo nearest-rank; None nếu rỗng."""
    if not values:
        return None
    s = sorted(values)
    return s[max(math.ceil(q * len(s)) - 1, 0)]


def terraform_outputs() -> dict:
    out = subprocess.run(["terraform", f"-chdir={APP_DIR}", "output", "-json"], check=True, text=True,
                         stdout=subprocess.PIPE).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def serving_users(session: boto3.Session, data_version: int) -> list[int]:
    """User trong manifest của bản dữ liệu đang phục vụ trên S3."""
    body = session.client("s3").get_object(Bucket=publish.default_bucket(session),
                                           Key=f"data/serving/v_{data_version}/manifest.json")["Body"].read()
    return sorted(u["user"] for u in json.loads(body)["users"])


def spread(users: list[int], n: int) -> list[int]:
    """`n` user cách đều trong danh sách; n lớn hơn số user thì mỗi user được gọi nhiều lần."""
    return [users[i * len(users) // n] for i in range(n)]


def call(url: str, user: int) -> Call:
    t = time.perf_counter()
    r = httpx.post(f"{url}/v1/users/{user}/predictions", timeout=60)
    elapsed = time.perf_counter() - t
    try:
        m = r.json()["model"]
        model = f"{m['name']} v{m['version']}"
    except (ValueError, KeyError, TypeError):
        model = None
    return Call(user, r.status_code, elapsed, r.headers.get("x-cold-start") == "1",
                r.headers.get("apigw-requestid"), model)


def log_events(logs, group: str, start_ms: int, end_ms: int):
    for page in logs.get_paginator("filter_log_events").paginate(
            logGroupName=group, startTime=start_ms, endTime=end_ms):
        for e in page["events"]:
            try:
                msg = json.loads(e["message"])
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                yield msg, e["logStreamName"]


def attach_versions(calls: list[Call], logs, start_ms: int, end_ms: int) -> int:
    """Gắn Lambda version và `durationMs` cho từng request qua access log và log của function;
    trả số request chưa ghép được với access log."""
    lambda_ids = {msg["requestId"]: msg.get("lambdaRequestId")
                  for msg, _ in log_events(logs, ACCESS_LOGS, start_ms, end_ms) if "requestId" in msg}
    reports = {}
    for msg, stream in log_events(logs, FUNCTION_LOGS, start_ms, end_ms):
        if msg.get("type") == "platform.report":
            m = STREAM_VERSION.search(stream)
            reports[msg["record"]["requestId"]] = (m.group(1) if m else None,
                                                   msg["record"]["metrics"].get("durationMs"))
    for c in calls:
        version, duration = reports.get(lambda_ids.get(c.apigw_id), (None, None))
        c.lambda_version, c.duration_ms = version, duration
    return sum(c.apigw_id not in lambda_ids for c in calls)


def wait_for_logs(calls: list[Call], logs, start_ms: int, end_ms: int) -> None:
    """Đọc lại log tới khi mọi request ghép được với access log, tối đa LOG_WAIT_S giây."""
    deadline = time.monotonic() + LOG_WAIT_S
    while True:
        time.sleep(LOG_POLL_S)
        missing = attach_versions(calls, logs, start_ms, end_ms)
        if missing == 0 or time.monotonic() > deadline:
            break
        print(f"  chờ access log: còn {missing} request")
    if missing:
        print(f"  {missing} request không có trong access log sau {LOG_WAIT_S} giây")


def fmt(x: float | None, digits: int = 2) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100, help="số request")
    ap.add_argument("--url", help="URL của HTTP API; mặc định đọc output của stack app")
    ap.add_argument("--data-version", type=int, default=1)
    a = ap.parse_args(argv)

    outputs = terraform_outputs()
    url = a.url or outputs["url"]
    live, challenger = outputs["live"], outputs["challenger"]
    old_v, new_v = str(live["lambda_version"]), str(challenger["lambda_version"])
    weight = live["canary_weight"]
    print(f"live: Lambda version {old_v} (registry v{live['model_version']}); "
          f"challenger: Lambda version {new_v} (registry v{challenger['model_version']}); canary_weight {weight}%")
    if old_v == new_v:
        print("không có canary: challenger trùng live")
    elif weight == 0:
        print("canary_weight 0: version mới không nhận request qua live")

    session = boto3.Session()
    users = spread(serving_users(session, a.data_version), a.n)
    start_ms = int(time.time() * 1000) - 1000
    calls = []
    for i, user in enumerate(users, 1):
        calls.append(call(url, user))
        if i % 20 == 0:
            print(f"  {i}/{a.n}")
    end_ms = int(time.time() * 1000)
    wait_for_logs(calls, session.client("logs"), start_ms, end_ms + 60_000)

    groups: dict[str, Group] = defaultdict(Group)
    for c in calls:
        groups[c.lambda_version or "-"].calls.append(c)

    print(f"\n{a.n} request tuần tự, {len(set(users))} user\n")
    registry = {old_v: live["model_version"], new_v: challenger["model_version"]}
    print("| Lambda version | Registry version | Model (response) | Request | Tỉ lệ | 5xx | Cold start | "
          "p50 khi ấm (s) | p95 khi ấm (s) | p95 durationMs khi ấm |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for v in sorted(groups, key=lambda k: (k == "-", k)):
        g = groups[v]
        models = sorted({c.model for c in g.calls if c.model is not None})
        warm_ms = [c.duration_ms for c in g.calls if not c.cold and c.duration_ms is not None]
        reg = f"v{registry[v]}" if v in registry else "-"
        print(f"| {v} | {reg} | {', '.join(models) or '-'} | {len(g.calls)} | "
              f"{100 * len(g.calls) / a.n:.0f}% | {sum(c.status >= 500 for c in g.calls)} | "
              f"{sum(c.cold for c in g.calls)} | {fmt(p(g.warm_client_s, 0.5))} | {fmt(p(g.warm_client_s, 0.95))} | "
              f"{fmt(p(warm_ms, 0.95), 0)} |")
    other = [c for c in calls if c.status not in (200, 404) and c.status < 500]
    if other:
        print(f"\nMã khác 200 / 404 / 5xx: {sorted(c.status for c in other)}")

    if old_v == new_v or weight == 0:
        return
    old, new = groups.get(old_v, Group()), groups.get(new_v, Group())
    share = 100 * len(new.calls) / a.n
    # Sai số chuẩn của tỉ lệ nhị thức; lệch quá 3 lần là bất thường với n request.
    tolerance = 300 * math.sqrt(weight / 100 * (1 - weight / 100) / a.n)
    p95_old, p95_new = p(old.warm_client_s, 0.95), p(new.warm_client_s, 0.95)
    checks = [
        (f"tỉ lệ tới version mới {share:.0f}% so với {weight}% (cho phép ±{tolerance:.0f} điểm %)",
         abs(share - weight) <= tolerance),
        (f"5xx của version mới: {sum(c.status >= 500 for c in new.calls)}",
         all(c.status < 500 for c in new.calls)),
        (f"p95 khi ấm: mới {fmt(p95_new)} s, cũ {fmt(p95_old)} s (tối đa {MAX_P95_RATIO}×)",
         p95_new is not None and p95_old is not None and p95_new <= MAX_P95_RATIO * p95_old),
    ]
    print()
    for text, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print("\nĐủ điều kiện chốt" if all(ok for _, ok in checks) else "\nChưa đủ điều kiện chốt")


if __name__ == "__main__":
    main()
