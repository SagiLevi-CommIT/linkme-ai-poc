"""Wait until DynamoDB has the expected number of simulator results."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

from common import config as runtime_config
from knowledge_setup.simulator_question_prewarm import DEFAULT_REPORTS_ROOT

logger = logging.getLogger(__name__)


def build_session(args: argparse.Namespace) -> boto3.Session:
    kwargs = {"region_name": args.region}
    profile = args.aws_profile or args.profile
    if profile:
        kwargs["profile_name"] = profile
    return boto3.Session(**kwargs)


def count_results(session: boto3.Session, *, table_name: str, gsi_name: str, run_id: str) -> int:
    table = session.resource("dynamodb").Table(table_name)
    total = 0
    kwargs = {
        "IndexName": gsi_name,
        "KeyConditionExpression": Key("run_id").eq(run_id),
        "Select": "COUNT",
    }
    while True:
        response = table.query(**kwargs)
        total += int(response.get("Count", 0))
        if "LastEvaluatedKey" not in response:
            return total
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def run_wait(args: argparse.Namespace) -> dict[str, object]:
    session = build_session(args)
    deadline = time.time() + args.timeout_seconds
    last_count = 0
    while True:
        last_count = count_results(
            session,
            table_name=args.results_table,
            gsi_name=args.results_gsi,
            run_id=args.run_id,
        )
        logger.info("run_id=%s results=%s/%s", args.run_id, last_count, args.expected_count)
        if last_count >= args.expected_count:
            status = "complete"
            break
        if time.time() >= deadline:
            status = "timeout"
            break
        time.sleep(args.poll_seconds)

    report = {
        "run_id": args.run_id,
        "expected_count": args.expected_count,
        "actual_count": last_count,
        "status": status,
    }
    run_dir = Path(args.reports_root).resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    output = run_dir / f"wait_results_{args.expected_count}.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wait for a simulator run to reach an expected DynamoDB result count.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--results-table", default=runtime_config.RESULTS_TABLE)
    parser.add_argument("--results-gsi", default="run-id-processed-at")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--region", default=runtime_config.AWS_REGION)
    parser.add_argument("--profile", default="", help="Alias for --aws-profile")
    parser.add_argument("--aws-profile", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_arg_parser().parse_args(argv)
    try:
        report = run_wait(args)
    except Exception as exc:
        logger.error("Waiting for simulator results failed: %s", exc, exc_info=True)
        return 1
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
