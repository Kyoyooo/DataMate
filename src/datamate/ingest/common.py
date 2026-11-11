"""Shared filesystem, provenance, text and serialization utilities."""

from __future__ import annotations

import csv
import hashlib
import inspect
import io
import json
import math
import re
import types
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

PREPROCESS_VERSION = "1.0.0"
NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan", "-", "--", "—"}


def nfc_text(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def fold_key(value: Any) -> str:
    text = str(value).replace("đ", "d").replace("Đ", "D")
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)
    ).casefold()


def identifier(value: str) -> str:
    text = value
    result = re.sub(r"[^a-z0-9]+", "_", fold_key(text)).strip("_") or "column"
    return "c_" + result if result[0].isdigit() else result


def unique_names(values: list[str]) -> list[str]:
    used, result = set(), []
    for value in values:
        base, candidate, count = identifier(value), identifier(value), 1
        while candidate in used:
            count += 1
            candidate = f"{base}_{count}"
        used.add(candidate)
        result.append(candidate)
    return result


def sql_quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return isinstance(value, str) and value.strip().casefold() in NULL_TOKENS


def source_text(value: Any) -> str | None:
    if value is None or isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return nfc_text(str(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_text(value: Any, *, pretty: bool = False) -> str:
    """Serialize Decimal as a JSON number without an intermediate float."""

    def encode(item):
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError("Nonfinite JSON decimal")
            return format(item, "f")
        if item is None or isinstance(item, (str, bool, int, float)):
            return json.dumps(item, ensure_ascii=False, allow_nan=False)
        if isinstance(item, (Path, datetime, date, time)):
            return json.dumps(str(item), ensure_ascii=False)
        if isinstance(item, dict):
            return (
                "{"
                + ",".join(encode(str(k)) + ":" + encode(v) for k, v in sorted(item.items()))
                + "}"
            )
        if isinstance(item, (list, tuple)):
            return "[" + ",".join(map(encode, item)) + "]"
        raise TypeError(f"Unsupported JSON type: {type(item).__name__}")

    encoded = encode(value)
    # Pretty printing through json.loads would turn Decimal into binary floats.
    return encoded + ("\n" if pretty else "")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json_text(value, pretty=True), encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json_text(row) + "\n")
    temporary.replace(path)


def separate_output(split_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    source, destination = split_dir.resolve(), output_dir.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Split directory does not exist: {source}")
    if (
        source == destination
        or destination.is_relative_to(source)
        or source.is_relative_to(destination)
    ):
        raise ValueError("Input and output must be separate, non-nested directories")
    return source, destination


def resolve_split(preferred: Path | None = None) -> Path:
    """Use an explicit train/test directory; never guess between multiple splits."""
    if preferred is not None:
        candidate = preferred.resolve()
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"Set SPLIT_DIR to an existing split directory: {preferred}")
    roots = [Path("/data"), Path("/kaggle/input")]
    candidates = {
        p.resolve()
        for root in roots
        if root.is_dir()
        for p in [root, *root.glob("*"), *root.glob("*/*"), *root.glob("*/*/*/*")]
        if p.is_dir() and (p / "questions.jsonl").is_file() and (p / "data").is_dir()
    }
    if len(candidates) != 1:
        raise ValueError(f"Set SPLIT_DIR explicitly; found {len(candidates)} splits")
    return candidates.pop()


def safe_business_dir(split_dir: Path, business_id: str) -> Path:
    if not isinstance(business_id, str) or not business_id or business_id in {".", ".."}:
        raise ValueError("Invalid business_id")
    if "/" in business_id or "\\" in business_id or Path(business_id).is_absolute():
        raise ValueError("business_id must be one opaque directory name")
    root = (split_dir / "data").resolve()
    target = (root / business_id).resolve()
    target.relative_to(root)
    return target


def decode_source(blob: bytes) -> tuple[str, str, list[str]]:
    if blob.startswith((b"\xff\xfe", b"\xfe\xff")):
        return blob.decode("utf-16"), "utf-16", []
    try:
        return blob.decode("utf-8-sig"), "utf-8-sig", []
    except UnicodeDecodeError:
        from charset_normalizer import from_bytes

        matches = from_bytes(blob, cp_isolation=["cp1258", "utf_16", "cp1252"])
        best = matches.best()
        if best is not None:
            try:
                vietnamese = unicodedata.normalize("NFC", blob.decode("cp1258"))
                evidence = sum(
                    c in "ăĂđĐơƠưƯ" or bool(unicodedata.combining(c)) for c in vietnamese
                )
            except UnicodeDecodeError:
                vietnamese, evidence = "", 0
            if evidence and best.encoding in {"cp1252", "cp1258"}:
                return vietnamese, "cp1258", ["W_ENCODING_DETECTED", "W_ENCODING_CP1258_EVIDENCE"]
            return str(best), best.encoding, ["W_ENCODING_DETECTED"]
        return blob.decode("latin-1"), "latin-1", ["W_ENCODING_FALLBACK"]


def read_delimited(path: Path, *, require_dialect: bool = False) -> tuple[list[list], dict]:
    text, encoding, warnings = decode_source(path.read_bytes())
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        if require_dialect:
            raise ValueError("W_DELIMITER_UNRECOGNIZED") from None
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        warnings.append("W_DIALECT_ASSUMED")
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, quotechar='"'))
    return rows, {"encoding": encoding, "delimiter": delimiter, "warnings": warnings}


def inventory_files(split_dir: Path, paths: list[Path]) -> list[dict]:
    root = split_dir.resolve()
    return [
        {
            "path": p.resolve().relative_to(root).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": sha256_file(p),
        }
        for p in sorted(set(paths))
        if p.is_file()
    ]


def verify_inventory(split_dir: Path, inventory: list[dict]) -> dict:
    changed = [
        row["path"]
        for row in inventory
        if not (split_dir / row["path"]).is_file()
        or sha256_file(split_dir / row["path"]) != row["sha256"]
    ]
    return {"valid": not changed, "files_checked": len(inventory), "changed": changed}


def implementation_digest(namespace: dict) -> str:
    """Hash live function bodies, including notebook edits; ignore execution filenames."""

    def signature(code):
        return {
            "bytecode": code.co_code.hex(),
            "names": code.co_names,
            "constants": [
                signature(c) if isinstance(c, types.CodeType) else repr(c) for c in code.co_consts
            ],
        }

    functions = {}
    for name, value in namespace.items():
        local = getattr(value, "__module__", "") == namespace.get("__name__")
        local |= getattr(value, "__module__", "").startswith("datamate.preprocessing")
        if local and inspect.isfunction(value):
            functions[name] = signature(value.__code__)
        elif local and inspect.isclass(value):
            functions[name] = {
                key: signature(method.__code__)
                for key, method in vars(value).items()
                if inspect.isfunction(method)
            }
    return hashlib.sha256(json_text(functions).encode()).hexdigest()


def component_run(
    split_dir: Path,
    output_dir: Path,
    component: str,
    inventory: list[dict],
    settings: dict,
    code_sha256: str,
) -> Path:
    source, output = separate_output(split_dir, output_dir)
    identity = {
        "version": PREPROCESS_VERSION,
        "component": component,
        "files": inventory,
        "settings": settings,
        "code_sha256": code_sha256,
    }
    key = hashlib.sha256(json_text(identity).encode()).hexdigest()[:20]
    folder = output / component / key
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "manifest.json", identity)
    return folder


def finish_component(folder: Path, validation: dict) -> None:
    write_json(folder / "validation.json", validation)
    hashes = {
        p.relative_to(folder).as_posix(): sha256_file(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name not in {"complete.json"} and not p.name.endswith((".tmp", ".wal"))
    }
    write_json(
        folder / "complete.json", {"valid": validation.get("valid", False), "files_sha256": hashes}
    )
