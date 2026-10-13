"""Measure EML parsing and bulk saving with synthetic data only.

These are source microbenchmarks, not Windows EXE startup or UI benchmarks.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser


class CountingParser(EmlParser):
    def __init__(self) -> None:
        self.loads = 0

    def _load_message(self, path):
        self.loads += 1
        return super()._load_message(path)


def summarize(values: list[float]) -> dict:
    return {"median_ms": round(statistics.median(values), 3),
            "min_ms": round(min(values), 3), "max_ms": round(max(values), 3),
            "samples_ms": [round(value, 3) for value in values]}


def create_case(root: Path, name: str, kind: str, count: int, size: int):
    message = EmailMessage()
    message["Subject"] = "Synthetic performance fixture"
    message["From"] = "sender@example.invalid"
    message["To"] = "receiver@example.invalid"
    message.set_content("Synthetic plain text.\n" * (4096 if kind == "plain" else 1))
    if kind == "html":
        message.add_alternative("<html><body>" + "<p>Synthetic HTML text.</p>" * 8192 +
                                "</body></html>", subtype="html")
    expected = {}
    for index in range(count):
        payload = bytes([index + 1]) * size
        filename = f"attachment-{index + 1}.bin"
        message.add_attachment(payload, maintype="application", subtype="octet-stream",
                               filename=filename)
        expected[filename] = hashlib.sha256(payload).hexdigest()
    path = root / f"{name}.eml"
    path.write_bytes(message.as_bytes())
    return path, expected


def run_benchmark(repeats: int) -> dict:
    cases = [("plain", "plain", 0, 0), ("html", "html", 0, 0),
             ("six-attachments", "plain", 6, 512 * 1024),
             ("large-attachment", "plain", 1, 8 * 1024 * 1024)]
    report = {"kind": "synthetic EML source microbenchmark", "repeats": repeats,
              "python": platform.python_version(), "platform": platform.platform(),
              "pyside6": version("PySide6"),
              "source_sha256": {
                  str(path.relative_to(PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in [PROJECT_ROOT / "src/eml_viewer/services/eml_parser.py",
                               PROJECT_ROOT / "src/eml_viewer/services/attachment_service.py"]
              },
              "recorded_utc": datetime.now(timezone.utc).isoformat(), "cases": []}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                         capture_output=True, text=True, check=False)
    report["git_head"] = git.stdout.strip()
    report["working_tree_dirty"] = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, capture_output=True,
        text=True, check=False).stdout.strip())
    with tempfile.TemporaryDirectory(prefix="eml-performance-") as temp:
        root = Path(temp)
        for name, kind, count, size in cases:
            path, expected = create_case(root, name, kind, count, size)
            parser = CountingParser()
            parsed = parser.parse_file(path)  # Warm the file cache; not EXE cold start.
            parse_times, save_times, save_loads = [], [], []
            for trial in range(repeats):
                start = time.perf_counter()
                parsed = parser.parse_file(path)
                parse_times.append((time.perf_counter() - start) * 1000)
                if count:
                    destination = root / f"{name}-save-{trial}"
                    destination.mkdir()
                    before = parser.loads
                    start = time.perf_counter()
                    saved = AttachmentService(parser=parser).save_attachments(
                        path, parsed.attachments, destination
                    )
                    save_times.append((time.perf_counter() - start) * 1000)
                    save_loads.append(parser.loads - before)
                    if len(saved) != count:
                        raise AssertionError("Wrong attachment count")
                    for item in saved:
                        if hashlib.sha256(item.path.read_bytes()).hexdigest() != expected[item.path.name]:
                            raise AssertionError("Saved attachment bytes changed")
            report["cases"].append({"name": name, "file_bytes": path.stat().st_size,
                                    "attachments": count, "each_attachment_bytes": size,
                                    "parse": summarize(parse_times),
                                    "bulk_save": summarize(save_times) if save_times else None,
                                    "bulk_save_source_loads": save_loads,
                                    "saved_bytes_verified": bool(count)})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("--repeats must be between 1 and 100")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Save once to a new path; preserve prior evidence.
    with args.output.open("x", encoding="utf-8") as stream:
        report = run_benchmark(args.repeats)
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
