"""DynamoDB-safe value helpers."""

from __future__ import annotations

from decimal import Decimal


def decimal_from_float(value: float, places: int = 4) -> Decimal:
    """Return a Decimal rounded from a float for boto3 DynamoDB resources."""
    return Decimal(str(round(value, places)))
