"""Offline bulk ingestion for prepared creator profiles.

This module intentionally reuses Component 1 conventions:
- DynamoDB profile rows are keyed by ``tenant_id == creator.creator_id``.
- Profile JSON is validated with ``common.schema.CreatorProfile``.
- KB source documents are written under ``{tenant_id}/`` in the shared
  ``KB_SOURCE_BUCKET`` with tenant metadata for Bedrock KB filters.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

import boto3

from common import config
from common.schema import CreatorProfile

logger = logging.getLogger(__name__)

DEFAULT_REPORT = "bulk_ingest_creators_report.json"
USER_AGENT = "LinkMeBulkIngest/1.0 (+https://linkme.ai)"
REPO_ROOT = Path(__file__).resolve().parents[2]
KB_SETUP_CONFIG = REPO_ROOT / "config" / "bedrock_kb_creators.json"


@dataclass(frozen=True)
class CreatorFolder:
    path: Path
    kind: str
    json_count: int


@dataclass(frozen=True)
class PreparedDocument:
    doc_id: str
    name: str
    source_type: str
    source: str
    s3_key: str


@dataclass(frozen=True)
class PreparedCreator:
    path: Path
    folder: str
    source_kind: str
    input_creator_id: str
    tenant_id: str
    lead_id: str
    profile: CreatorProfile
    documents: list[PreparedDocument]


@dataclass
class BulkIngestStats:
    total_files_found: int = 0
    total_processed: int = 0
    profiles_created: int = 0
    profiles_updated: int = 0
    kb_documents_uploaded: int = 0
    ingestion_jobs_started: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_files_found": self.total_files_found,
            "total_processed": self.total_processed,
            "profiles_created": self.profiles_created,
            "profiles_updated": self.profiles_updated,
            "kb_documents_uploaded": self.kb_documents_uploaded,
            "ingestion_jobs_started": self.ingestion_jobs_started,
            "skipped": self.skipped,
            "failed": self.failed,
            "failures": self.failures,
        }


class BulkIngestError(RuntimeError):
    """Raised when one creator cannot be normalized or ingested."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return clean_text(" ".join(self.parts))


class AwsBulkIngestClient:
    """Small AWS adapter so tests can provide fakes."""

    def __init__(
        self,
        *,
        region: str,
        aws_profile: str = "",
        profiles_table: str = config.PROFILES_TABLE,
        kb_source_bucket: str = config.KB_SOURCE_BUCKET,
    ) -> None:
        session_kwargs = {"region_name": region}
        if aws_profile:
            session_kwargs["profile_name"] = aws_profile
        session = boto3.Session(**session_kwargs)
        self._ddb = session.resource("dynamodb")
        self._s3 = session.client("s3")
        self._bedrock_agent = session.client("bedrock-agent")
        self.profiles_table_name = profiles_table
        self.kb_source_bucket = kb_source_bucket

    def profile_exists(self, tenant_id: str) -> bool:
        table = self._ddb.Table(self.profiles_table_name)
        return "Item" in table.get_item(Key={"tenant_id": tenant_id})

    def put_profile(self, tenant_id: str, profile: CreatorProfile) -> None:
        table = self._ddb.Table(self.profiles_table_name)
        table.put_item(
            Item={"tenant_id": tenant_id, "profile": profile.model_dump_json()}
        )

    def object_exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.kb_source_bucket, Key=key)
            return True
        except Exception:
            return False

    def put_document(
        self,
        *,
        key: str,
        text: str,
        metadata: dict[str, str],
        force: bool,
    ) -> bool:
        if not force and self.object_exists(key):
            return False
        self._s3.put_object(
            Bucket=self.kb_source_bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            Metadata=bedrock_filter_metadata(metadata),
        )
        self.put_metadata_sidecar(key=key, metadata=metadata)
        return True

    def replace_object_metadata(self, *, key: str, metadata: dict[str, str]) -> None:
        self._s3.copy_object(
            Bucket=self.kb_source_bucket,
            Key=key,
            CopySource={"Bucket": self.kb_source_bucket, "Key": key},
            Metadata=bedrock_filter_metadata(metadata),
            MetadataDirective="REPLACE",
            ContentType="text/plain; charset=utf-8",
        )

    def put_metadata_sidecar(self, *, key: str, metadata: dict[str, str]) -> None:
        self._s3.put_object(
            Bucket=self.kb_source_bucket,
            Key=f"{key}.metadata.json",
            Body=json.dumps(
                {"metadataAttributes": bedrock_kb_metadata(metadata)},
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
            ContentType="application/json",
        )

    def start_ingestion_job(self, kb_id: str, data_source_id: str) -> str:
        resp = self._bedrock_agent.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=data_source_id,
        )
        return resp.get("ingestionJob", {}).get("ingestionJobId", "unknown")


def discover_creator_folders(
    creators_root: Path, only_folder: str | None = None
) -> list[CreatorFolder]:
    if not creators_root.exists():
        raise FileNotFoundError(f"creators root not found: {creators_root}")

    folders: list[CreatorFolder] = []
    for folder in sorted(p for p in creators_root.iterdir() if p.is_dir()):
        if only_folder and folder.name != only_folder:
            continue
        files = list(folder.glob("*.json"))
        if not files:
            continue
        folders.append(CreatorFolder(folder, infer_folder_kind(files[:5]), len(files)))
    return folders


def infer_folder_kind(sample_files: list[Path]) -> str:
    kinds = set()
    for path in sample_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            doc = first_document(data)
            if doc.get("type") == "url":
                kinds.add("wiki_link")
            elif doc.get("type") == "text":
                kinds.add("text_content")
            else:
                kinds.add("unknown")
        except Exception:
            kinds.add("unknown")
    if len(kinds) == 1:
        return kinds.pop()
    if "wiki_link" in kinds and "text_content" in kinds:
        return "mixed"
    return "unknown"


def iter_creator_files(folders: list[CreatorFolder], limit: int | None = None) -> list[Path]:
    files: list[Path] = []
    for folder in folders:
        for path in sorted(folder.path.glob("*.json")):
            files.append(path)
            if limit is not None and len(files) >= limit:
                return files
    return files


def load_creator_file(
    path: Path, kb_id: str, kb_source_prefix: str = ""
) -> PreparedCreator:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return normalize_creator(
        raw,
        path=path,
        kb_id=kb_id,
        kb_source_prefix=kb_source_prefix,
    )


def normalize_creator(
    raw: dict[str, Any],
    *,
    path: Path,
    kb_id: str,
    kb_source_prefix: str = "",
) -> PreparedCreator:
    data = json.loads(json.dumps(raw))
    creator_data = data.setdefault("creator", {})
    input_creator_id = creator_data.get("creator_id", "")
    creator_data["creator_id"] = normalize_creator_id(
        input_creator_id,
        creator_data.get("creator_name", ""),
        path,
    )

    if not isinstance(data.get("knowledge_base"), dict):
        raise BulkIngestError("knowledge_base object is required")
    documents = data["knowledge_base"].get("documents") or []
    if not documents:
        raise BulkIngestError("at least one knowledge_base document is required")

    data["knowledge_base"]["kb_id"] = data["knowledge_base"].get("kb_id") or kb_id
    data["knowledge_base"]["documents"] = [
        normalize_document_for_profile(doc) for doc in documents
    ]

    now = datetime.now(timezone.utc).isoformat()
    data.setdefault("created_at", now)
    data.setdefault("updated_at", now)

    try:
        profile = CreatorProfile(**data)
    except Exception as exc:
        raise BulkIngestError(f"profile validation failed: {exc}") from exc

    prepared_docs = [
        prepare_document(profile.creator.creator_id, doc, kb_source_prefix)
        for doc in documents
    ]
    source_kinds = {doc.source_type for doc in prepared_docs}
    source_kind = "wiki_link" if "url" in source_kinds else "text_content"
    return PreparedCreator(
        path=path,
        folder=path.parent.name,
        source_kind=source_kind,
        input_creator_id=input_creator_id,
        tenant_id=profile.creator.creator_id,
        lead_id=profile.creator.creator_id,
        profile=profile,
        documents=prepared_docs,
    )


def normalize_creator_id(raw_id: str, creator_name: str, path: Path) -> str:
    """Return a stable CreatorProfile-compatible ID.

    Valid source IDs are preserved exactly. Invalid source IDs are made ASCII,
    lower-case, and underscore-delimited. This keeps tenant IDs deterministic
    without weakening the canonical schema.
    """
    if re.fullmatch(r"creator_[a-z0-9_]+", raw_id or ""):
        return raw_id

    candidate = raw_id or f"creator_{creator_name}" or path.stem
    if candidate.startswith("creator_"):
        candidate = candidate[len("creator_") :]
    candidate = unicodedata.normalize("NFKD", candidate)
    candidate = candidate.encode("ascii", "ignore").decode("ascii")
    candidate = re.sub(r"[^a-zA-Z0-9]+", "_", candidate).lower()
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    if not candidate:
        candidate = slugify(path.stem.replace("creator_", "")) or "unknown"
    return f"creator_{candidate}"


def normalize_document_for_profile(doc: dict[str, Any]) -> dict[str, Any]:
    source_type = doc.get("type", "")
    normalized = {
        "doc_id": doc.get("doc_id") or "doc_001",
        "name": doc.get("name") or doc.get("doc_id") or "Creator Background",
        "type": source_type,
    }
    if source_type == "url" and doc.get("source"):
        normalized["source"] = doc["source"]
    return normalized


def first_document(data: dict[str, Any]) -> dict[str, Any]:
    docs = data.get("knowledge_base", {}).get("documents") or []
    if not docs:
        return {}
    return docs[0]


def prepare_document(
    tenant_id: str, doc: dict[str, Any], kb_source_prefix: str = ""
) -> PreparedDocument:
    source_type = doc.get("type", "")
    source = doc.get("source", "")
    if source_type not in {"url", "text"}:
        raise BulkIngestError(f"unsupported document type: {source_type}")
    if not source:
        raise BulkIngestError(f"document source missing for {doc.get('name', '')}")

    doc_id = doc.get("doc_id") or "doc_001"
    name = doc.get("name") or doc_id
    key = build_s3_key(tenant_id, source_type, doc_id, name, kb_source_prefix)
    return PreparedDocument(doc_id, name, source_type, source, key)


def build_s3_key(
    tenant_id: str,
    source_type: str,
    doc_id: str,
    name: str,
    kb_source_prefix: str = "",
) -> str:
    safe_doc = slugify(doc_id) or "doc"
    safe_name = slugify(name) or "creator-background"
    key = f"{tenant_id}/bulk_ingest/{source_type}/{safe_doc}_{safe_name}.txt"
    prefix = normalize_s3_prefix(kb_source_prefix)
    return f"{prefix}{key}" if prefix else key


def normalize_s3_prefix(prefix: str) -> str:
    cleaned = prefix.strip().lstrip("/")
    if cleaned and not cleaned.endswith("/"):
        cleaned += "/"
    return cleaned


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def clean_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_document_text(doc: PreparedDocument, retries: int = 3) -> tuple[str, str]:
    if doc.source_type == "text":
        return clean_text(doc.source), "prepared_text"
    return fetch_url_text(doc.source, retries=retries)


def build_profile_fallback_text(profile: CreatorProfile, source_url: str, error: str) -> str:
    rules = "\n".join(f"- {rule}" for rule in profile.agent.response_rules)
    return clean_text(
        "\n\n".join(
            [
                f"Creator: {profile.creator.creator_name}",
                f"Creator ID: {profile.creator.creator_id}",
                f"Primary goal: {profile.agent.main_goal}",
                f"Tone preset: {profile.agent.tone.preset}",
                "Response rules:",
                rules or "- No extra response rules supplied.",
                f"Out-of-scope reply: {profile.agent.out_of_scope_reply}",
                (
                    "Source URL could not be fetched during bulk ingestion. "
                    f"URL: {source_url}. Error: {error}"
                ),
            ]
        )
    )


def build_document_metadata(
    creator: PreparedCreator,
    doc: PreparedDocument,
    method: str,
) -> dict[str, str]:
    metadata = {
        "tenant_id": creator.tenant_id,
        "lead_id": creator.lead_id,
        "doc_id": doc.doc_id,
        "source_type": "local_text" if doc.source_type == "text" else "url",
        "extraction_method": method,
    }
    if doc.source_type == "url":
        metadata["source_url"] = doc.source[:1024]
    return metadata


def bedrock_filter_metadata(metadata: dict[str, str]) -> dict[str, str]:
    """Metadata that Bedrock should index as filterable S3 Vectors fields."""
    allowed = ("tenant_id", "lead_id", "doc_id", "source_type", "extraction_method")
    return {key: metadata[key] for key in allowed if key in metadata}


def bedrock_kb_metadata(metadata: dict[str, str]) -> dict[str, str]:
    """Full KB metadata; source_url must be non-filterable in the S3 Vectors index."""
    attrs = bedrock_filter_metadata(metadata)
    if "source_url" in metadata:
        attrs["source_url"] = metadata["source_url"]
    return attrs


def fetch_url_text(url: str, retries: int = 3) -> tuple[str, str]:
    if "wikipedia.org/wiki/" in url:
        text = fetch_wikipedia_extract(url, retries=retries)
        if text:
            return text, "wikipedia_api"
    return fetch_generic_url_text(url, retries=retries), "html_text"


def fetch_wikipedia_extract(url: str, retries: int = 3) -> str:
    parsed = urlparse(url)
    title = parsed.path.split("/wiki/", 1)[-1]
    if not parsed.netloc or not title:
        return ""

    title = unquote(title)
    api_url = (
        f"{parsed.scheme}://{parsed.netloc}/w/api.php"
        "?action=query&prop=extracts&explaintext=1&redirects=1&format=json&titles="
        f"{quote(title)}"
    )
    payload = fetch_bytes(api_url, retries=retries).decode("utf-8", errors="replace")
    data = json.loads(payload)
    pages = data.get("query", {}).get("pages", {})
    extracts = [page.get("extract", "") for page in pages.values()]
    return clean_text("\n\n".join(extract for extract in extracts if extract))


def fetch_generic_url_text(url: str, retries: int = 3) -> str:
    html = fetch_bytes(url, retries=retries).decode("utf-8", errors="replace")
    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(html)
        if extracted:
            return clean_text(extracted)
    except Exception:
        pass
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def fetch_bytes(url: str, retries: int = 3) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=30) as resp:
                return resp.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
    raise BulkIngestError(f"failed to fetch {url}: {last_exc}")


def load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def should_skip_for_resume(path: Path, report: dict[str, Any], force: bool) -> bool:
    if force:
        return False
    entry = report.get("files", {}).get(str(path))
    return bool(entry and entry.get("status") == "success")


def process_creator(
    creator: PreparedCreator,
    *,
    aws_client: AwsBulkIngestClient | None,
    dry_run: bool,
    force: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": str(creator.path),
        "input_creator_id": creator.input_creator_id,
        "tenant_id": creator.tenant_id,
        "lead_id": creator.lead_id,
        "source_kind": creator.source_kind,
        "documents": [],
    }

    if dry_run:
        result["profile_action"] = "dry_run"
        for doc in creator.documents:
            text, method = (
                extract_document_text(doc)
                if doc.source_type == "text"
                else ("", "would_fetch_url")
            )
            result["documents"].append(
                {
                    "s3_key": doc.s3_key,
                    "source_type": doc.source_type,
                    "extraction_method": method,
                    "char_count": len(text),
                    "action": "dry_run",
                }
            )
        return result

    if aws_client is None:
        raise BulkIngestError("aws_client is required when dry_run is false")

    exists = aws_client.profile_exists(creator.tenant_id)
    aws_client.put_profile(creator.tenant_id, creator.profile)
    result["profile_action"] = "updated" if exists else "created"

    for doc in creator.documents:
        if (
            aws_client is not None
            and not force
            and aws_client.object_exists(doc.s3_key)
        ):
            metadata = build_document_metadata(
                creator,
                doc,
                "not_refetched_existing_s3_object",
            )
            aws_client.replace_object_metadata(key=doc.s3_key, metadata=metadata)
            aws_client.put_metadata_sidecar(key=doc.s3_key, metadata=metadata)
            result["documents"].append(
                {
                    "s3_key": doc.s3_key,
                    "source_type": doc.source_type,
                    "extraction_method": "not_refetched_existing_s3_object",
                    "char_count": 0,
                    "action": "already_exists",
                }
            )
            continue

        try:
            text, method = extract_document_text(doc)
        except Exception as exc:
            if doc.source_type != "url":
                raise
            logger.warning(
                "URL fetch failed for %s (%s); using profile fallback",
                creator.tenant_id,
                exc,
            )
            text = build_profile_fallback_text(creator.profile, doc.source, str(exc))
            method = "profile_fallback_after_fetch_error"
        if len(text) < 10:
            if doc.source_type != "url":
                raise BulkIngestError(f"extracted text too short for {doc.name}")
            logger.warning(
                "URL extraction too short for %s (%s); using profile fallback",
                creator.tenant_id,
                doc.source,
            )
            text = build_profile_fallback_text(
                creator.profile,
                doc.source,
                "extracted text was empty or too short",
            )
            method = "profile_fallback_after_short_extract"
        metadata = build_document_metadata(creator, doc, method)

        uploaded = aws_client.put_document(
            key=doc.s3_key,
            text=text,
            metadata=metadata,
            force=force,
        )
        result["documents"].append(
            {
                "s3_key": doc.s3_key,
                "source_type": doc.source_type,
                "extraction_method": method,
                "char_count": len(text),
                "action": "uploaded" if uploaded else "already_exists",
            }
        )
    return result


def run_bulk_ingest(args: argparse.Namespace) -> dict[str, Any]:
    creators_root = Path(args.creators_root)
    report_path = Path(args.output_report or DEFAULT_REPORT)
    folders = discover_creator_folders(creators_root, args.only_folder or args.folder)
    files = iter_creator_files(folders, args.limit)
    existing_report = load_report(report_path) if args.resume else {"files": {}}
    if args.resume and existing_report.get("stats"):
        previous = existing_report["stats"]
        stats = BulkIngestStats(
            total_files_found=sum(folder.json_count for folder in folders),
            total_processed=previous.get("total_processed", 0),
            profiles_created=previous.get("profiles_created", 0),
            profiles_updated=previous.get("profiles_updated", 0),
            kb_documents_uploaded=previous.get("kb_documents_uploaded", 0),
            ingestion_jobs_started=previous.get("ingestion_jobs_started", 0),
            failed=previous.get("failed", 0),
            failures=previous.get("failures", []),
        )
    else:
        stats = BulkIngestStats(total_files_found=sum(folder.json_count for folder in folders))
    kb_setup = load_kb_setup_config()
    kb_id = (
        args.kb_id
        or kb_setup.get("BEDROCK_KB_ID")
        or config.BEDROCK_KB_ID
        or "shared_bedrock_kb"
    )
    kb_ds_id = (
        args.kb_data_source_id
        or kb_setup.get("BEDROCK_KB_DS_ID")
        or config.BEDROCK_KB_DS_ID
    )
    kb_source_bucket = (
        args.kb_source_bucket
        or kb_setup.get("KB_SOURCE_BUCKET")
        or config.KB_SOURCE_BUCKET
    )
    kb_source_prefix = (
        args.kb_source_prefix
        or kb_setup.get("KB_SOURCE_PREFIX")
        or config.KB_SOURCE_PREFIX
    )

    if (
        not args.dry_run
        and not args.skip_kb_sync
        and not (args.kb_id or kb_setup.get("BEDROCK_KB_ID") or config.BEDROCK_KB_ID)
    ):
        raise BulkIngestError("BEDROCK_KB_ID or --kb-id is required for full ingestion")
    if not args.dry_run and not args.skip_kb_sync and not kb_ds_id:
        raise BulkIngestError(
            "BEDROCK_KB_DS_ID or --kb-data-source-id is required unless --skip-kb-sync is set"
        )

    aws_client = None
    thread_local = threading.local()
    if not args.dry_run:
        aws_client = AwsBulkIngestClient(
            region=args.region,
            aws_profile=args.aws_profile or args.profile or "",
            profiles_table=args.profiles_table,
            kb_source_bucket=kb_source_bucket,
        )

    def client_for_thread() -> AwsBulkIngestClient | None:
        if args.dry_run:
            return None
        if args.workers <= 1:
            return aws_client
        client = getattr(thread_local, "aws_client", None)
        if client is None:
            client = AwsBulkIngestClient(
                region=args.region,
                aws_profile=args.aws_profile or args.profile or "",
                profiles_table=args.profiles_table,
                kb_source_bucket=kb_source_bucket,
            )
            thread_local.aws_client = client
        return client

    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "creators_root": str(creators_root),
        "folders": [
            {
                "path": str(folder.path),
                "kind": folder.kind,
                "json_count": folder.json_count,
            }
            for folder in folders
        ],
        "files": existing_report.get("files", {}),
        "stats": {},
    }

    uploaded_any = False

    def handle_success(path: Path, result: dict[str, Any]) -> None:
        nonlocal uploaded_any
        prior = report["files"].get(str(path), {})
        if prior.get("status") == "failed" and stats.failed > 0:
            stats.failed -= 1
            stats.failures = [
                failure
                for failure in stats.failures
                if failure.get("file") != str(path)
            ]
        stats.total_processed += 1
        if result.get("profile_action") == "created":
            stats.profiles_created += 1
        elif result.get("profile_action") == "updated":
            stats.profiles_updated += 1
        uploaded = sum(
            1 for doc in result["documents"] if doc["action"] == "uploaded"
        )
        stats.kb_documents_uploaded += uploaded
        uploaded_any = uploaded_any or uploaded > 0
        result["status"] = "success"
        report["files"][str(path)] = result

    def handle_failure(path: Path, exc: Exception) -> None:
        stats.failed += 1
        error = {"file": str(path), "error": str(exc)}
        stats.failures.append(error)
        report["files"][str(path)] = {"status": "failed", **error}
        logger.exception("Failed to process %s", path)

    def process_path(path: Path) -> tuple[Path, dict[str, Any]]:
        creator = load_creator_file(
            path,
            kb_id=kb_id,
            kb_source_prefix=kb_source_prefix,
        )
        result = process_creator(
            creator,
            aws_client=client_for_thread(),
            dry_run=args.dry_run,
            force=args.force,
        )
        return path, result

    pending: list[Path] = []
    for path in files:
        if should_skip_for_resume(path, report, args.force):
            stats.skipped += 1
            continue
        pending.append(path)

    if args.workers <= 1 or len(pending) <= 1:
        for index, path in enumerate(pending, start=1):
            try:
                _, result = process_path(path)
                handle_success(path, result)
            except Exception as exc:
                handle_failure(path, exc)

            if index % args.progress_every == 0:
                logger.info("Processed %d/%d pending files", index, len(pending))
            if args.resume:
                report["stats"] = stats.as_dict()
                write_report(report_path, report)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_path = {executor.submit(process_path, path): path for path in pending}
            for index, future in enumerate(
                concurrent.futures.as_completed(future_to_path),
                start=1,
            ):
                path = future_to_path[future]
                try:
                    _, result = future.result()
                    handle_success(path, result)
                except Exception as exc:
                    handle_failure(path, exc)
                if index % args.progress_every == 0:
                    logger.info("Processed %d/%d pending files", index, len(pending))
                if args.resume:
                    report["stats"] = stats.as_dict()
                    write_report(report_path, report)

    if not args.dry_run and not args.skip_kb_sync and uploaded_any and aws_client:
        job_id = aws_client.start_ingestion_job(kb_id, kb_ds_id)
        stats.ingestion_jobs_started += 1
        report["ingestion_job_id"] = job_id

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["stats"] = stats.as_dict()
    write_report(report_path, report)
    return report


def load_kb_setup_config() -> dict[str, str]:
    if not KB_SETUP_CONFIG.exists():
        return {}
    try:
        data = json.loads(KB_SETUP_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read KB setup config at %s", KB_SETUP_CONFIG)
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bulk-ingest prepared LinkMe creator JSON files into profiles + KB source."
    )
    parser.add_argument("--creators-root", default="creators")
    parser.add_argument("--profile", default="", help="Alias for --aws-profile")
    parser.add_argument("--aws-profile", default="")
    parser.add_argument("--region", default=config.AWS_REGION)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-folder", default="")
    parser.add_argument("--folder", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output-report", default=DEFAULT_REPORT)
    parser.add_argument("--skip-kb-sync", action="store_true")
    parser.add_argument("--kb-id", default="")
    parser.add_argument(
        "--kb-data-source-id", default=""
    )
    parser.add_argument("--profiles-table", default=config.PROFILES_TABLE)
    parser.add_argument("--kb-source-bucket", default="")
    parser.add_argument("--kb-source-prefix", default="")
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--workers", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        report = run_bulk_ingest(args)
    except Exception as exc:
        logger.error("Bulk ingestion failed: %s", exc)
        return 1

    stats = report["stats"]
    logger.info(
        "Bulk ingestion complete: processed=%s created=%s updated=%s uploaded=%s skipped=%s failed=%s ingestion_jobs=%s",
        stats["total_processed"],
        stats["profiles_created"],
        stats["profiles_updated"],
        stats["kb_documents_uploaded"],
        stats["skipped"],
        stats["failed"],
        stats["ingestion_jobs_started"],
    )
    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
