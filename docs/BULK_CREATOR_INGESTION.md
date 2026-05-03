# Bulk Creator Ingestion

`scripts/bulk_ingest_creators.py` loads prepared local creator JSON files, validates
them against the canonical `CreatorProfile` schema, writes profile rows to
DynamoDB, writes normalized text files to the KB-source S3 bucket, writes
Bedrock metadata sidecars, and can start one Bedrock Knowledge Base ingestion
job at the end of a successful run.

## Dedicated Bedrock KB

Do not use the historical `S0WOFNAVDL` KB. The dedicated creator-ingestion KB
for this project is stored in [`config/bedrock_kb_creators.json`](../config/bedrock_kb_creators.json)
and `.env.creator-kb`.

Current setup:

| Setting | Value |
|---|---|
| Region | `us-west-2` |
| Knowledge Base name | `linkme-ai-poc-creators-kb-v3` |
| `BEDROCK_KB_ID` | `4OCVLZA0SR` |
| Data source name | `linkme-ai-poc-creators-kb-s3-source-v3` |
| `BEDROCK_KB_DS_ID` | `XUUR927HC8` |
| Source bucket/prefix | `s3://linkme-poc-kb-source/creators-ingestion/` |
| Embedding model | `arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0` |
| Vector store | S3 Vectors bucket `linkme-ai-poc-creators-kb-vectors-v3`, index `linkme-ai-poc-creators-kb-index-v3` |
| Vector settings | `float32`, `1024` dimensions, cosine distance |

The S3 Vectors index marks `AMAZON_BEDROCK_TEXT`,
`AMAZON_BEDROCK_METADATA`, and `source_url` as non-filterable metadata. Tenant
filtering uses compact filterable metadata: `tenant_id`, `lead_id`, `doc_id`,
`source_type`, and `extraction_method`.

Create or verify this setup with:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe scripts\setup_bedrock_kb.py `
  --profile corp-ai-sandbox-devops `
  --region us-west-2 `
  --kb-name linkme-ai-poc-creators-kb-v3 `
  --data-source-name linkme-ai-poc-creators-kb-s3-source-v3 `
  --vector-bucket-name linkme-ai-poc-creators-kb-vectors-v3 `
  --vector-index-name linkme-ai-poc-creators-kb-index-v3 `
  --role-name role-linkme-ai-poc-creators-kb-v3
```

## Expected Local Layout

```text
creators/
  output_v2/
    creator_3blue1brown.json
    ...
  israeli_creators profiles/
    creator_barrefaeli01.json
    ...
```

The `output_v2` files are treated as Wikipedia-link creators:

- `knowledge_base.documents[].type == "url"`
- `knowledge_base.documents[].source` is a Wikipedia URL
- The script fetches clean article text through the Wikipedia API when possible.

The `israeli_creators profiles` files are treated as prepared-text creators:

- `knowledge_base.documents[].type == "text"`
- `knowledge_base.documents[].source` contains the text to ingest
- The script writes that text directly to the KB source bucket.

Both folder schemas already match the project profile shape except that the
local files omit `knowledge_base.kb_id`. The script fills it from explicit CLI
args, `config/bedrock_kb_creators.json`, env vars, or the dry-run placeholder
`shared_bedrock_kb`.

Valid `creator.creator_id` values are preserved as-is and become both
`tenant_id` and `lead_id`. If a local file contains characters outside the
canonical `^creator_[a-z0-9_]+$` pattern, the script deterministically normalizes
the ID to ASCII lowercase underscores before validation and records the original
ID in the output report as `input_creator_id`.

## AWS Resources Touched

- DynamoDB profiles table, default `ddb-linkme-poc-profiles`
- S3 KB source bucket/prefix, default from config:
  `s3://linkme-poc-kb-source/creators-ingestion/`
- Bedrock Agent `StartIngestionJob` for the configured Knowledge Base data source

The script does not touch the Phase 2 ECS services, queues, semantic cache,
SageMaker endpoint, or message simulator.

## Required Configuration

For a full run, either use the stored config file or load `.env.creator-kb`:

```powershell
$env:PYTHONPATH = "src"
$env:BEDROCK_KB_ID = "4OCVLZA0SR"
$env:BEDROCK_KB_DS_ID = "XUUR927HC8"
$env:KB_SOURCE_BUCKET = "linkme-poc-kb-source"
$env:KB_SOURCE_PREFIX = "creators-ingestion/"
```

Optional overrides:

- `--profiles-table`
- `--kb-source-bucket`
- `--kb-source-prefix`
- `--kb-id`
- `--kb-data-source-id`
- `--aws-profile`
- `--region`

## Dry Run

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe scripts\bulk_ingest_creators.py `
  --creators-root C:\Git_Repos\linkme-ws\linkme-ai-poc\creators `
  --region us-west-2 `
  --dry-run `
  --limit 25 `
  --output-report .\bulk_ingest_creators_report.dry-run.json
```

Dry-run validates profile normalization and S3 key planning. It does not call
AWS and does not fetch Wikipedia pages.

## Full Run

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe scripts\bulk_ingest_creators.py `
  --creators-root C:\Git_Repos\linkme-ws\linkme-ai-poc\creators `
  --aws-profile corp-ai-sandbox-devops `
  --region us-west-2 `
  --resume `
  --workers 16 `
  --output-report .\bulk_ingest_creators_report.json
```

Use `--skip-kb-sync` when you want to upload profiles and source documents but
trigger Bedrock ingestion manually later. Use `--force` to overwrite existing S3
objects and to reprocess files previously marked successful in a resume report.

## Idempotency

Profile writes use the stable tenant ID from `creator.creator_id`; the same file
updates the same DynamoDB row on repeated runs.

S3 document keys are deterministic:

```text
creators-ingestion/{tenant_id}/bulk_ingest/{source_type}/{doc_id}_{slugged_doc_name}.txt
```

Without `--force`, an existing S3 object is left in place and reported as
`already_exists`. With `--resume`, files marked `success` in the report are
skipped unless `--force` is also supplied.

## Verification

Check profile rows:

```powershell
aws dynamodb get-item `
  --table-name ddb-linkme-poc-profiles `
  --key '{"tenant_id":{"S":"creator_3blue1brown01"}}' `
  --profile commit-ai-sandbox-01 `
  --region us-west-2
```

Check KB source documents:

```powershell
aws s3 ls s3://linkme-poc-kb-source/creators-ingestion/creator_3blue1brown01/bulk_ingest/ `
  --recursive `
  --profile commit-dev `
  --region us-west-2
```

Check Bedrock ingestion:

```powershell
aws bedrock-agent get-ingestion-job `
  --knowledge-base-id 4OCVLZA0SR `
  --data-source-id XUUR927HC8 `
  --ingestion-job-id CKY9F1P6J8 `
  --profile commit-dev `
  --region us-west-2
```

Final ingestion result: `COMPLETE`, `4987` documents scanned, `4987` new
documents indexed, `0` failed. The 4,990 local JSON files collapse to 4,987
unique S3 documents because three source files share deterministic tenant/doc
keys.

Tenant-filtered retrieval example:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -c "import boto3; c=boto3.Session(profile_name='commit-dev',region_name='us-west-2').client('bedrock-agent-runtime'); r=c.retrieve(knowledgeBaseId='4OCVLZA0SR', retrievalQuery={'text':'What is 3Blue1Brown known for?'}, retrievalConfiguration={'vectorSearchConfiguration': {'numberOfResults':3, 'filter': {'equals': {'key':'tenant_id','value':'creator_3blue1brown01'}}}}); print(r['retrievalResults'][0]['metadata']); print(r['retrievalResults'][0]['content']['text'][:300])"
```

Observed result included tenant metadata `creator_3blue1brown01`, source URL
`https://en.wikipedia.org/wiki/3Blue1Brown`, and article text describing
3Blue1Brown as Grant Sanderson's educational visual mathematics YouTube channel.
