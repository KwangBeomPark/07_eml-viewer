"""Measure MessageBodyWidget initialization in fresh, isolated Qt processes.

This is a warm-OS-cache source measurement, not an EXE cold start or an
HTML-ready measurement. A generated empty document is used only to confirm
that an eagerly constructed WebEngine renderer starts successfully.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE = Path("src/eml_viewer/gui/message_widgets.py")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _child(source_path: Path) -> int:
    # Force headless Qt before importing any PySide6 modules.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    import importlib.util
    import json as json_module
    import time as time_module
    from PySide6.QtCore import QTimer, qVersion
    from PySide6.QtWidgets import QApplication

    result: dict[str, object] = {}
    start = time_module.perf_counter()
    spec = importlib.util.spec_from_file_location("benchmark_message_widgets", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load widget source: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result["module_import_ms"] = (time_module.perf_counter() - start) * 1000

    start = time_module.perf_counter()
    app = QApplication([])
    result["qapplication_ms"] = (time_module.perf_counter() - start) * 1000

    start = time_module.perf_counter()
    widget = module.MessageBodyWidget()
    result["widget_constructor_ms"] = (time_module.perf_counter() - start) * 1000
    result["webengine_imported_after_constructor"] = bool(
        module.QWebEngineView is not None
    )
    result["html_renderer_view_created"] = widget._html_view is not None
    result["renderer_process_pid"] = None
    result["renderer_process_status"] = "not_created_by_constructor"
    result["renderer_bootstrap_ms"] = None

    if module.QWebEngineView is not None and isinstance(widget._html_view, module.QWebEngineView):
        page = widget._html_view.page()
        terminated: list[object] = []
        page.renderProcessTerminated.connect(
            lambda status, exit_code: terminated.append((status, exit_code))
        )
        start = time_module.perf_counter()
        page.setHtml("<html><body></body></html>")
        deadline = time_module.monotonic() + 15
        renderer_pid = 0
        while time_module.monotonic() < deadline and renderer_pid <= 0 and not terminated:
            app.processEvents()
            renderer_pid = int(page.renderProcessPid())
            time_module.sleep(0.01)
        result["renderer_bootstrap_ms"] = (time_module.perf_counter() - start) * 1000
        result["renderer_process_pid"] = renderer_pid or None
        if renderer_pid > 0 and not terminated:
            result["renderer_process_status"] = "started"
        else:
            result["renderer_process_status"] = "failed"
            result["renderer_failure"] = repr(terminated) if terminated else "renderer PID did not start"

    result["qt_version"] = qVersion()
    from PySide6 import __version__ as pyside_version
    result["pyside6_version"] = pyside_version

    widget.close()
    widget.deleteLater()
    # Give Qt its normal event-loop shutdown so deferred QObject destruction
    # and WebEngine IPC complete before the fresh measurement process exits.
    QTimer.singleShot(100, app.quit)
    app.exec()
    del widget
    print(json_module.dumps(result))
    if result["renderer_process_status"] == "failed":
        return 3
    return 0


def _median_range(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(values), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def main() -> int:
    output_root = PROJECT_ROOT / "build" / "performance-overnight" / f"widget-startup-{uuid.uuid4().hex}"
    output_root.mkdir(parents=True, exist_ok=False)

    source_path = PROJECT_ROOT / SOURCE_RELATIVE
    current_bytes = source_path.read_bytes()
    baseline = subprocess.run(
        ["git", "show", f"HEAD:{SOURCE_RELATIVE.as_posix()}"],
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    baseline_path = output_root / "baseline_message_widgets.py"
    baseline_path.write_bytes(baseline)

    sources = {"baseline": baseline_path, "current": source_path}
    source_hashes = {"baseline": _sha256(baseline), "current": _sha256(current_bytes)}
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
    python = Path(sys.executable)

    # Alternate which version runs first so background host load is balanced.
    order: list[str] = []
    runs_by_version: dict[str, list[dict[str, object]]] = {"baseline": [], "current": []}
    run_number = 0
    for pair in range(5):
        pair_order = ("baseline", "current") if pair % 2 == 0 else ("current", "baseline")
        for version in pair_order:
            run_number += 1
            stdout_path = output_root / f"run-{run_number:02d}-{version}.stdout.txt"
            stderr_path = output_root / f"run-{run_number:02d}-{version}.stderr.txt"
            command = [str(python), str(Path(__file__).resolve()), "--child", str(sources[version])]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    cwd=PROJECT_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=40,
                    creationflags=creationflags,
                )
                exit_code = completed.returncode
                stdout_bytes = completed.stdout
                stderr_bytes = completed.stderr
            except subprocess.TimeoutExpired as error:
                exit_code = None
                stdout_bytes = error.stdout or b""
                stderr_bytes = error.stderr or b""
            elapsed_ms = (time.perf_counter() - started) * 1000
            stdout_path.write_bytes(stdout_bytes)
            stderr_path.write_bytes(stderr_bytes)
            try:
                child_result = json.loads(stdout_bytes.decode("utf-8").strip().splitlines()[-1])
            except (IndexError, UnicodeDecodeError, json.JSONDecodeError):
                child_result = None
            record = {
                "version": version,
                "order": run_number,
                "exit_code": exit_code,
                "subprocess_elapsed_ms": round(elapsed_ms, 3),
                "child_measurements": child_result,
                "stdout_file": stdout_path.name,
                "stderr_file": stderr_path.name,
            }
            runs_by_version[version].append(record)
            order.append(version)

    metrics: dict[str, object] = {}
    all_success = True
    for version, runs in runs_by_version.items():
        successful = [
            run["child_measurements"] for run in runs
            if run["exit_code"] == 0 and isinstance(run["child_measurements"], dict)
        ]
        if len(successful) != len(runs):
            all_success = False
        stage_metrics: dict[str, object] = {}
        for key in ("module_import_ms", "qapplication_ms", "widget_constructor_ms", "renderer_bootstrap_ms"):
            values = [item[key] for item in successful if isinstance(item.get(key), (int, float))]
            stage_metrics[key] = _median_range(values) if values else None
        stage_metrics["webengine_imported_after_constructor"] = [
            item.get("webengine_imported_after_constructor") for item in successful
        ]
        stage_metrics["html_renderer_view_created"] = [
            item.get("html_renderer_view_created") for item in successful
        ]
        stage_metrics["renderer_process_status"] = [
            item.get("renderer_process_status") for item in successful
        ]
        metrics[version] = stage_metrics

    result = {
        "benchmark": "message_body_widget_fresh_process_startup",
        "status": "success" if all_success else "failed_measurement",
        "scope": "source widget initialization with warm OS file caches; not EXE or OS cold start; not HTML-ready latency",
        "environment": {
            "python_executable": str(python),
            "python_version": sys.version.split()[0],
            "qt_platform": "offscreen",
            "pyside6_version": runs_by_version["current"][0]["child_measurements"].get("pyside6_version")
            if isinstance(runs_by_version["current"][0]["child_measurements"], dict) else None,
            "qt_version": runs_by_version["current"][0]["child_measurements"].get("qt_version")
            if isinstance(runs_by_version["current"][0]["child_measurements"], dict) else None,
        },
        "source": {
            "baseline_ref": "HEAD",
            "baseline_sha256": source_hashes["baseline"],
            "current_sha256": source_hashes["current"],
        },
        "counterbalanced_run_order": order,
        "runs_per_version": len(runs_by_version["baseline"]),
        "summary": metrics,
        "runs": runs_by_version,
        "raw_output_directory": str(output_root),
    }
    json_path = output_root / "results.json"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "results_json": str(json_path), "summary": metrics}, indent=2))
    return 0 if all_success else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(_child(Path(sys.argv[2])))
    raise SystemExit(main())
