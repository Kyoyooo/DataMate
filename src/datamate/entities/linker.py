"""Deterministic exact/fuzzy matching over original catalog values (SPEC 7.6)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
from rapidfuzz.fuzz import partial_ratio, token_set_ratio

from datamate.catalog.models import EntityCandidate, Mention
from datamate.catalog.models import IngestionCatalog as BusinessCatalog
from datamate.config import EntityConfig
from datamate.ingest import sql_quote
from datamate.lexicon import fold


@dataclass(frozen=True)
class EntityRecord:
    table: str
    column: str
    value: str
    value_folded: str
    code: str | None = None


@dataclass(frozen=True)
class EntityIndex:
    records: tuple[EntityRecord, ...]

    def query(
        self, mention: Mention | str, config: EntityConfig | None = None
    ) -> list[EntityCandidate]:
        cfg = config or EntityConfig()
        text = mention.text if isinstance(mention, Mention) else mention
        key = fold(text)
        if not key:
            return []
        candidates = []
        scores = {}
        for record in self.records:
            target = record.value_folded
            if target not in scores:
                scores[target] = (
                    100.0
                    if key == target
                    else max(token_set_ratio(key, target), partial_ratio(key, target))
                )
            score = scores[target]
            if score >= cfg.weak_threshold:
                candidates.append(
                    EntityCandidate(
                        mention=text,
                        table=record.table,
                        column=record.column,
                        value=record.value,
                        code=record.code,
                        score=score,
                        strength="strong" if score >= cfg.strong_threshold else "weak",
                    )
                )
        candidates.sort(key=lambda c: (-c.score, c.table, c.column, c.value))
        return candidates[: cfg.top_k]


def build_entity_index(catalog: BusinessCatalog, config: EntityConfig | None = None) -> EntityIndex:
    cfg = config or EntityConfig()
    records = []
    if catalog.status != "ready":
        return EntityIndex(())
    with duckdb.connect(
        catalog.db_path,
        read_only=True,
        config={
            "threads": 1,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    ) as connection:
        for table in catalog.tables:
            codes = [c for c in table.columns if c.semantic_hint == "code"]
            for column in table.columns:
                if column.sql_type != "VARCHAR" or not (
                    column.semantic_hint in {"name", "code", "status"}
                    or column.distinct_count <= cfg.max_distinct_values
                ):
                    continue
                name = sql_quote(column.name)
                expressions = [
                    f"CASE WHEN COUNT(DISTINCT {sql_quote(c.name)})=1 THEN MIN({sql_quote(c.name)})::VARCHAR END"
                    for c in codes
                ]
                projection = "," + ",".join(expressions) if expressions else ""
                cursor = connection.execute(
                    f"SELECT {name}{projection} FROM {sql_quote(table.name)} WHERE {name} IS NOT NULL GROUP BY {name} ORDER BY {name}"
                )
                while chunk := cursor.fetchmany(10000):
                    for value, *possible in chunk:
                        records.append(
                            EntityRecord(
                                table.name,
                                column.name,
                                value,
                                fold(value),
                                next((code for code in possible if code is not None), None),
                            )
                        )
    return EntityIndex(tuple(records))


def save_entity_index(index: EntityIndex, path: Path) -> str:
    payload = [
        {
            "table": r.table,
            "column": r.column,
            "value": r.value,
            "value_folded": r.value_folded,
            "code": r.code,
        }
        for r in index.records
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")
    return hashlib.sha256(encoded.encode()).hexdigest()


def load_entity_index(path: Path) -> EntityIndex:
    return EntityIndex(
        tuple(EntityRecord(**row) for row in json.loads(path.read_text(encoding="utf-8")))
    )
