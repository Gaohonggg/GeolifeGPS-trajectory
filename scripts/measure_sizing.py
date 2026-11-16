"""Đo RAM đỉnh và thời gian của API dưới giới hạn CPU / RAM của một ECS task, để chọn cỡ task (docs/task_sizing.md).

    uv run python scripts/measure_sizing.py --cpus 0.5 --memory 2g --versions 1 4

Cần stack local đang chạy (`make setup`): Postgres đã nạp dữ liệu, image `geolife-api:local` đã build, `.env` có token
Databricks. Mỗi (giới hạn, registry version) chạy một container mới trên mạng của compose, gọi lần lượt user có số điểm
ở trung vị, phân vị 90 và lớn nhất, rồi gọi N request đồng thời cho user lớn nhất. RAM đỉnh đọc từ
`/sys/fs/cgroup/memory.peak` trong container (cgroup v2): là đỉnh kể từ lúc container khởi động, nên các user được gọi
theo thứ tự tăng dần số điểm.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "geolife-sizing"
PORT = 8011
MB = 1024 * 1024


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=check).stdout.strip()


def read_env(path: Path = ROOT / ".env") -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            out[key.strip()] = value.strip()
    return out


def pick_users(pg_container: str) -> list[tuple[str, int, int]]:
    """(nhãn, user_id, n_points) của user ở trung vị, phân vị 90 và lớn nhất."""
    q = """
    with r as (select user_id, n_points, percent_rank() over (order by n_points) pr from users)
    select 'p50', user_id, n_points from (select * from r order by abs(pr - 0.5) limit 1) a
    union all select 'p90', user_id, n_points from (select * from r order by abs(pr - 0.9) limit 1) b
    union all select 'max', user_id, n_points from (select * from r order by n_points desc limit 1) c"""
    rows = sh("docker", "exec", pg_container, "psql", "-U", "geolife", "-d", "geolife", "-Atc", q).splitlines()
    return [(label, int(uid), int(n)) for label, uid, n in (r.split("|") for r in rows)]


def call(path: str, method: str = "GET", timeout: float = 900) -> tuple[int, float]:
    """(mã HTTP, giây). Mã 0: mất kết nối (container chết hoặc timeout)."""
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"http://localhost:{PORT}{path}", method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except OSError:
        code = 0
    return code, time.perf_counter() - t0


def peak_mb() -> float | None:
    out = sh("docker", "exec", NAME, "cat", "/sys/fs/cgroup/memory.peak", check=False)
    return round(int(out) / MB) if out.isdigit() else None


def state() -> dict:
    out = sh("docker", "inspect", "-f", "{{.State.Running}} {{.State.OOMKilled}} {{.State.ExitCode}}", NAME, check=False)
    running, oom, code = (out.split() + ["", "", ""])[:3]
    return {"running": running == "true", "oom_killed": oom == "true", "exit_code": code}


def measure(cpus: str, memory: str, version: int, users: list[tuple[str, int, int]], env: dict[str, str],
            network: str, image: str, concurrent: int) -> dict:
    sh("docker", "rm", "-f", NAME, check=False)
    db_url = f"postgresql://geolife:{env['POSTGRES_PASSWORD']}@postgres:5432/geolife"
    model_uri = f"models:/{env['MLFLOW_MODEL_NAME']}/{version}"
    t0 = time.perf_counter()
    sh("docker", "run", "-d", "--name", NAME, "--network", network, "--cpus", cpus, "--memory", memory,
       "--memory-swap", memory,   # không cho swap: hết RAM thì bị giết như trên Fargate
       "--env-file", str(ROOT / ".env"), "-e", f"DATABASE_URL={db_url}", "-e", f"MODEL_URI={model_uri}",
       "-p", f"{PORT}:8000", image)
    res: dict = {"cpus": cpus, "memory": memory, "registry_version": version, "users": []}
    try:
        while call("/v1/health", timeout=5)[0] != 200:
            if time.perf_counter() - t0 > 600 or not state()["running"]:
                res["error"] = "API không lên"
                return res
            time.sleep(1)
        res["startup_s"] = round(time.perf_counter() - t0, 1)
        res["peak_after_startup_mb"] = peak_mb()

        for label, uid, n in users:
            path = f"/v1/users/{uid}/predictions"
            code1, s1 = call(path, "POST")
            code2, s2 = call(path, "POST") if code1 == 200 else (0, 0.0)
            res["users"].append({"label": label, "user_id": uid, "n_points": n, "status": code1,
                                 "first_s": round(s1, 2), "second_s": round(s2, 2) if code2 == 200 else None,
                                 "peak_mb": peak_mb(), **state()})
            if code1 != 200:
                return res

        if concurrent > 1:
            label, uid, n = users[-1]
            out: list[tuple[int, float]] = []
            threads = [threading.Thread(target=lambda: out.append(call(f"/v1/users/{uid}/predictions", "POST")))
                       for _ in range(concurrent)]
            t1 = time.perf_counter()
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            res["concurrent"] = {"n": concurrent, "user_id": uid, "statuses": [c for c, _ in out],
                                 "slowest_s": round(max(s for _, s in out), 2),
                                 "wall_s": round(time.perf_counter() - t1, 2), "peak_mb": peak_mb(), **state()}
        return res
    finally:
        sh("docker", "rm", "-f", NAME, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpus", default="0.5")
    ap.add_argument("--memory", default="2g")
    ap.add_argument("--versions", type=int, nargs="+", required=True, help="registry version cần đo")
    ap.add_argument("--concurrent", type=int, default=2, help="số request đồng thời cho user lớn nhất (0: bỏ)")
    ap.add_argument("--image", default="geolife-api:local")
    ap.add_argument("--network", default="geolife_default")
    ap.add_argument("--postgres", default="geolife-postgres-1")
    ap.add_argument("--out", type=Path, help="ghi kết quả JSON vào file này")
    a = ap.parse_args(argv)

    env = read_env()
    users = pick_users(a.postgres)
    results = []
    for v in a.versions:
        r = measure(a.cpus, a.memory, v, users, env, a.network, a.image, a.concurrent)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    if a.out:
        a.out.write_text(json.dumps(results, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
