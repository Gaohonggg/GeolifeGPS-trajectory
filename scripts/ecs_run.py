"""Chạy một lệnh trong task definition `geolife-ops` (stack data) trên Fargate, in log tới khi task dừng.

    uv run python scripts/ecs_run.py python -m geolife_api.migrate
    uv run python scripts/ecs_run.py python -m geolife_api.seed --data-dir s3://<bucket>/data/preprocess/v_1

Task chạy ở public subnet với public IP (để kéo image, đọc S3, ghi log) và security group của task, nên kết nối
được RDS trong private subnet. Mã thoát của script là mã thoát của container.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import boto3

from geolife.paths import ROOT

POLL_S = 5


def tf_outputs(stack: str) -> dict:
    out = subprocess.run(["terraform", f"-chdir={ROOT / 'infra' / stack}", "output", "-json"],
                         capture_output=True, text=True, check=True).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def run(command: list[str], memory_mb: int | None = None) -> int:
    foundation, data = tf_outputs("foundation"), tf_outputs("data")
    session = boto3.Session(region_name=foundation["region"])
    ecs, logs = session.client("ecs"), session.client("logs")

    resp = ecs.run_task(
        cluster=foundation["ecs_cluster_name"],
        taskDefinition=data["ops_task_definition_arn"],
        launchType="FARGATE",
        networkConfiguration={"awsvpcConfiguration": {
            "subnets": foundation["public_subnet_ids"],
            "securityGroups": [foundation["task_security_group_id"]],
            "assignPublicIp": "ENABLED",
        }},
        overrides={"containerOverrides": [{"name": "ops", "command": command}],
                   # RAM của task (MB) cho riêng lần chạy này; phải là tổ hợp hợp lệ với 1 vCPU của task definition
                   **({"memory": str(memory_mb)} if memory_mb else {})},
    )
    if resp["failures"]:
        raise SystemExit(f"run_task lỗi: {resp['failures']}")
    task_arn = resp["tasks"][0]["taskArn"]
    task_id = task_arn.rsplit("/", 1)[-1]
    stream = f"ops/ops/{task_id}"
    print(f"task {task_id}: {' '.join(command)}", flush=True)

    t0, status, token = time.monotonic(), None, None
    while True:
        task = ecs.describe_tasks(cluster=foundation["ecs_cluster_name"], tasks=[task_arn])["tasks"][0]
        if task["lastStatus"] != status:
            status = task["lastStatus"]
            print(f"[{time.monotonic() - t0:5.0f}s] {status}", flush=True)
        token = _print_logs(logs, foundation["log_group_name"], stream, token)
        if status == "STOPPED":
            break
        time.sleep(POLL_S)

    time.sleep(POLL_S)   # log tới CloudWatch trễ vài giây sau khi container dừng
    _print_logs(logs, foundation["log_group_name"], stream, token)
    container = task["containers"][0]
    code = container.get("exitCode")
    print(f"[{time.monotonic() - t0:5.0f}s] exit {code}; {task.get('stoppedReason', '')}", flush=True)
    if code is None:
        print(f"container không chạy: {container.get('reason', '')}", file=sys.stderr)
        return 1
    return code


def _print_logs(logs, group: str, stream: str, token: str | None) -> str | None:
    """In các dòng log mới; trả về token để lần sau đọc tiếp."""
    while True:
        kwargs = {"logGroupName": group, "logStreamName": stream, "startFromHead": True}
        if token:
            kwargs["nextToken"] = token
        try:
            resp = logs.get_log_events(**kwargs)
        except logs.exceptions.ResourceNotFoundException:   # stream chỉ có sau khi container chạy
            return token
        for e in resp["events"]:
            print(f"  {e['message']}", flush=True)
        if resp["nextForwardToken"] == token:
            return token
        token = resp["nextForwardToken"]


def main(argv=None):
    ap = argparse.ArgumentParser(usage="ecs_run.py [--memory MB] <lệnh> ...", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--memory", type=int, help="RAM của task (MB), mặc định theo task definition")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    if not a.command:
        ap.error("thiếu lệnh")
    return run(a.command, a.memory)


if __name__ == "__main__":
    sys.exit(main())
