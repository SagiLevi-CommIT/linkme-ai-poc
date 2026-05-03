"""Download CloudWatch logs for a simulator run into local run artifacts."""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

from common import config as runtime_config
from knowledge_setup.simulator_question_prewarm import DEFAULT_REPORTS_ROOT

logger = logging.getLogger(__name__)

DEFAULT_LOG_GROUPS = [
    "/ecs/linkme-ai/poc/messages-pusher",
    "/ecs/linkme-ai/poc/cache-service",
    "/ecs/linkme-ai/poc/llm-service",
    "/aws/lambda/linkme-poc-api",
    "/aws/lambda/linkme-poc-preprocessing",
]


def build_session(args: argparse.Namespace) -> boto3.Session:
    kwargs = {"region_name": args.region}
    profile = args.aws_profile or args.profile
    if profile:
        kwargs["profile_name"] = profile
    return boto3.Session(**kwargs)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "log_group"


def collect_group(
    logs: Any,
    *,
    log_group: str,
    run_id: str,
    start_time_ms: int | None,
    end_time_ms: int | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "logGroupName": log_group,
        "filterPattern": f'"{run_id}"',
    }
    if start_time_ms is not None:
        kwargs["startTime"] = start_time_ms
    if end_time_ms is not None:
        kwargs["endTime"] = end_time_ms
    while True:
        try:
            response = logs.filter_log_events(**kwargs)
        except logs.exceptions.ResourceNotFoundException:
            logger.warning("Log group does not exist: %s", log_group)
            return events
        events.extend(response.get("events", []))
        next_token = response.get("nextToken")
        if not next_token:
            return events
        kwargs["nextToken"] = next_token


def run_collect(args: argparse.Namespace) -> dict[str, Any]:
    session = build_session(args)
    logs = session.client("logs")
    run_dir = Path(args.reports_root).resolve() / args.run_id
    cloudwatch_dir = run_dir / "cloudwatch"
    cloudwatch_dir.mkdir(parents=True, exist_ok=True)
    groups = args.log_group or DEFAULT_LOG_GROUPS
    summary = {
        "run_id": args.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "log_groups": [],
    }
    for group in groups:
        events = collect_group(
            logs,
            log_group=group,
            run_id=args.run_id,
            start_time_ms=args.start_time_ms,
            end_time_ms=args.end_time_ms,
        )
        output = cloudwatch_dir / f"{safe_name(group)}.jsonl"
        output.write_text(
            "".join(json.dumps(event, ensure_ascii=False, default=str) + "\n" for event in events),
            encoding="utf-8",
        )
        summary["log_groups"].append(
            {
                "log_group": group,
                "events": len(events),
                "output": str(output),
            }
        )
    summary_path = cloudwatch_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect simulator CloudWatch logs into reports/simulator-runs/<RUN_ID>/cloudwatch/.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--log-group", action="append", default=[])
    parser.add_argument("--start-time-ms", type=int)
    parser.add_argument("--end-time-ms", type=int)
    parser.add_argument("--region", default=runtime_config.AWS_REGION)
    parser.add_argument("--profile", default="", help="Alias for --aws-profile")
    parser.add_argument("--aws-profile", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_arg_parser().parse_args(argv)
    try:
        run_collect(args)
    except Exception as exc:
        logger.error("CloudWatch log collection failed: %s", exc, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
