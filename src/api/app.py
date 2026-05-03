"""LinkMe POC REST API -- slim profile + document CRUD + submit/poll.

The UI talks to this Lambda via the Function URL. For the simulator
(S3 -> SQS -> ECS pipeline) the API is not on the hot path; it is used
only by the UI (Live Test tab) and the profile-load script.

Endpoints:
  GET    /leads                                    List profiles
  POST   /leads                                    Create a lead (CreatorProfile)
  GET    /leads/{lead_id}                          Get lead profile
  PUT    /leads/{lead_id}                          Update lead profile
  DELETE /leads/{lead_id}                          Delete lead + associated S3 docs
  GET    /leads/{lead_id}/documents                List documents
  POST   /leads/{lead_id}/documents                Upload a document (text/url)
  DELETE /leads/{lead_id}/documents/{doc}          Delete a document
  POST   /leads/{lead_id}/upload-raw               Raw binary upload (base64 JSON)
  POST   /leads/{lead_id}/questions                Submit one question (-> SQS incoming)
  GET    /leads/{lead_id}/questions/{message_id}   Poll one answer (DDB results, fallback messages)

The handler runs as an AWS Lambda behind a Function URL, or locally via
`python -m api.app 8000`.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import boto3

from common import config
from common.logging_config import setup_logging
from common.schema import CreatorProfile

setup_logging()
logger = logging.getLogger(__name__)

_ddb = None
_s3 = None
_sqs = None
_bedrock_agent = None


def _get_ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return _ddb


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=config.AWS_REGION)
    return _s3


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=config.AWS_REGION)
    return _sqs


def _get_bedrock_agent():
    global _bedrock_agent
    if _bedrock_agent is None:
        _bedrock_agent = boto3.client("bedrock-agent", region_name=config.AWS_REGION)
    return _bedrock_agent


# Populated at runtime via env (terraform-output-driven)
S3_BUCKET = config.KB_SOURCE_BUCKET
RAW_BUCKET = config.RAW_UPLOADS_BUCKET
KB_ID = config.BEDROCK_KB_ID
KB_DS_ID = getattr(config, "BEDROCK_KB_DS_ID", "")
INCOMING_QUEUE_URL = config.INCOMING_QUEUE_URL
RESULTS_TABLE = config.RESULTS_TABLE
MESSAGES_TABLE = config.MESSAGES_TABLE


def _trigger_kb_reingestion() -> str | None:
    if not KB_ID or not KB_DS_ID:
        logger.info("KB re-ingestion skipped — KB_ID/KB_DS_ID not configured")
        return None
    try:
        resp = _get_bedrock_agent().start_ingestion_job(
            knowledgeBaseId=KB_ID,
            dataSourceId=KB_DS_ID,
        )
        job_id = resp.get("ingestionJob", {}).get("ingestionJobId", "unknown")
        logger.info("KB re-ingestion triggered: job=%s", job_id)
        return job_id
    except Exception:
        logger.exception("Failed to trigger KB re-ingestion")
        return None


def _resp(status: int, body: Any) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


# ---- Leads ----

def list_leads() -> dict:
    table = _get_ddb().Table(config.PROFILES_TABLE)
    resp = table.scan(Limit=1000)
    leads = []
    for item in resp.get("Items", []):
        tid = item.get("tenant_id", "")
        if tid.startswith("_system"):
            continue
        profile_data = item.get("profile", "{}")
        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
            except json.JSONDecodeError:
                profile_data = {}
        leads.append(
            {
                "lead_id": tid,
                "name": profile_data.get("creator", {}).get("creator_name", tid),
            }
        )
    return _resp(200, {"leads": leads})


def create_lead(body: dict) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    body.setdefault("created_at", now)
    body.setdefault("updated_at", now)
    try:
        profile = CreatorProfile(**body)
    except Exception as e:
        return _resp(400, {"error": f"Invalid profile: {e}"})

    table = _get_ddb().Table(config.PROFILES_TABLE)
    table.put_item(
        Item={
            "tenant_id": profile.creator.creator_id,
            "profile": profile.model_dump_json(),
        }
    )
    return _resp(
        201,
        {"lead_id": profile.creator.creator_id, "profile": profile.model_dump()},
    )


def get_lead(lead_id: str) -> dict:
    table = _get_ddb().Table(config.PROFILES_TABLE)
    item = table.get_item(Key={"tenant_id": lead_id}).get("Item")
    if not item:
        return _resp(404, {"error": f"Lead {lead_id} not found"})
    profile_data = item.get("profile", "{}")
    if isinstance(profile_data, str):
        profile_data = json.loads(profile_data)
    return _resp(200, {"lead_id": lead_id, "profile": profile_data})


def update_lead(lead_id: str, body: dict) -> dict:
    body.setdefault("updated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        profile = CreatorProfile(**body)
    except Exception as e:
        return _resp(400, {"error": f"Invalid profile: {e}"})
    if profile.creator.creator_id != lead_id:
        return _resp(400, {"error": "creator_id in body must match URL"})

    table = _get_ddb().Table(config.PROFILES_TABLE)
    table.put_item(
        Item={
            "tenant_id": lead_id,
            "profile": profile.model_dump_json(),
        }
    )
    return _resp(200, {"lead_id": lead_id, "profile": profile.model_dump()})


def delete_lead(lead_id: str) -> dict:
    table = _get_ddb().Table(config.PROFILES_TABLE)
    table.delete_item(Key={"tenant_id": lead_id})
    if S3_BUCKET:
        s3 = _get_s3()
        prefix = f"{lead_id}/"
        resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        for obj in resp.get("Contents", []):
            s3.delete_object(Bucket=S3_BUCKET, Key=obj["Key"])
    return _resp(200, {"deleted": lead_id})


# ---- Documents ----

def _track_document(
    lead_id: str, doc_id: str, name: str, source_type: str, url: str = ""
) -> None:
    doc_record: dict[str, str] = {"doc_id": doc_id, "name": name, "type": source_type}
    if source_type == "url" and url:
        doc_record["source"] = url
    table = _get_ddb().Table(config.PROFILES_TABLE)
    try:
        table.update_item(
            Key={"tenant_id": lead_id},
            UpdateExpression=(
                "SET #profile.#kb.#docs = "
                "list_append(if_not_exists(#profile.#kb.#docs, :empty), :doc)"
            ),
            ExpressionAttributeNames={
                "#profile": "profile",
                "#kb": "knowledge_base",
                "#docs": "documents",
            },
            ExpressionAttributeValues={
                ":doc": [doc_record],
                ":empty": [],
            },
        )
    except Exception:
        logger.warning(
            "Could not track document %s in profile for %s", doc_id, lead_id
        )


def _untrack_document(lead_id: str, doc_name: str) -> None:
    table = _get_ddb().Table(config.PROFILES_TABLE)
    try:
        item = table.get_item(Key={"tenant_id": lead_id}).get("Item")
        if not item:
            return
        profile_data = item.get("profile", "{}")
        if isinstance(profile_data, str):
            profile_data = json.loads(profile_data)
        docs = profile_data.get("knowledge_base", {}).get("documents", [])
        updated = [d for d in docs if d.get("name") != doc_name]
        if len(updated) != len(docs):
            profile_data["knowledge_base"]["documents"] = updated
            profile_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            table.update_item(
                Key={"tenant_id": lead_id},
                UpdateExpression="SET #profile = :p",
                ExpressionAttributeNames={"#profile": "profile"},
                ExpressionAttributeValues={
                    ":p": json.dumps(profile_data)
                    if isinstance(item.get("profile"), str)
                    else profile_data
                },
            )
    except Exception:
        logger.warning(
            "Could not untrack document %s from profile for %s", doc_name, lead_id
        )


def upload_document(lead_id: str, body: dict) -> dict:
    doc_name = body.get("name", "")
    content = body.get("content", "")
    source_type = body.get("source_type", "text")
    url = body.get("url", "")
    content_type = body.get("content_type", "text/plain")
    if not doc_name:
        return _resp(400, {"error": "name required"})
    if source_type == "url" and not url:
        return _resp(400, {"error": "url required for url source_type"})
    if source_type != "url" and not content:
        return _resp(400, {"error": "content required"})

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    key = f"{lead_id}/{doc_name}"
    if source_type != "url":
        if not S3_BUCKET:
            return _resp(500, {"error": "KB_SOURCE_BUCKET not configured"})
        _get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
            Metadata={
                "tenant_id": lead_id,
                "doc_id": doc_id,
                "source_type": source_type,
            },
        )

    _track_document(lead_id, doc_id, doc_name, source_type, url)
    job_id = _trigger_kb_reingestion()
    return _resp(
        201,
        {"doc_id": doc_id, "key": key, "bucket": S3_BUCKET, "ingestion_job": job_id},
    )


def list_documents(lead_id: str) -> dict:
    if not S3_BUCKET:
        return _resp(200, {"lead_id": lead_id, "documents": []})
    resp = _get_s3().list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{lead_id}/")
    docs = [
        {"key": obj["Key"], "size": obj["Size"], "modified": str(obj["LastModified"])}
        for obj in resp.get("Contents", [])
    ]
    return _resp(200, {"lead_id": lead_id, "documents": docs})


def delete_document(lead_id: str, doc_key: str) -> dict:
    full_key = f"{lead_id}/{doc_key}" if not doc_key.startswith(lead_id) else doc_key
    doc_name = full_key.split("/", 1)[-1] if "/" in full_key else doc_key
    if S3_BUCKET:
        _get_s3().delete_object(Bucket=S3_BUCKET, Key=full_key)
    _untrack_document(lead_id, doc_name)
    job_id = _trigger_kb_reingestion()
    return _resp(200, {"deleted": full_key, "ingestion_job": job_id})


# ---- Raw File Upload (binary via base64) ----

def upload_raw_file(lead_id: str, body: dict) -> dict:
    import base64 as b64mod

    filename = body.get("filename", body.get("name", ""))
    content_b64 = body.get("content_base64", "")
    source_type = body.get("source_type", "text")
    if not filename or not content_b64:
        return _resp(400, {"error": "filename and content_base64 required"})
    if not RAW_BUCKET:
        return _resp(500, {"error": "RAW_UPLOADS_BUCKET not configured"})

    try:
        raw_bytes = b64mod.b64decode(content_b64)
    except Exception:
        return _resp(400, {"error": "Invalid base64 content"})

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    raw_key = f"{lead_id}/{doc_id}/{filename}"
    _get_s3().put_object(
        Bucket=RAW_BUCKET,
        Key=raw_key,
        Body=raw_bytes,
        Metadata={
            "tenant_id": lead_id,
            "doc_id": doc_id,
            "source_type": source_type,
        },
    )
    _track_document(lead_id, doc_id, filename, source_type)
    return _resp(
        201,
        {"doc_id": doc_id, "raw_key": raw_key, "status": "processing"},
    )


# ---- Submit Question (UI Live Test -> SQS incoming) ----

def submit_question(lead_id: str, body: dict) -> dict:
    """POST /leads/{lead_id}/questions

    Builds an IncomingMessage, enqueues to SQS `incoming`, returns a
    202 with the message_id so the caller can poll the answer.
    """
    question_text = body.get("question") or body.get("text") or ""
    if not question_text:
        return _resp(400, {"error": "question (or text) required"})
    if not INCOMING_QUEUE_URL:
        return _resp(500, {"error": "INCOMING_QUEUE_URL not configured"})

    message_id = f"msg_{uuid.uuid4().hex[:16]}"
    correlation_id = body.get("correlation_id") or f"live:{message_id}"
    run_id = body.get("run_id") or body.get("simulation_id") or "live"
    payload = {
        "message_id": message_id,
        "lead_id": lead_id,
        "user_id": body.get("user_id") or "ui-live-test",
        "question_text": question_text,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "tenant_id": lead_id,
        "question": question_text,
        "correlation_id": correlation_id,
        "source": "ui-live-test",
        "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        _get_sqs().send_message(
            QueueUrl=INCOMING_QUEUE_URL,
            MessageBody=json.dumps(payload),
            MessageAttributes={
                "correlation_id": {
                    "DataType": "String",
                    "StringValue": correlation_id,
                },
                "lead_id": {
                    "DataType": "String",
                    "StringValue": lead_id,
                },
            },
        )
    except Exception as e:
        logger.exception("Failed to enqueue question to Incoming SQS")
        return _resp(500, {"error": f"Enqueue failed: {e}"})

    return _resp(
        202,
        {
            "message_id": message_id,
            "correlation_id": correlation_id,
            "status": "queued",
            "poll_url": f"/leads/{lead_id}/questions/{message_id}",
        },
    )


def poll_answer(lead_id: str, message_id: str) -> dict:
    """GET /leads/{lead_id}/questions/{message_id}

    Reads DDB `results` first (new pipeline authoritative store). Falls
    back to the legacy DDB `messages` table during the transition so
    in-flight messages from the old CDK pipeline continue to resolve.
    """
    ddb = _get_ddb()
    # Primary: DDB results (new pipeline)
    try:
        results_table = ddb.Table(RESULTS_TABLE)
        item = results_table.get_item(Key={"message_id": message_id}).get("Item")
        if item:
            return _resp(
                200,
                {
                    "message_id": message_id,
                    "lead_id": item.get("lead_id", lead_id),
                    "question": item.get("question"),
                    "answer": item.get("answer"),
                    "source": item.get("source"),
                    "cache_tier": item.get("cache_tier"),
                    "model_used": item.get("model_used"),
                    "latency_ms": item.get("latency_ms"),
                    "status": "delivered",
                    "store": "results",
                },
            )
    except Exception:
        logger.warning("results table read failed; falling through to messages table", exc_info=True)

    # Fallback: legacy DDB messages (CDK pipeline)
    try:
        legacy_table = ddb.Table(MESSAGES_TABLE)
        legacy = legacy_table.get_item(Key={"message_id": message_id}).get("Item")
        if legacy:
            return _resp(
                200,
                {
                    "message_id": message_id,
                    "lead_id": legacy.get("lead_id", lead_id),
                    "question": legacy.get("question"),
                    "answer": legacy.get("answer"),
                    "source": legacy.get("source"),
                    "cache_tier": legacy.get("cache_tier"),
                    "model_used": legacy.get("model_used"),
                    "status": legacy.get("status", "delivered"),
                    "store": "messages-legacy",
                },
            )
    except Exception:
        logger.warning("legacy messages table read failed", exc_info=True)

    return _resp(202, {"message_id": message_id, "status": "pending"})


# ---- Lambda Handler / Router ----

def handler(event: dict, context: Any = None) -> dict:
    http_ctx = event.get("requestContext", {}).get("http", {})
    method = event.get("httpMethod") or http_ctx.get("method", "GET")
    path = event.get("path") or event.get("rawPath", "/")
    body: dict = {}
    raw_body = event.get("body", "")
    if raw_body:
        if event.get("isBase64Encoded"):
            import base64
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return _resp(400, {"error": "Invalid JSON"})

    parts = [p for p in path.strip("/").split("/") if p]

    if not parts or parts == [""]:
        return _resp(200, {"service": "LinkMe POC API", "status": "ok"})

    if parts == ["leads"] and method == "GET":
        return list_leads()

    if parts == ["leads"] and method == "POST":
        return create_lead(body)

    if len(parts) == 2 and parts[0] == "leads":
        lead_id = parts[1]
        if method == "GET":
            return get_lead(lead_id)
        if method == "PUT":
            return update_lead(lead_id, body)
        if method == "DELETE":
            return delete_lead(lead_id)

    if len(parts) == 3 and parts[0] == "leads" and parts[2] == "upload-raw" and method == "POST":
        return upload_raw_file(parts[1], body)

    if len(parts) == 3 and parts[0] == "leads" and parts[2] == "documents":
        lead_id = parts[1]
        if method == "POST":
            return upload_document(lead_id, body)
        if method == "GET":
            return list_documents(lead_id)

    if len(parts) == 4 and parts[0] == "leads" and parts[2] == "documents":
        return delete_document(parts[1], parts[3])

    if len(parts) == 3 and parts[0] == "leads" and parts[2] == "questions" and method == "POST":
        return submit_question(parts[1], body)

    if len(parts) == 4 and parts[0] == "leads" and parts[2] == "questions" and method == "GET":
        return poll_answer(parts[1], parts[3])

    return _resp(404, {"error": f"Not found: {method} {path}"})


if __name__ == "__main__":
    import sys
    from http.server import BaseHTTPRequestHandler, HTTPServer

    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    class Handler(BaseHTTPRequestHandler):
        def _handle(self, method):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length else ""
            event = {"httpMethod": method, "path": self.path, "body": body}
            result = handler(event)
            self.send_response(result["statusCode"])
            for k, v in result.get("headers", {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(result["body"].encode())

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

    print(f"API server on http://localhost:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
