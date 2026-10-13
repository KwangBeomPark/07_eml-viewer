"""Profile synthetic EML service paths separately from unprofiled wall timing.

This measures parse_file and single extraction, not GUI rendering or EXE startup.
Profiler inclusive timings overlap and must not be added together.
"""
import argparse
import cProfile
import hashlib
import json
import platform
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from benchmark_email import create_case
from eml_viewer.services.eml_parser import EmlParser


def measure(call, repeats):
    call()
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        call()
        times.append((time.perf_counter() - started) * 1000)
    profile = cProfile.Profile()
    profile.runcall(call)
    rows = []
    for (filename, line, name), (primitive, total, exclusive, inclusive, _) in pstats.Stats(profile).stats.items():
        rows.append({"file": Path(filename).name, "line": line, "function": name,
                     "calls": total, "primitive_calls": primitive,
                     "exclusive_ms": round(exclusive * 1000, 3),
                     "inclusive_ms": round(inclusive * 1000, 3)})
    return {"median_ms": round(statistics.median(times), 3),
            "min_ms": round(min(times), 3), "max_ms": round(max(times), 3),
            "samples_ms": [round(value, 3) for value in times],
            "top_cumulative": sorted(rows, key=lambda item: item["inclusive_ms"], reverse=True)[:12],
            "top_exclusive": sorted(rows, key=lambda item: item["exclusive_ms"], reverse=True)[:12],
            "parser_methods": [row for row in rows if row["file"] == "eml_parser.py"]}


def run(output: Path, repeats: int = 7):
    report = {"repeats": repeats, "python": platform.python_version(),
              "boundary": "synthetic EML source; warm cache; profiler timing is separate from wall samples",
              "source_sha256": hashlib.sha256((ROOT / "src/eml_viewer/services/eml_parser.py").read_bytes()).hexdigest(),
              "cases": []}
    with tempfile.TemporaryDirectory(prefix="eml-profile-") as temp:
        root = Path(temp)
        for name, kind, count, size in [("plain", "plain", 0, 0), ("html", "html", 0, 0),
                                         ("six-attachments", "plain", 6, 512 * 1024),
                                         ("eight-large", "plain", 8, 1024 * 1024)]:
            path, expected = create_case(root, name, kind, count, size)
            parser = EmlParser()
            item = {"name": name, "file_bytes": path.stat().st_size,
                    "parse": measure(lambda: parser.parse_file(path), report["repeats"])}
            if count:
                def extract():
                    return parser.extract_attachment(path, count - 1)
                verified = extract()
                assert hashlib.sha256(verified.payload).hexdigest() == expected[verified.info.filename]
                item["extract_last"] = measure(extract, report["repeats"])
            report["cases"].append(item)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(output), "cases": [
        {"name": item["name"], "parse_ms": item["parse"]["median_ms"],
         "extract_last_ms": item.get("extract_last", {}).get("median_ms")}
        for item in report["cases"]]}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("--repeats must be between 1 and 100")
    if args.output.exists():
        parser.error("Output already exists; use a new path to preserve evidence")
    run(args.output, args.repeats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
