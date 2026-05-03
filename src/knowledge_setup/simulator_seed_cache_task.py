"""Run a one-off ECS task inside the VPC to seed simulator cache manifests."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import boto3

from common import config as runtime_config
from knowledge_setup.simulator_question_prewarm import (
    DEFAULT_CONFIG,
    DEFAULT_REPORTS_ROOT,
    load_prewarm_config,
    s3_prefix_parts,
)

logger = logging.getLogger(__name__)


SEEDER_CODE = r'''
import json
import os
import re
import struct
import urllib.request
from datetime import datetime, timezone

import boto3
import redis

REGION = os.environ.get("AWS_REGION", "us-west-2")
RUN_ID = os.environ["RUN_ID"]
MANIFEST_URL = os.environ["MANIFEST_URL"]
MODE = os.environ.get("MODE", "seed")
CACHE_TABLE = os.environ.get("CACHE_TABLE", "ddb-linkme-poc-cache")
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "linkme-poc-embedding")
MEMORYDB_ENDPOINT = os.environ["MEMORYDB_ENDPOINT"]
MEMORYDB_PORT = int(os.environ.get("MEMORYDB_PORT", "6379"))
INDEX_NAME = "idx:semantic_cache"
KEY_PREFIX = "cache:"
VECTOR_DIM = 768

def normalize_question(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text

def question_hash(normalized_text):
    import hashlib
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

def pack_vector(embedding):
    return struct.pack(f"{len(embedding)}f", *embedding)

def embed_batch(texts, batch_size=128):
    client = boto3.client("sagemaker-runtime", region_name=REGION)
    vectors = []
    for index in range(0, len(texts), batch_size):
        chunk = texts[index:index + batch_size]
        response = client.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType="application/json",
            Body=json.dumps({"inputs": chunk}).encode("utf-8"),
        )
        vectors.extend(json.loads(response["Body"].read().decode("utf-8")))
    return vectors

def ensure_index(redis_client):
    try:
        redis_client.execute_command(
            "FT.CREATE", INDEX_NAME,
            "ON", "HASH",
            "PREFIX", "1", KEY_PREFIX,
            "SCHEMA",
            "tenant_id", "TAG",
            "question", "TEXT",
            "answer", "TEXT",
            "vector", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32",
            "DIM", str(VECTOR_DIM),
            "DISTANCE_METRIC", "COSINE",
        )
    except Exception as exc:
        lowered = str(exc).lower()
        if "already exists" not in lowered and "index already" not in lowered:
            raise

manifest = json.loads(urllib.request.urlopen(MANIFEST_URL, timeout=60).read().decode("utf-8"))
ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(CACHE_TABLE)
redis_client = redis.Redis(host=MEMORYDB_ENDPOINT, port=MEMORYDB_PORT, decode_responses=False, ssl=True)

if MODE == "reset":
    exact = manifest.get("exact_cache_entries", []) + manifest.get("runtime_exact_cache_reset_entries", [])
    semantic = manifest.get("semantic_cache_entries", []) + manifest.get("runtime_semantic_cache_reset_entries", [])
else:
    exact = manifest.get("exact_cache_entries", [])
    semantic = manifest.get("semantic_cache_entries", [])
seeded_at = datetime.now(timezone.utc).isoformat()
if MODE == "reset":
    exact_deleted = 0
    with table.batch_writer() as batch:
        for entry in exact:
            if entry.get("pk"):
                batch.delete_item(Key={"pk": entry["pk"]})
                exact_deleted += 1
    semantic_deleted = 0
    for entry in semantic:
        if entry.get("key"):
            semantic_deleted += int(redis_client.delete(entry["key"]))
    print(json.dumps({
        "event": "simulator_cache_reset_complete",
        "run_id": RUN_ID,
        "exact_cache_deleted": exact_deleted,
        "semantic_cache_deleted": semantic_deleted,
    }))
else:
    ensure_index(redis_client)
    for entry in exact:
        table.put_item(Item={
            "pk": entry["pk"],
            "tenant_id": entry["tenant_id"],
            "question": entry["question"],
            "answer": entry["answer"],
            "seed_source": "simulator_prewarm",
            "run_id": RUN_ID,
            "seeded_at": seeded_at,
        })

    vectors = embed_batch([entry["question"] for entry in semantic])
    for entry, vector in zip(semantic, vectors):
        redis_client.hset(entry["key"], mapping={
            "tenant_id": entry["tenant_id"],
            "question": entry["question"],
            "answer": entry["answer"],
            "seed_source": "simulator_prewarm",
            "run_id": RUN_ID,
            "seeded_at": seeded_at,
            "vector": pack_vector(vector),
        })

    print(json.dumps({
        "event": "simulator_cache_seed_complete",
        "run_id": RUN_ID,
        "exact_cache_seeds": len(exact),
        "semantic_cache_seeds": len(semantic),
    }))
'''


def build_session(args: argparse.Namespace) -> boto3.Session:
    kwargs = {"region_name": args.region}
    profile = args.aws_profile or args.profile
    if profile:
        kwargs["profile_name"] = profile
    return boto3.Session(**kwargs)


def upload_artifact(s3_client: Any, bucket: str, key: str, body: bytes, content_type: str) -> str:
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=3600,
    )


def run_seed_task(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_prewarm_config(Path(args.config))
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = args.run_id or manifest.get("run_id")
    if not run_id:
        raise ValueError("--run-id or manifest.run_id is required")
    session = build_session(args)
    s3 = session.client("s3")
    ecs = session.client("ecs")
    bucket, prefix = s3_prefix_parts(args.s3_output_prefix or cfg.s3_output_prefix, run_id)
    artifact_prefix = f"{prefix}artifacts/"
    manifest_url = upload_artifact(
        s3,
        bucket,
        f"{artifact_prefix}cache_prewarm_manifest.json",
        json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        "application/json",
    )
    code_url = upload_artifact(
        s3,
        bucket,
        f"{artifact_prefix}ecs_{args.mode}_cache.py",
        SEEDER_CODE.encode("utf-8"),
        "text/x-python",
    )
    command = [
        "python",
        "-c",
        f"import urllib.request; exec(urllib.request.urlopen({code_url!r}, timeout=60).read().decode('utf-8'))",
    ]
    env = [
        {"name": "RUN_ID", "value": run_id},
        {"name": "MANIFEST_URL", "value": manifest_url},
        {"name": "MODE", "value": args.mode},
        {"name": "CACHE_TABLE", "value": args.exact_cache_table or cfg.exact_cache_table},
    ]
    response = ecs.run_task(
        cluster=args.cluster,
        taskDefinition=args.task_definition,
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": [item.strip() for item in args.subnet_ids.split(",") if item.strip()],
                "securityGroups": [args.security_group_id],
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": args.container,
                    "command": command,
                    "environment": env,
                }
            ]
        },
    )
    failures = response.get("failures", [])
    if failures:
        raise RuntimeError(f"ECS run-task failed: {failures}")
    task_arn = response["tasks"][0]["taskArn"]
    waiter = ecs.get_waiter("tasks_stopped")
    waiter.wait(cluster=args.cluster, tasks=[task_arn], WaiterConfig={"Delay": 10, "MaxAttempts": 60})
    described = ecs.describe_tasks(cluster=args.cluster, tasks=[task_arn])
    task = described["tasks"][0]
    containers = task.get("containers", [])
    exit_codes = [container.get("exitCode") for container in containers]
    report = {
        "run_id": run_id,
        "task_arn": task_arn,
        "last_status": task.get("lastStatus"),
        "stopped_reason": task.get("stoppedReason", ""),
        "container_exit_codes": exit_codes,
        "manifest_s3_uri": f"s3://{bucket}/{artifact_prefix}cache_prewarm_manifest.json",
        "code_s3_uri": f"s3://{bucket}/{artifact_prefix}ecs_{args.mode}_cache.py",
        "mode": args.mode,
    }
    output_dir = Path(args.reports_root).resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"ecs_cache_{args.mode}_task.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if any(code not in (0, None) for code in exit_codes):
        raise RuntimeError(f"cache {args.mode} task exited non-zero: {exit_codes}")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed or reset simulator cache from a manifest using a one-off ECS task.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--mode", choices=["seed", "reset"], default="seed")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--s3-output-prefix", default="")
    parser.add_argument("--exact-cache-table", default="")
    parser.add_argument("--cluster", default="ecs-linkme-ai-poc-cluster")
    parser.add_argument("--task-definition", default="task-poc-cache-service")
    parser.add_argument("--container", default="cache-service")
    parser.add_argument("--subnet-ids", required=True)
    parser.add_argument("--security-group-id", required=True)
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--region", default=runtime_config.AWS_REGION)
    parser.add_argument("--profile", default="", help="Alias for --aws-profile")
    parser.add_argument("--aws-profile", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_arg_parser().parse_args(argv)
    try:
        run_seed_task(args)
    except Exception as exc:
        logger.error("Simulator ECS cache seed failed: %s", exc, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
