"""Report simulator expected-vs-actual routing for a prewarm run."""

from __future__ import annotations

import argparse
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from common import config as runtime_config

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "simulator_question_prewarm_report.json"
DEFAULT_REPORTS_ROOT = REPO_ROOT / "reports" / "simulator-runs"


def classify_actual(item: dict[str, Any]) -> str:
    source = str(item.get("source", ""))
    cache_tier = str(item.get("cache_tier", ""))
    if source == "exact_cache" or cache_tier == "exact_hit":
        return "exact_cache"
    if source in {"semantic_cache", "borderline_adapt"} or cache_tier in {
        "semantic_high_hit",
        "semantic_borderline",
    }:
        return "semantic_cache"
    if source.startswith("llm_") or cache_tier == "full_miss":
        return "full_miss"
    return source or "unknown"


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def query_results(
    *,
    session: boto3.Session,
    table_name: str,
    gsi_name: str,
    run_id: str,
) -> list[dict[str, Any]]:
    table = session.resource("dynamodb").Table(table_name)
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "IndexName": gsi_name,
        "KeyConditionExpression": Key("run_id").eq(run_id),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def build_report(manifest: dict[str, Any], actual_items: list[dict[str, Any]]) -> dict[str, Any]:
    messages = manifest.get("messages", [])
    expected_by_id = {item["message_id"]: item for item in messages}
    actual_by_id = {item.get("message_id"): item for item in actual_items}
    actual_route_counts: dict[str, int] = {}
    for item in actual_items:
        route = classify_actual(item)
        actual_route_counts[route] = actual_route_counts.get(route, 0) + 1

    missing = sorted(set(expected_by_id) - set(actual_by_id))
    unexpected = sorted(str(mid) for mid in set(actual_by_id) - set(expected_by_id) if mid)
    route_mismatches = []
    tenant_issues = []
    failures = []
    per_message_results = []
    for message_id, expected in expected_by_id.items():
        actual = actual_by_id.get(message_id)
        if not actual:
            per_message_results.append(
                {
                    "run_id": manifest["run_id"],
                    "message_id": message_id,
                    "lead_id": expected.get("lead_id", ""),
                    "question_text": expected.get("question_text", ""),
                    "expected_route": expected.get("expected_route", ""),
                    "actual_route": "",
                    "cache_tier": "",
                    "model_used": "",
                    "score": None,
                    "status": "failed",
                    "error": "missing_result",
                    "processing_time_ms": None,
                }
            )
            continue
        actual_route = classify_actual(actual)
        status = "success" if expected["expected_route"] == actual_route else "failed"
        error = "" if status == "success" else "route_mismatch"
        if expected["expected_route"] != actual_route:
            route_mismatches.append(
                {
                    "message_id": message_id,
                    "lead_id": expected["lead_id"],
                    "expected_route": expected["expected_route"],
                    "actual_route": actual_route,
                    "source": actual.get("source", ""),
                    "cache_tier": actual.get("cache_tier", ""),
                }
            )
        if actual.get("run_id") != manifest["run_id"]:
            failures.append({"message_id": message_id, "issue": "wrong_run_id", "actual_run_id": actual.get("run_id")})
            status = "failed"
            error = "wrong_run_id"
        if actual.get("tenant_id") and actual.get("tenant_id") != expected["tenant_id"]:
            tenant_issues.append(
                {
                    "message_id": message_id,
                    "expected_tenant_id": expected["tenant_id"],
                    "actual_tenant_id": actual.get("tenant_id"),
                }
            )
            status = "failed"
            error = "tenant_mismatch"
        if actual.get("lead_id") and actual.get("lead_id") != expected["lead_id"]:
            tenant_issues.append(
                {
                    "message_id": message_id,
                    "expected_lead_id": expected["lead_id"],
                    "actual_lead_id": actual.get("lead_id"),
                }
            )
            status = "failed"
            error = "lead_mismatch"
        if actual.get("source") in {"profile_missing", "unknown"} or actual.get("answer", None) == "":
            failures.append({"message_id": message_id, "issue": "failed_or_empty_answer", "source": actual.get("source")})
            status = "failed"
            error = "failed_or_empty_answer"
        per_message_results.append(
            {
                "run_id": actual.get("run_id", manifest["run_id"]),
                "message_id": message_id,
                "lead_id": expected.get("lead_id", ""),
                "question_text": expected.get("question_text", ""),
                "expected_route": expected.get("expected_route", ""),
                "actual_route": actual_route,
                "cache_tier": actual.get("cache_tier", ""),
                "model_used": actual.get("model_used", ""),
                "score": json_safe(actual.get("similarity_score")),
                "status": status,
                "error": error,
                "processing_time_ms": json_safe(actual.get("latency_ms")),
            }
        )

    expected_counts = manifest.get("expected_route_counts") or count_by(messages, "expected_route")
    hit_count = actual_route_counts.get("exact_cache", 0) + actual_route_counts.get("semantic_cache", 0)
    miss_count = actual_route_counts.get("full_miss", 0)
    processed = len(actual_items)
    exact_expected = int(expected_counts.get("exact_cache", 0))
    semantic_expected = int(expected_counts.get("semantic_cache", 0))
    full_miss_expected = int(expected_counts.get("full_miss", 0))
    latencies = [
        float(item.get("latency_ms"))
        for item in actual_items
        if item.get("latency_ms") not in (None, "")
    ]
    manifest_stats = manifest.get("stats", {})
    generation_stats = manifest.get("run_level_statistics", {})
    generation_tokens = generation_stats.get("token_usage", {"unavailable": True})
    bedrock_generation_calls = generation_stats.get("bedrock_generation_calls")
    if bedrock_generation_calls in (None, "unavailable"):
        bedrock_generation_calls = int(manifest_stats.get("bedrock_generation_calls", 0)) + int(
            manifest_stats.get("runtime_bedrock_generation_calls", 0)
        )
    return {
        "run_id": manifest["run_id"],
        "creators_processed": manifest_stats.get("creators_processed", 0),
        "total_s3_simulator_questions": len(messages),
        "exact_cache_seeds": manifest_stats.get("exact_cache_seeds", 0),
        "semantic_cache_seeds": manifest_stats.get("semantic_cache_seeds", 0),
        "full_miss_questions": manifest_stats.get("full_miss_questions", 0),
        "expected_route_counts": expected_counts,
        "actual_route_counts": actual_route_counts,
        "processed_results": processed,
        "total_successes": sum(1 for item in per_message_results if item["status"] == "success"),
        "total_failures": sum(1 for item in per_message_results if item["status"] == "failed"),
        "cache_hit_rate": round(hit_count / processed, 6) if processed else 0.0,
        "cache_miss_rate": round(miss_count / processed, 6) if processed else 0.0,
        "exact_hit_rate": round(actual_route_counts.get("exact_cache", 0) / exact_expected, 6) if exact_expected else 0.0,
        "semantic_hit_rate": round(actual_route_counts.get("semantic_cache", 0) / semantic_expected, 6) if semantic_expected else 0.0,
        "full_miss_rate": round(actual_route_counts.get("full_miss", 0) / full_miss_expected, 6) if full_miss_expected else 0.0,
        "kb_llm_calls_inferred": miss_count,
        "kb_retrieval_calls_inferred": miss_count,
        "llm_calls_inferred": sum(
            1
            for item in actual_items
            if str(item.get("source", "")).startswith("llm_") or item.get("source") == "borderline_adapt"
        ),
        "failures": failures,
        "missing_message_ids": missing,
        "unexpected_message_ids": unexpected,
        "route_mismatches": route_mismatches,
        "tenant_isolation_issues": tenant_issues,
        "per_message_results": per_message_results,
        "run_level_statistics": {
            "total_creators": manifest_stats.get("creators_processed", 0),
            "total_generated_questions": manifest_stats.get("total_generated_questions", 0),
            "total_simulator_questions_uploaded": len(messages),
            "expected_route_counts": expected_counts,
            "actual_route_counts": actual_route_counts,
            "expected_bedrock_misses": full_miss_expected,
            "expected_exact_hits": exact_expected,
            "expected_semantic_hits": semantic_expected,
            "exact_hit_rate": round(actual_route_counts.get("exact_cache", 0) / exact_expected, 6) if exact_expected else 0.0,
            "semantic_hit_rate": round(actual_route_counts.get("semantic_cache", 0) / semantic_expected, 6) if semantic_expected else 0.0,
            "full_miss_rate": round(actual_route_counts.get("full_miss", 0) / full_miss_expected, 6) if full_miss_expected else 0.0,
            "nova_retries": manifest_stats.get("nova_retries", "unavailable"),
            "haiku_fallbacks": manifest_stats.get("haiku_fallbacks", "unavailable"),
            "sonnet_fallbacks": manifest_stats.get("sonnet_fallbacks", "unavailable"),
            "opus_fallbacks": manifest_stats.get("opus_fallbacks", "unavailable"),
            "model_escalation_attempts": manifest_stats.get("model_escalation_attempts", "unavailable"),
            "failed_similarity_validations": manifest_stats.get("failed_similarity_validations", "unavailable"),
            "total_successes": sum(1 for item in per_message_results if item["status"] == "success"),
            "total_failures": sum(1 for item in per_message_results if item["status"] == "failed"),
            "bedrock_generation_calls": bedrock_generation_calls,
            "bedrock_llm_calls": sum(
                1
                for item in actual_items
                if str(item.get("source", "")).startswith("llm_") or item.get("source") == "borderline_adapt"
            ),
            "sagemaker_embedding_calls": manifest_stats.get("sagemaker_embedding_calls", "unavailable"),
            "kb_retrieval_calls": miss_count,
            "total_runtime_seconds": manifest.get("runtime_seconds", "unavailable"),
            "average_latency_per_stage": {
                "result_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else "unavailable",
                "cache_service_exact_or_semantic": "unavailable",
                "kb_retrieve": "unavailable",
                "bedrock_invoke": "unavailable",
            },
            "token_usage": {
                "generation": generation_tokens,
                "pipeline_llm": "unavailable",
            },
        },
        "run_id_coverage": {
            "expected": len(messages),
            "actual": processed,
            "missing": len(missing),
            "unexpected": len(unexpected),
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize simulator prewarm run results from DynamoDB.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--results-table", default=runtime_config.RESULTS_TABLE)
    parser.add_argument("--results-gsi", default="run-id-processed-at")
    parser.add_argument("--region", default=runtime_config.AWS_REGION)
    parser.add_argument("--profile", default="", help="Alias for --aws-profile")
    parser.add_argument("--aws-profile", default="")
    parser.add_argument("--output-report", default=str(REPO_ROOT / "simulator_actual_route_report.json"))
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_arg_parser().parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.run_id:
        manifest["run_id"] = args.run_id
    session_kwargs = {"region_name": args.region}
    profile = args.aws_profile or args.profile
    if profile:
        session_kwargs["profile_name"] = profile
    session = boto3.Session(**session_kwargs)
    actual_items = query_results(
        session=session,
        table_name=args.results_table,
        gsi_name=args.results_gsi,
        run_id=manifest["run_id"],
    )
    report = build_report(manifest, actual_items)
    run_dir = Path(args.reports_root).resolve() / manifest["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "per_message_processing_results.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in report["per_message_results"]),
        encoding="utf-8",
    )
    (run_dir / "final_summary_report.json").write_text(
        json.dumps(json_safe(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path(args.output_report).write_text(json.dumps(json_safe(report), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(json_safe(report), indent=2, sort_keys=True))
    return 0 if not report["failures"] and not report["tenant_isolation_issues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
