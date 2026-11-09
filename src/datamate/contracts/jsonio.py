"""Exact JSON serialization shared by the formatter, writer, and scorer. Owner: Lead.

``json.dumps`` cannot write a Decimal as a number literal without passing it
through float. This serializer writes Decimal values as exact literals and
dates as ISO strings, with ``ensure_ascii=False`` and compact separators.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


def _decimal_literal(d: Decimal) -> str:
    if not d.is_finite():
        raise ValueError(f"non-finite Decimal cannot be serialized: {d}")
    if d == d.to_integral_value():
        return str(int(d))
    return format(d, "f").rstrip("0").rstrip(".")


def dumps(obj: Any) -> str:
    """Serialize to a single-line JSON string (no trailing newline)."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, Decimal):
        return _decimal_literal(obj)
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"non-finite float cannot be serialized: {obj}")
        return repr(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, (datetime, date)):
        return json.dumps(obj.isoformat())
    if isinstance(obj, BaseModel):
        return dumps(obj.model_dump(mode="python"))
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            if not isinstance(k, str):
                raise TypeError(f"JSON object keys must be str, got {type(k).__name__}")
            parts.append(f"{json.dumps(k, ensure_ascii=False)}:{dumps(v)}")
        return "{" + ",".join(parts) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(dumps(v) for v in obj) + "]"
    raise TypeError(f"cannot serialize {type(obj).__name__}")


def loads_exact(text: str) -> Any:
    """Parse JSON keeping non-integral numbers as Decimal (for scorers and tests)."""
    return json.loads(text, parse_float=Decimal)
