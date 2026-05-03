"""CodeCommit -> CodeBuild dispatcher Lambda.

Triggered by EventBridge on CodeCommit referenceUpdated events. Diffs the
push (old commit -> new commit) and starts a CodeBuild project when any
file under its registered source path prefix changed.

Configuration is injected via env vars:
    WATCH_BRANCH      - branch name to watch (typically "main")
    PATH_TO_PROJECT   - JSON object mapping source-path-prefix to
                        CodeBuild project name, e.g.
                        {"src/tei_embedding/": "linkme-ai-poc-poc-tei-embedding-build"}

On a first push to a new branch (no oldCommitId) every registered project
is started so the branch initial state produces a full build set.
"""

from __future__ import annotations

import json
import logging
import os

import boto3

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_codecommit = boto3.client("codecommit")
_codebuild = boto3.client("codebuild")


def handler(event: dict, _context: object) -> dict:
    print(f"event={json.dumps(event)}")
    detail = event.get("detail", {})
    if detail.get("event") != "referenceUpdated":
        result = {"skipped": "not referenceUpdated"}
        print(f"result={json.dumps(result)}")
        return result

    watch_branch = os.environ.get("WATCH_BRANCH", "main")
    if detail.get("referenceName") != watch_branch:
        result = {"skipped": f"branch {detail.get('referenceName')!r} is not {watch_branch!r}"}
        print(f"result={json.dumps(result)}")
        return result

    path_to_project: dict[str, str] = json.loads(os.environ["PATH_TO_PROJECT"])
    if not path_to_project:
        return {"skipped": "no path map configured"}

    repo = detail["repositoryName"]
    after = detail["commitId"]
    before = detail.get("oldCommitId")

    if not before:
        return _trigger(sorted(set(path_to_project.values())), reason="new branch")

    changed_paths = _changed_paths(repo, before, after)

    to_trigger: set[str] = set()
    for path_prefix, project in path_to_project.items():
        if any(p.startswith(path_prefix) for p in changed_paths):
            to_trigger.add(project)

    return _trigger(sorted(to_trigger), changed_paths=sorted(changed_paths))


def _changed_paths(repo: str, before: str, after: str) -> set[str]:
    paths: set[str] = set()
    token: str | None = None
    while True:
        kwargs = {
            "repositoryName": repo,
            "beforeCommitSpecifier": before,
            "afterCommitSpecifier": after,
        }
        if token:
            kwargs["NextToken"] = token
        resp = _codecommit.get_differences(**kwargs)
        for diff in resp.get("differences", []):
            for side in ("beforeBlob", "afterBlob"):
                blob = diff.get(side) or {}
                path = blob.get("path")
                if path:
                    paths.add(path)
        token = resp.get("NextToken") or resp.get("nextToken")
        if not token:
            break
    return paths


def _trigger(projects: list[str], **extra) -> dict:
    started: list[str] = []
    errors: list[dict] = []
    for project in projects:
        try:
            _codebuild.start_build(projectName=project)
            started.append(project)
            log.info("started build: %s", project)
        except Exception as exc:
            errors.append({"project": project, "error": str(exc)})
            log.exception("failed to start build %s", project)
    return {"started": started, "errors": errors, **extra}
