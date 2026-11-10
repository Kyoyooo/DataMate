"""tools/count_params.py against hand-built safetensors headers."""

from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools" / "count_params.py"
spec = importlib.util.spec_from_file_location("count_params", TOOL)
count_params = importlib.util.module_from_spec(spec)
spec.loader.exec_module(count_params)


def write_st(path: Path, tensors: dict[str, tuple[str, list[int]]]) -> None:
    header, offset = {"__metadata__": {"format": "pt"}}, 0
    sizes = {"F32": 4, "BF16": 2, "F8_E4M3": 1}
    for name, (dtype, shape) in tensors.items():
        n = sizes[dtype]
        for d in shape:
            n *= d
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + n]}
        offset += n
    blob = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(blob)) + blob + b"\0" * offset)


def test_counts_every_tensor_including_scalars_and_other_dtypes(tmp_path):
    write_st(tmp_path / "a.safetensors", {"w": ("BF16", [3, 4]), "s": ("F32", []),
                                         "q": ("F8_E4M3", [10])})
    write_st(tmp_path / "b.safetensors", {"vision.w": ("BF16", [2, 2, 2])})
    r = count_params.count_dir(tmp_path)
    assert r["parameters"] == 12 + 1 + 10 + 8  # hand-computed
    assert r["parameters_by_dtype"] == {"BF16": 20, "F32": 1, "F8_E4M3": 10}
    assert r["files"] == {"a.safetensors": 23, "b.safetensors": 8} and r["within_limit"]


def test_tied_tensors_count_once_and_missing_shards_are_reported(tmp_path):
    write_st(tmp_path / "a.safetensors", {"embed": ("BF16", [5, 2])})
    write_st(tmp_path / "b.safetensors", {"embed": ("BF16", [5, 2]), "x": ("BF16", [1])})
    (tmp_path / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"embed": "a", "x": "b", "lost": "c"}}))
    r = count_params.count_dir(tmp_path)
    assert r["parameters"] == 11 and r["duplicate_tensor_names"] == ["embed"]
    assert r["missing_from_disk"] == ["lost"]
    assert count_params.main([str(tmp_path)]) == 1  # missing tensors fail the check


def test_limit_and_errors(tmp_path, capsys):
    write_st(tmp_path / "a.safetensors", {"w": ("F8_E4M3", [4])})
    assert count_params.main([str(tmp_path)]) == 0
    assert count_params.main([str(tmp_path / "nope")]) == 2
    (tmp_path / "bad.safetensors").write_bytes(b"123")
    assert count_params.main([str(tmp_path)]) == 2
    assert "too short" in capsys.readouterr().err
