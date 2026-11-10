"""Versioned transport-only schema adapter. Application contracts remain authoritative."""

from __future__ import annotations

import copy
from typing import Any

SCHEMA_ADAPTER_VERSION = "timeref-kind-required-oneof-to-anyof.v1"


def schema_for_vllm(original: dict[str, Any]) -> dict[str, Any]:
    """Convert only the tagged TimeRef union, requiring distinct explicit kind values."""
    wire = copy.deepcopy(original)
    definitions = wire.get("$defs", {})
    expr = definitions.get("TimeRef", {}).get("properties", {}).get("expr", {})
    if "oneOf" in expr:
        if expr.get("discriminator", {}).get("propertyName") != "kind":
            raise ValueError("unexpected TimeRef discriminator")
        branches = expr["oneOf"]
        if not isinstance(branches, list) or not branches:
            raise ValueError("TimeRef.expr.oneOf must be non-empty")
        seen: set[str] = set()
        for branch in branches:
            ref = branch.get("$ref", "")
            if set(branch) != {"$ref"} or not ref.startswith("#/$defs/"):
                raise ValueError("unsupported TimeRef branch")
            definition = definitions[ref.removeprefix("#/$defs/")]
            kind = definition.get("properties", {}).get("kind", {})
            tag = kind.get("const")
            if (definition.get("type") != "object" or kind.get("type") != "string"
                    or not isinstance(tag, str) or tag in seen):
                raise ValueError("TimeRef branches need distinct string kind.const values")
            seen.add(tag)
            required = definition.setdefault("required", [])
            if "kind" not in required:
                required.append("kind")
        expr["anyOf"] = expr.pop("oneOf")
        expr.pop("discriminator", None)
    _reject_oneof(wire)
    return wire


def _reject_oneof(node: Any) -> None:
    if not isinstance(node, dict):
        return
    if "oneOf" in node:
        raise ValueError("unsupported oneOf outside the known TimeRef adapter")
    for keyword in ("$defs", "definitions", "properties", "patternProperties", "dependentSchemas"):
        for child in node.get(keyword, {}).values():
            _reject_oneof(child)
    for keyword in ("items", "additionalProperties", "contains", "not", "if", "then", "else",
                    "propertyNames"):
        _reject_oneof(node.get(keyword))
    for keyword in ("anyOf", "allOf", "prefixItems"):
        for child in node.get(keyword, []):
            _reject_oneof(child)
