"""Create a dedicated Bedrock Knowledge Base for bulk creator ingestion."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

DEFAULT_REGION = "us-west-2"
DEFAULT_ACCOUNT_ID = "095128162384"
DEFAULT_KB_NAME = "linkme-ai-poc-creators-kb"
DEFAULT_DATA_SOURCE_NAME = "linkme-ai-poc-creators-kb-s3-source"
DEFAULT_VECTOR_BUCKET_NAME = "linkme-ai-poc-creators-kb-vectors"
DEFAULT_VECTOR_INDEX_NAME = "linkme-ai-poc-creators-kb-index"
DEFAULT_ROLE_NAME = "role-linkme-ai-poc-creators-kb"
DEFAULT_KB_SOURCE_BUCKET = "linkme-poc-kb-source"
DEFAULT_KB_SOURCE_PREFIX = "creators-ingestion/"
DEFAULT_EMBEDDING_MODEL_ARN = (
    "arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0"
)
DEFAULT_VECTOR_DIMENSION = 1024

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "config" / "bedrock_kb_creators.json"
DEFAULT_ENV_OUTPUT = REPO_ROOT / ".env.creator-kb"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or discover the dedicated LinkMe creator-ingestion Bedrock KB."
    )
    parser.add_argument("--profile", "--aws-profile", dest="aws_profile", default="")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--kb-name", default=DEFAULT_KB_NAME)
    parser.add_argument("--data-source-name", default=DEFAULT_DATA_SOURCE_NAME)
    parser.add_argument("--vector-bucket-name", default=DEFAULT_VECTOR_BUCKET_NAME)
    parser.add_argument("--vector-index-name", default=DEFAULT_VECTOR_INDEX_NAME)
    parser.add_argument("--role-name", default=DEFAULT_ROLE_NAME)
    parser.add_argument("--kb-source-bucket", default=DEFAULT_KB_SOURCE_BUCKET)
    parser.add_argument("--kb-source-prefix", default=DEFAULT_KB_SOURCE_PREFIX)
    parser.add_argument("--embedding-model-arn", default=DEFAULT_EMBEDDING_MODEL_ARN)
    parser.add_argument("--vector-dimension", type=int, default=DEFAULT_VECTOR_DIMENSION)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--env-output", default=str(DEFAULT_ENV_OUTPUT))
    return parser


def create_session(region: str, aws_profile: str) -> boto3.Session:
    kwargs: dict[str, str] = {"region_name": region}
    if aws_profile:
        kwargs["profile_name"] = aws_profile
    return boto3.Session(**kwargs)


def ensure_vector_bucket(s3vectors, name: str) -> str:
    try:
        resp = s3vectors.get_vector_bucket(vectorBucketName=name)
        return resp["vectorBucket"]["vectorBucketArn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NotFoundException", "NoSuchBucket"}:
            raise

    logger.info("Creating S3 Vectors bucket %s", name)
    s3vectors.create_vector_bucket(vectorBucketName=name)
    return wait_for_vector_bucket(s3vectors, name)


def wait_for_vector_bucket(s3vectors, name: str) -> str:
    for _ in range(30):
        try:
            resp = s3vectors.get_vector_bucket(vectorBucketName=name)
            return resp["vectorBucket"]["vectorBucketArn"]
        except ClientError:
            time.sleep(2)
    raise RuntimeError(f"S3 Vectors bucket did not become visible: {name}")


def ensure_vector_index(
    s3vectors,
    *,
    vector_bucket_name: str,
    index_name: str,
    dimension: int,
) -> str:
    try:
        resp = s3vectors.get_index(
            vectorBucketName=vector_bucket_name,
            indexName=index_name,
        )
        return resp["index"]["indexArn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NotFoundException", "NoSuchIndex"}:
            raise

    logger.info("Creating S3 Vectors index %s", index_name)
    s3vectors.create_index(
        vectorBucketName=vector_bucket_name,
        indexName=index_name,
        dataType="float32",
        dimension=dimension,
        distanceMetric="cosine",
        metadataConfiguration={
            "nonFilterableMetadataKeys": [
                "AMAZON_BEDROCK_TEXT",
                "AMAZON_BEDROCK_METADATA",
                "source_url",
            ]
        },
    )
    for _ in range(30):
        try:
            resp = s3vectors.get_index(
                vectorBucketName=vector_bucket_name,
                indexName=index_name,
            )
            return resp["index"]["indexArn"]
        except ClientError:
            time.sleep(2)
    raise RuntimeError(f"S3 Vectors index did not become visible: {index_name}")


def ensure_kb_role(
    iam,
    *,
    role_name: str,
    account_id: str,
    region: str,
    source_bucket: str,
    vector_bucket_name: str,
    embedding_model_arn: str,
) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            }
        ],
    }
    try:
        role = iam.get_role(RoleName=role_name)["Role"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        logger.info("Creating IAM role %s", role_name)
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Dedicated Bedrock KB role for LinkMe creator bulk ingestion",
            Tags=[
                {"Key": "Project", "Value": "linkme-ai-poc"},
                {"Key": "Component", "Value": "creator-bulk-ingestion"},
            ],
        )["Role"]
    else:
        iam.update_assume_role_policy(
            RoleName=role_name,
            PolicyDocument=json.dumps(trust),
        )

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{source_bucket}",
                    f"arn:aws:s3:::{source_bucket}/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3vectors:DeleteVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:ListVectors",
                    "s3vectors:PutVectors",
                    "s3vectors:QueryVectors",
                ],
                "Resource": [
                    f"arn:aws:s3vectors:{region}:{account_id}:bucket/{vector_bucket_name}",
                    f"arn:aws:s3vectors:{region}:{account_id}:bucket/{vector_bucket_name}/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": [embedding_model_arn],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="bedrock-kb-creators-ingestion",
        PolicyDocument=json.dumps(policy),
    )
    time.sleep(10)
    return role["Arn"]


def find_knowledge_base(bedrock_agent, name: str) -> dict[str, Any] | None:
    paginator = bedrock_agent.get_paginator("list_knowledge_bases")
    for page in paginator.paginate():
        for summary in page.get("knowledgeBaseSummaries", []):
            if summary.get("name") == name:
                return summary
    return None


def ensure_knowledge_base(
    bedrock_agent,
    *,
    name: str,
    role_arn: str,
    embedding_model_arn: str,
    vector_dimension: int,
    vector_bucket_arn: str,
    vector_index_arn: str,
    vector_index_name: str,
) -> tuple[str, str]:
    existing = find_knowledge_base(bedrock_agent, name)
    if existing:
        kb_id = existing["knowledgeBaseId"]
        status = existing["status"]
        return kb_id, wait_for_kb_status(bedrock_agent, kb_id, status)

    logger.info("Creating Bedrock Knowledge Base %s", name)
    resp = bedrock_agent.create_knowledge_base(
        name=name,
        description="Dedicated LinkMe AI POC creator bulk-ingestion KB",
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": embedding_model_arn,
                "embeddingModelConfiguration": {
                    "bedrockEmbeddingModelConfiguration": {
                        "dimensions": vector_dimension,
                        "embeddingDataType": "FLOAT32",
                    }
                },
            },
        },
        storageConfiguration={
            "type": "S3_VECTORS",
            "s3VectorsConfiguration": {
                "indexArn": vector_index_arn,
            },
        },
        tags={
            "Project": "linkme-ai-poc",
            "Component": "creator-bulk-ingestion",
        },
    )
    kb = resp["knowledgeBase"]
    return kb["knowledgeBaseId"], wait_for_kb_status(
        bedrock_agent,
        kb["knowledgeBaseId"],
        kb["status"],
    )


def wait_for_kb_status(bedrock_agent, kb_id: str, status: str = "") -> str:
    current = status
    for _ in range(90):
        resp = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
        current = resp["knowledgeBase"]["status"]
        if current == "ACTIVE":
            return current
        if current == "FAILED":
            raise RuntimeError(f"Knowledge Base creation failed: {resp['knowledgeBase']}")
        time.sleep(10)
    raise RuntimeError(f"Knowledge Base did not become ACTIVE: {kb_id} ({current})")


def ensure_data_source(
    bedrock_agent,
    *,
    kb_id: str,
    name: str,
    account_id: str,
    source_bucket: str,
    source_prefix: str,
) -> str:
    paginator = bedrock_agent.get_paginator("list_data_sources")
    for page in paginator.paginate(knowledgeBaseId=kb_id):
        for summary in page.get("dataSourceSummaries", []):
            if summary.get("name") == name:
                return summary["dataSourceId"]

    logger.info("Creating Bedrock KB S3 data source %s", name)
    resp = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name=name,
        description="S3 source for LinkMe creator bulk-ingestion documents",
        dataDeletionPolicy="RETAIN",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{source_bucket}",
                "bucketOwnerAccountId": account_id,
                "inclusionPrefixes": [normalize_prefix(source_prefix)],
            },
        },
    )
    return resp["dataSource"]["dataSourceId"]


def normalize_prefix(prefix: str) -> str:
    cleaned = prefix.strip().lstrip("/")
    if cleaned and not cleaned.endswith("/"):
        cleaned += "/"
    return cleaned


def write_outputs(path: Path, env_path: Path, outputs: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(outputs, indent=2, sort_keys=True), encoding="utf-8")
    env_path.write_text(
        "\n".join(
            [
                f"BEDROCK_KB_ID={outputs['BEDROCK_KB_ID']}",
                f"BEDROCK_KB_DS_ID={outputs['BEDROCK_KB_DS_ID']}",
                f"KB_SOURCE_BUCKET={outputs['KB_SOURCE_BUCKET']}",
                f"KB_SOURCE_PREFIX={outputs['KB_SOURCE_PREFIX']}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def setup_kb(args: argparse.Namespace) -> dict[str, Any]:
    session = create_session(args.region, args.aws_profile)
    sts = session.client("sts")
    identity = sts.get_caller_identity()
    account_id = args.account_id or identity["Account"]
    if identity["Account"] != account_id:
        raise RuntimeError(
            f"Active account {identity['Account']} does not match expected {account_id}"
        )

    s3vectors = session.client("s3vectors")
    iam = session.client("iam")
    bedrock_agent = session.client("bedrock-agent")

    vector_bucket_arn = ensure_vector_bucket(s3vectors, args.vector_bucket_name)
    vector_index_arn = ensure_vector_index(
        s3vectors,
        vector_bucket_name=args.vector_bucket_name,
        index_name=args.vector_index_name,
        dimension=args.vector_dimension,
    )
    role_arn = ensure_kb_role(
        iam,
        role_name=args.role_name,
        account_id=account_id,
        region=args.region,
        source_bucket=args.kb_source_bucket,
        vector_bucket_name=args.vector_bucket_name,
        embedding_model_arn=args.embedding_model_arn,
    )
    kb_id, kb_status = ensure_knowledge_base(
        bedrock_agent,
        name=args.kb_name,
        role_arn=role_arn,
        embedding_model_arn=args.embedding_model_arn,
        vector_dimension=args.vector_dimension,
        vector_bucket_arn=vector_bucket_arn,
        vector_index_arn=vector_index_arn,
        vector_index_name=args.vector_index_name,
    )
    ds_id = ensure_data_source(
        bedrock_agent,
        kb_id=kb_id,
        name=args.data_source_name,
        account_id=account_id,
        source_bucket=args.kb_source_bucket,
        source_prefix=args.kb_source_prefix,
    )

    outputs = {
        "BEDROCK_KB_ID": kb_id,
        "BEDROCK_KB_DS_ID": ds_id,
        "KB_SOURCE_BUCKET": args.kb_source_bucket,
        "KB_SOURCE_PREFIX": normalize_prefix(args.kb_source_prefix),
        "knowledge_base_name": args.kb_name,
        "knowledge_base_status": kb_status,
        "data_source_name": args.data_source_name,
        "region": args.region,
        "account_id": account_id,
        "embedding_model_arn": args.embedding_model_arn,
        "vector_dimension": args.vector_dimension,
        "vector_bucket_name": args.vector_bucket_name,
        "vector_bucket_arn": vector_bucket_arn,
        "vector_index_name": args.vector_index_name,
        "vector_index_arn": vector_index_arn,
        "kb_role_name": args.role_name,
        "kb_role_arn": role_arn,
        "created_or_verified_at": datetime.now(timezone.utc).isoformat(),
    }
    write_outputs(Path(args.output), Path(args.env_output), outputs)
    return outputs


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = build_arg_parser().parse_args(argv)
    outputs = setup_kb(args)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
