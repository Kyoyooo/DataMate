"""Portable catalog snapshots; relative database paths are resolved at load time."""

from __future__ import annotations

from pathlib import Path

from datamate.catalog.models import IngestionCatalog as BusinessCatalog


def save_catalog(catalog: BusinessCatalog, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Path(catalog.db_path).resolve()
    location = (
        database.relative_to(path.parent.resolve()).as_posix()
        if database.is_relative_to(path.parent.resolve())
        else str(database)
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        catalog.model_copy(update={"db_path": location}).model_dump_json(indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def load_ingestion_catalog(path: Path) -> BusinessCatalog:
    catalog = BusinessCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    database = Path(catalog.db_path)
    if not database.is_absolute():
        database = (path.parent / database).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    return catalog.model_copy(update={"db_path": str(database)})


def load_catalog(path: Path):
    """Return main's BusinessCatalog, projecting away internal diagnostics."""
    from datamate.catalog.build import to_runtime_catalog
    return to_runtime_catalog(load_ingestion_catalog(path))
