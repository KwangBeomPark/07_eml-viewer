"""Compare repeated folder scans with FolderNavigationService reuse.

Uses a generated temporary directory only; it never reads user mail or app data.
Run with the project Python, for example ``.venv/Scripts/python.exe
scripts/benchmark_folder_navigation.py``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from eml_viewer.services import folder_navigation
from eml_viewer.services.folder_navigation import FolderNavigationService


FILE_COUNT = 2_000
OTHER_FILE_COUNT = 2_000
DIRECTORY_COUNT = 20
SELECTIONS = 30
RUNS = 7


class CountingFolderNavigationService(FolderNavigationService):
    """Count actual service scans without changing its filesystem behavior."""

    def __init__(self) -> None:
        super().__init__()
        self.scan_count = 0

    def _scan(self, folder: str | os.PathLike[str], key: str):
        self.scan_count += 1
        return super()._scan(folder, key)


def _generate_folder(folder: Path) -> None:
    for index in range(FILE_COUNT):
        extension = ".eml" if index % 2 == 0 else ".msg"
        (folder / f"mail-{index:04d}{extension}").write_bytes(b"x")
    for index in range(OTHER_FILE_COUNT):
        (folder / f"other-{index:04d}.txt").write_bytes(b"x")
    for index in range(DIRECTORY_COUNT):
        (folder / f"directory-{index:02d}.eml").mkdir()


def _baseline_listing(folder: Path) -> list[Path]:
    extensions = {".eml", ".msg"}
    files = [path for path in folder.iterdir()
             if path.is_file() and path.suffix.lower() in extensions]
    files.sort(key=lambda path: path.name.lower())
    return files


def _median_range(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(values), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def main() -> int:
    service_source = Path(folder_navigation.__file__)
    source_before = hashlib.sha256(service_source.read_bytes()).hexdigest()
    baseline_source = inspect.getsource(_baseline_listing)
    baseline_ref = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()
    run_order: list[list[str]] = []
    with tempfile.TemporaryDirectory(prefix="folder-navigation-benchmark-") as temporary:
        folder = Path(temporary)
        _generate_folder(folder)

        baseline_times: list[float] = []
        cached_times: list[float] = []
        baseline_scans: list[int] = []
        cached_scans: list[int] = []
        matching_lists = True

        # Keep setup and file creation outside all timed sections.
        for run_index in range(RUNS):
            service = CountingFolderNavigationService()
            order = ["baseline", "cached"] if run_index % 2 == 0 else ["cached", "baseline"]
            run_order.append(order)
            for version in order:
                start = time.perf_counter()
                if version == "baseline":
                    old_results = [_baseline_listing(folder) for _ in range(SELECTIONS)]
                    baseline_times.append((time.perf_counter() - start) * 1000)
                    baseline_scans.append(SELECTIONS)
                else:
                    new_results = [service.files(folder) for _ in range(SELECTIONS)]
                    cached_times.append((time.perf_counter() - start) * 1000)
                    cached_scans.append(service.scan_count)

            matching_lists = matching_lists and all(
                old == list(new) for old, new in zip(old_results, new_results)
            )

        result = {
            "benchmark": "folder_navigation_repeated_selection",
            "source": {
                "baseline_ref": baseline_ref,
                "baseline_listing_source": baseline_source,
                "baseline_listing_sha256": hashlib.sha256(baseline_source.encode()).hexdigest(),
                "service_sha256_before": source_before,
            },
            "counterbalanced_run_order": run_order,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
            "synthetic_directory": {
                "eml_msg_files": FILE_COUNT,
                "other_files": OTHER_FILE_COUNT,
                "directories": DIRECTORY_COUNT,
                "selections_per_run": SELECTIONS,
                "runs": RUNS,
            },
            "same_listing_each_selection": matching_lists,
            "baseline_iterdir_each_selection": {
                **_median_range(baseline_times),
                "source_scans_per_run": baseline_scans,
            },
            "folder_navigation_service": {
                **_median_range(cached_times),
                "source_scans_per_run": cached_scans,
            },
            "scope": "synthetic filesystem microbenchmark; no UI or EXE timing",
        }

    source_after = hashlib.sha256(service_source.read_bytes()).hexdigest()
    source_stable = source_before == source_after
    result["source"].update({
        "service_sha256_after": source_after,
        "unchanged_during_measurement": source_stable,
    })
    output_dir = PROJECT_ROOT / "build" / "performance-overnight"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"folder-navigation-{uuid.uuid4().hex}.json"
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "saved_to": str(output_path)}, indent=2))
    return 0 if source_stable and matching_lists and all(count == 1 for count in cached_scans) else 1


if __name__ == "__main__":
    raise SystemExit(main())
