"""Export M1 boundary schemas for producer/consumer review."""

from __future__ import annotations

import json
from pathlib import Path

from datamate.catalog.models import (
    ColumnInfo,
    EntityCandidate,
    JoinEdge,
    SemanticAnnotations,
    TableInfo,
    ViewSpec,
)
from datamate.catalog.models import IngestionCatalog as BusinessCatalog
from datamate.contracts import CONTRACTS_VERSION


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "src/datamate/catalog/schemas"
    output.mkdir(parents=True, exist_ok=True)
    for model in (
        BusinessCatalog,
        ColumnInfo,
        TableInfo,
        JoinEdge,
        EntityCandidate,
        ViewSpec,
        SemanticAnnotations,
    ):
        (output / (model.__name__ + ".json")).write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    (output / "version.json").write_text(
        json.dumps({"schema_family": "datamate.ingestion.audit.v1", "shared_contracts_version": CONTRACTS_VERSION}) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
