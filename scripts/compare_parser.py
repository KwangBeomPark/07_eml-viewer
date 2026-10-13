"""Counterbalance before/after parser timings on identical synthetic EML files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from benchmark_email import create_case
from eml_viewer.services.eml_parser import EmlParser


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-parser", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=11)
    args = parser.parse_args()
    if not 3 <= args.repeats <= 100:
        parser.error("--repeats must be between 3 and 100")
    if args.output.exists():
        parser.error("Choose a new output path; previous evidence is preserved")
    snapshot = args.before_parser.resolve()
    spec = importlib.util.spec_from_file_location("eml_before_comparison", snapshot)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = {
        "boundary": "synthetic EML service; warm cache; alternating order; no profiler during timing",
        "before_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "after_sha256": hashlib.sha256((ROOT / "src/eml_viewer/services/eml_parser.py").read_bytes()).hexdigest(),
        "repeats": args.repeats, "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="eml-paired-") as temp:
        for name, count, size in [("six-attachments", 6, 512 * 1024),
                                  ("eight-large", 8, 1024 * 1024)]:
            path, expected = create_case(Path(temp), name, "plain", count, size)
            implementations = {"before": module.EmlParser(), "after": EmlParser()}
            for implementation in implementations.values():
                selected = implementation.extract_attachment(path, count - 1)
                assert hashlib.sha256(selected.payload).hexdigest() == expected[selected.info.filename]
                implementation.parse_file(path)
            item = {"name": name, "file_bytes": path.stat().st_size}
            for operation in ["parse_file", "extract_attachment"]:
                samples = {"before": [], "after": []}
                for trial in range(args.repeats):
                    order = ["before", "after"] if trial % 2 == 0 else ["after", "before"]
                    for label in order:
                        started = time.perf_counter()
                        if operation == "parse_file":
                            result = implementations[label].parse_file(path)
                        else:
                            result = implementations[label].extract_attachment(path, count - 1)
                        samples[label].append((time.perf_counter() - started) * 1000)
                        if operation == "extract_attachment":
                            assert hashlib.sha256(result.payload).hexdigest() == expected[result.info.filename]
                item[operation] = {
                    label: {"median_ms": round(statistics.median(values), 3),
                            "min_ms": round(min(values), 3), "max_ms": round(max(values), 3),
                            "samples_ms": [round(value, 3) for value in values]}
                    for label, values in samples.items()
                }
            report["cases"].append(item)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
