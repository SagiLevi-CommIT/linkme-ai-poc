"""Reset simulator-generated state without touching creator source, KB, or profiles."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr

from common import config as runtime_config
from knowledge_setup.simulator_question_prewarm import (
    DEFAULT_CONFIG,
    DEFAULT_REPORTS_ROOT,
    load_prewarm_config,
    s3_prefix_parts,
)

logger = logging.getLogger(__name__)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def cache_manifest_for_run(reports_root: Path, run_id: str) -> dict[str, Any]:
    return load_json(reports_root / run_id / "cache_prewarm_manifest.json")


def exact_entries_from_manifest(manifest: dict[str, Any]) -> list[dict[str, str]]:
    if "exact_cache_entries" in manifest or "runtime_exact_cache_reset_entries" in manifest:
        return list(manifest.get("exact_cache_entries") or []) + list(
            manifest.get("runtime_exact_cache_reset_entries") or []
        )
    nested = manifest.get("cache_prewarm_manifest", {})
    return list(nested.get("exact_cache_entries") or []) + list(
        nested.get("runtime_exact_cache_reset_entries") or []
    )


def semantic_entries_from_manifest(manifest: dict[str, Any]) -> list[dict[str, str]]:
    if "semantic_cache_entries" in manifest or "runtime_semantic_cache_reset_entries" in manifest:
        return list(manifest.get("semantic_cache_entries") or []) + list(
            manifest.get("runtime_semantic_cache_reset_entries") or []
        )
    nested = manifest.get("cache_prewarm_manifest", {})
    return list(nested.get("semantic_cache_entries") or []) + list(
        nested.get("runtime_semantic_cache_reset_entries") or []
    )


class SimulatorResetter:
    def __init__(
        self,
        *,
        session: boto3.Session,
        exact_cache_table: str,
        memorydb_endpoint: str,
        memorydb_port: int,
    ) -> None:
        self._ddb = session.resource("dynamodb")
        self._s3 = session.client("s3")
        self._exact_cache_table = exact_cache_table
        self._memorydb_endpoint = memorydb_endpoint
        self._memorydb_port = memorydb_port
        self._redis = None

    def delete_exact_keys(self, entries: list[dict[str, str]]) -> int:
        if not entries:
            return 0
        table = self._ddb.Table(self._exact_cache_table)
        deleted = 0
        with table.batch_writer() as batch:
            for entry in entries:
                pk = entry.get("pk")
                if not pk:
                    continue
                batch.delete_item(Key={"pk": pk})
                deleted += 1
        return deleted

    def delete_all_simulator_exact_seeds(
        self,
        *,
        run_id: str = "",
        tenant_ids: set[str] | None = None,
    ) -> int:
        table = self._ddb.Table(self._exact_cache_table)
        filter_expression = Attr("seed_source").eq("simulator_prewarm")
        if run_id:
            filter_expression = filter_expression & Attr("run_id").eq(run_id)
        deleted = 0
        kwargs: dict[str, Any] = {
            "FilterExpression": filter_expression,
            "ProjectionExpression": "pk, tenant_id",
        }
        while True:
            resp = table.scan(**kwargs)
            entries = []
            for item in resp.get("Items", []):
                if tenant_ids and item.get("tenant_id") not in tenant_ids:
                    continue
                entries.append({"pk": item["pk"]})
            deleted += self.delete_exact_keys(entries)
            if "LastEvaluatedKey" not in resp:
                return deleted
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def delete_semantic_keys(self, entries: list[dict[str, str]]) -> int:
        if not entries:
            return 0
        redis_client = self._get_redis()
        keys = [entry["key"] for entry in entries if entry.get("key")]
        if not keys:
            return 0
        deleted = 0
        for key in keys:
            deleted += int(redis_client.delete(key))
        return deleted

    def delete_all_simulator_semantic_seeds(
        self,
        *,
        run_id: str = "",
        tenant_ids: set[str] | None = None,
    ) -> int:
        redis_client = self._get_redis()
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match="cache:*", count=500)
            to_delete = []
            for key in keys:
                seed_source = redis_client.hget(key, "seed_source")
                if seed_source not in {b"simulator_prewarm", "simulator_prewarm"}:
                    continue
                item_run_id = redis_client.hget(key, "run_id")
                item_tenant = redis_client.hget(key, "tenant_id")
                item_run_id = item_run_id.decode() if isinstance(item_run_id, bytes) else item_run_id
                item_tenant = item_tenant.decode() if isinstance(item_tenant, bytes) else item_tenant
                if run_id and item_run_id != run_id:
                    continue
                if tenant_ids and item_tenant not in tenant_ids:
                    continue
                to_delete.append(key)
            if to_delete:
                deleted += int(redis_client.delete(*to_delete))
            if cursor == 0:
                return deleted

    def delete_s3_prefix(self, *, bucket: str, prefix: str) -> int:
        deleted = 0
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            for index in range(0, len(objects), 1000):
                chunk = objects[index:index + 1000]
                if not chunk:
                    continue
                self._s3.delete_objects(Bucket=bucket, Delete={"Objects": chunk})
                deleted += len(chunk)
        return deleted

    def _get_redis(self):  # type: ignore[no-untyped-def]
        if not self._memorydb_endpoint:
            raise RuntimeError("MEMORYDB_ENDPOINT or --memorydb-endpoint is required")
        if self._redis is None:
            import redis as redis_lib

            self._redis = redis_lib.Redis(
                host=self._memorydb_endpoint,
                port=self._memorydb_port,
                decode_responses=False,
                ssl=True,
            )
        return self._redis


def safe_delete_run_dir(reports_root: Path, run_id: str) -> bool:
    root = reports_root.resolve()
    target = (root / run_id).resolve()
    if root not in target.parents:
        raise ValueError(f"refusing to delete outside reports root: {target}")
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def build_session(args: argparse.Namespace) -> boto3.Session:
    kwargs = {"region_name": args.region}
    profile = args.aws_profile or args.profile
    if profile:
        kwargs["profile_name"] = profile
    return boto3.Session(**kwargs)


def run_reset(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_prewarm_config(Path(args.config))
    reports_root = Path(args.reports_root)
    manifest = {}
    if args.manifest:
        manifest = load_json(Path(args.manifest))
    elif args.run_id:
        manifest = cache_manifest_for_run(reports_root, args.run_id)
    run_id = args.run_id or manifest.get("run_id", "")
    tenant_ids = set(args.tenant_id or [])
    exact_entries = exact_entries_from_manifest(manifest)
    semantic_entries = semantic_entries_from_manifest(manifest)
    session = build_session(args)
    resetter = SimulatorResetter(
        session=session,
        exact_cache_table=args.exact_cache_table or cfg.exact_cache_table,
        memorydb_endpoint=args.memorydb_endpoint or runtime_config.MEMORYDB_ENDPOINT,
        memorydb_port=args.memorydb_port,
    )

    report: dict[str, Any] = {
        "run_id": run_id,
        "exact_cache_deleted": 0,
        "semantic_cache_deleted": 0,
        "s3_input_deleted": 0,
        "local_reports_deleted": False,
        "notes": [
            "Did not touch Bedrock KB, creator source data, or profiles table.",
        ],
    }
    if args.skip_cache:
        report["notes"].append("Skipped cache deletion by request; use simulator_seed_cache_task.py --mode reset inside the VPC for MemoryDB.")
    else:
        if exact_entries:
            report["exact_cache_deleted"] += resetter.delete_exact_keys(exact_entries)
        if semantic_entries:
            report["semantic_cache_deleted"] += resetter.delete_semantic_keys(semantic_entries)
        if args.all_simulator_seeds:
            report["exact_cache_deleted"] += resetter.delete_all_simulator_exact_seeds(
                run_id=run_id if args.filter_seed_run_id else "",
                tenant_ids=tenant_ids or None,
            )
            report["semantic_cache_deleted"] += resetter.delete_all_simulator_semantic_seeds(
                run_id=run_id if args.filter_seed_run_id else "",
                tenant_ids=tenant_ids or None,
            )
    if args.clean_s3_input:
        if not run_id:
            raise ValueError("--run-id is required with --clean-s3-input")
        bucket, prefix = s3_prefix_parts(args.s3_output_prefix or cfg.s3_output_prefix, run_id)
        report["s3_input_deleted"] = resetter.delete_s3_prefix(bucket=bucket, prefix=prefix)
        report["s3_input_prefix"] = f"s3://{bucket}/{prefix}"
    if args.clean_local_reports:
        if not run_id:
            raise ValueError("--run-id is required with --clean-local-reports")
        report["local_reports_deleted"] = safe_delete_run_dir(reports_root, run_id)

    output_dir = reports_root / (run_id or "adhoc-reset")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "reset_report.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reset simulator-generated cache and input state safely.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--tenant-id", action="append", default=[])
    parser.add_argument("--all-simulator-seeds", action="store_true")
    parser.add_argument("--skip-cache", action="store_true")
    parser.add_argument("--filter-seed-run-id", action="store_true")
    parser.add_argument("--clean-s3-input", action="store_true")
    parser.add_argument("--clean-local-reports", action="store_true")
    parser.add_argument("--s3-output-prefix", default="")
    parser.add_argument("--exact-cache-table", default="")
    parser.add_argument("--memorydb-endpoint", default="")
    parser.add_argument("--memorydb-port", type=int, default=runtime_config.MEMORYDB_PORT)
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--region", default=runtime_config.AWS_REGION)
    parser.add_argument("--profile", default="", help="Alias for --aws-profile")
    parser.add_argument("--aws-profile", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_arg_parser().parse_args(argv)
    try:
        run_reset(args)
    except Exception as exc:
        logger.error("Simulator reset failed: %s", exc, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
