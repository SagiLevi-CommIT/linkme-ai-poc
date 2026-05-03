"""Custom CloudWatch metrics helper -- EMF-first, PutMetricData fallback.

Metrics are emitted as **Embedded Metric Format (EMF)** log lines whenever
possible. CloudWatch Logs automatically extracts these into the
namespace from ``METRICS_NAMESPACE`` (default ``Linkme/PoC``) with no ``PutMetricData`` API calls --
that keeps simulator burst cost flat (no per-call charges) and avoids
the PutMetricData throttle limit.

``put_metric`` and ``timed_metric`` remain API-compatible with the
previous boto3-based implementation so existing callers do not need to
change. They delegate to ``emit_emf_metric`` (EMF log line) by default
and fall back to ``PutMetricData`` only if the ``METRICS_MODE`` env var
is explicitly set to ``api``.

``emit_stage_timing(service, stage, duration_ms, ...)`` is the primary
per-stage instrumentation helper used by cache-service, llm-service,
and messages-pusher. It adds ``Service``, ``Stage``, and ``RunId``
dimensions (with optional extras) per the observability contract in
PROJECT.md.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Generator, Iterable

from common import config
from common.correlation import get_correlation_id

logger = logging.getLogger(__name__)


def _metrics_namespace() -> str:
    """CloudWatch EMF namespace (supplier: ``Linkme/PoC``).

    Resolved at **emit** time so subprocesses or late env injection still work.
    Blank ``METRICS_NAMESPACE`` is treated as unset. Legacy doc-only values map to
    ``Linkme/PoC`` so dashboards, log metric filters, and alarms stay aligned.
    """
    raw = os.environ.get("METRICS_NAMESPACE")
    if raw is None or not str(raw).strip():
        return "Linkme/PoC"
    n = str(raw).strip()
    if n in ("LinkMe/POC/Simulator", "Linkme/POC/Simulator", "linkme/poc/simulator"):
        return "Linkme/PoC"
    return n

# "emf" (default): write an Embedded Metric Format log line on stdout.
# "api": call PutMetricData via boto3 (legacy; costs + throttle risk).
METRICS_MODE = os.environ.get("METRICS_MODE", "emf").lower()

_cw_client: Any = None


def _get_client():  # type: ignore[no-untyped-def]
    """Lazy boto3 CloudWatch client for METRICS_MODE=api fallback."""
    global _cw_client
    if _cw_client is None:
        import boto3

        _cw_client = boto3.client("cloudwatch", region_name=config.AWS_REGION)
    return _cw_client


# ============================================================
# Embedded Metric Format (EMF) emission
# ============================================================

def _emf_line(
    metrics: Iterable[dict[str, str]],
    dimension_sets: list[list[str]],
    values: dict[str, float | int | str],
) -> str:
    """Build a single EMF log line.

    Parameters
    ----------
    metrics
        List of ``{"Name": "MyMetric", "Unit": "Milliseconds"}`` entries
        that CloudWatch Logs should extract into metrics.
    dimension_sets
        List of dimension-key tuples. Each tuple is a separate dimension
        combination that will be emitted to CloudWatch. All keys must
        appear in ``values``.
    values
        The actual dimension values (as strings) + metric values (as
        numbers). Keys referenced in ``metrics``/``dimension_sets``
        must be present here.
    """
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": _metrics_namespace(),
                        "Dimensions": dimension_sets,
                        "Metrics": list(metrics),
                    }
                ],
            },
            **values,
        },
        separators=(",", ":"),
    )


def emit_emf_metric(
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> None:
    """Emit a single metric as an EMF log line.

    Safe to call from any thread. Writes to stdout so the CloudWatch
    Logs agent (awslogs driver in ECS / the Lambda runtime) picks the
    line up automatically.
    """
    dims = dimensions or {}
    values: dict[str, Any] = {k: str(v) for k, v in dims.items()}
    values[name] = value

    cid = get_correlation_id()
    if cid and "correlation_id" not in values:
        values["correlation_id"] = cid

    if extra_fields:
        for k, v in extra_fields.items():
            values.setdefault(k, v)

    line = _emf_line(
        metrics=[{"Name": name, "Unit": unit}],
        dimension_sets=[list(dims.keys())] if dims else [[]],
        values=values,
    )
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# ============================================================
# Public helpers
# ============================================================

def put_metric(
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> None:
    """Emit a CloudWatch metric.

    Default mode is EMF (preferred -- no API cost, no quota). Falls back
    to ``PutMetricData`` only when ``METRICS_MODE=api`` is explicitly
    requested (kept for compatibility with legacy Lambdas that have not
    been migrated to structured log emission yet).
    """
    if METRICS_MODE == "api":
        try:
            _get_client().put_metric_data(
                Namespace=_metrics_namespace(),
                MetricData=[
                    {
                        "MetricName": name,
                        "Value": value,
                        "Unit": unit,
                        "Dimensions": [
                            {"Name": k, "Value": v}
                            for k, v in (dimensions or {}).items()
                        ],
                    }
                ],
            )
        except Exception:
            logger.exception("Failed to put CloudWatch metric %s via PutMetricData", name)
        return

    # Default EMF path
    emit_emf_metric(name, value, unit=unit, dimensions=dimensions)


@contextmanager
def timed_metric(
    name: str,
    dimensions: dict[str, str] | None = None,
) -> Generator[None, None, None]:
    """Context manager -- times the with-block and emits Milliseconds."""
    start = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - start) * 1000
    put_metric(name, elapsed_ms, unit="Milliseconds", dimensions=dimensions)


def emit_stage_timing(
    service: str,
    stage: str,
    duration_ms: float,
    run_id: str | None = None,
    outcome: str | None = None,
    cache_tier: str | None = None,
    model: str | None = None,
    extra_dims: dict[str, str] | None = None,
) -> None:
    """Primary per-stage timing helper for the pipeline services.

    Emits a single EMF log line with the ``StageLatencyMs`` metric and
    standard dimensions: ``Service``, ``Stage``, ``RunId``.

    Optional dimensions (passed through when set):
    ``Outcome`` (e.g. success | miss | hit | error),
    ``CacheTier`` (exact | semantic | miss),
    ``Model`` (bedrock model id used by llm-service).

    ``extra_dims`` lets callers add arbitrary small-cardinality
    dimensions (keep cardinality low -- CloudWatch metrics bill per
    unique dimension combination).
    """
    rid = run_id or os.environ.get("RUN_ID", "adhoc")

    dimensions: dict[str, str] = {
        "Service": service,
        "Stage": stage,
        "RunId": rid,
    }
    if outcome is not None:
        dimensions["Outcome"] = outcome
    if cache_tier is not None:
        dimensions["CacheTier"] = cache_tier
    if model is not None:
        dimensions["Model"] = model
    if extra_dims:
        dimensions.update(extra_dims)

    emit_emf_metric(
        name="StageLatencyMs",
        value=float(duration_ms),
        unit="Milliseconds",
        dimensions=dimensions,
    )


@contextmanager
def stage_timer(
    service: str,
    stage: str,
    run_id: str | None = None,
    outcome: str | None = None,
    cache_tier: str | None = None,
    model: str | None = None,
    extra_dims: dict[str, str] | None = None,
) -> Generator[None, None, None]:
    """Context manager version of ``emit_stage_timing``.

    Usage::

        with stage_timer("cache-service", "semantic_search"):
            do_the_thing()
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        emit_stage_timing(
            service=service,
            stage=stage,
            duration_ms=elapsed_ms,
            run_id=run_id,
            outcome=outcome,
            cache_tier=cache_tier,
            model=model,
            extra_dims=extra_dims,
        )


def emit_counter(
    name: str,
    service: str,
    run_id: str | None = None,
    extra_dims: dict[str, str] | None = None,
    value: float = 1.0,
) -> None:
    """Emit a simple counter metric (e.g. MessagesProcessed, CacheMiss).

    Dimensions: Service + RunId + any extra_dims provided.
    """
    rid = run_id or os.environ.get("RUN_ID", "adhoc")
    dimensions = {"Service": service, "RunId": rid}
    if extra_dims:
        dimensions.update(extra_dims)

    emit_emf_metric(name=name, value=value, unit="Count", dimensions=dimensions)
