"""Measure fresh-process startup through first synthetic HTML marker readiness.

This source-level, offscreen measurement is neither an EXE/OS cold-start test
nor a user-email or application-settings test. It uses only a generated marker.
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
MARKER = "HTML_READY_MARKER_7F3A91"
RUNS_PER_VERSION = 5
HTML_READY_TIMEOUT_SECONDS = 15


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _child(source_path: Path) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    import importlib.util
    import json as json_module
    import time as time_module

    total_started = time_module.perf_counter()
    stage_started = time_module.perf_counter()
    spec = importlib.util.spec_from_file_location("benchmark_message_widgets", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load widget source: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import_ms = (time_module.perf_counter() - stage_started) * 1000

    from PySide6.QtCore import QCoreApplication, QTimer, Qt, qVersion
    from PySide6.QtWidgets import QApplication
    # Match app.py: WebEngine shared OpenGL contexts must be configured before QApplication.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    stage_started = time_module.perf_counter()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    qapplication_ms = (time_module.perf_counter() - stage_started) * 1000

    stage_started = time_module.perf_counter()
    widget = module.MessageBodyWidget()
    constructor_ms = (time_module.perf_counter() - stage_started) * 1000

    setup_started = time_module.perf_counter()
    view = widget._ensure_html_view() if hasattr(widget, "_ensure_html_view") else widget._html_view
    if module.QWebEngineView is None or not isinstance(view, module.QWebEngineView):
        result = {
            "status": "failed_measurement",
            "failure": "QtWebEngine view unavailable; HTML marker cannot be verified",
            "module_import_ms": import_ms,
            "qapplication_ms": qapplication_ms,
            "widget_constructor_ms": constructor_ms,
            "total_to_html_ready_ms": None,
            "qt_version": qVersion(),
        }
        print(json_module.dumps(result))
        widget.close()
        widget.deleteLater()
        QTimer.singleShot(100, app.quit)
        app.exec()
        return 3

    page = view.page()
    outcome: dict[str, object] = {
        "status": "failed_measurement",
        "failure": "HTML marker was not observed before timeout",
        "load_finished_count": 0,
        "renderer_terminated": [],
    }
    html_started_at: float | None = None

    def on_load_finished(_ok: bool) -> None:
        outcome["load_finished_count"] = int(outcome["load_finished_count"]) + 1
        # Older empty-placeholder completions are ignored unless their text has
        # the exact generated marker from the requested synthetic message.
        page.toPlainText(check_marker)

    def check_marker(plain_text: str) -> None:
        if MARKER not in plain_text:
            return
        ready_at = time_module.perf_counter()
        outcome.update({
            "status": "success",
            "failure": None,
            "html_ready_ms": (ready_at - html_started_at) * 1000,
            "total_to_html_ready_ms": (ready_at - total_started) * 1000,
            "marker_detected": True,
        })
        app.quit()

    def on_renderer_terminated(status: object, exit_code: int) -> None:
        outcome["renderer_terminated"].append({"status": str(status), "exit_code": exit_code})
        outcome["failure"] = f"WebEngine renderer terminated: {status}, exit {exit_code}"
        app.quit()

    page.loadFinished.connect(on_load_finished)
    page.renderProcessTerminated.connect(on_renderer_terminated)
    setup_ms_before_email = (time_module.perf_counter() - setup_started) * 1000

    from eml_viewer.models.email_data import ParsedEmail
    email = ParsedEmail(
        subject="Synthetic startup benchmark",
        sender="benchmark@example.invalid",
        recipients="",
        date="",
        plain_body="Generated benchmark document",
        html_body=f"<html><body><p>{MARKER}</p></body></html>",
    )
    html_started_at = time_module.perf_counter()
    widget.set_email(email)
    html_setup_ms = (time_module.perf_counter() - setup_started) * 1000

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(app.quit)
    timer.start(HTML_READY_TIMEOUT_SECONDS * 1000)
    app.exec()
    timer.stop()

    result = {
        "status": outcome["status"],
        "failure": outcome["failure"],
        "module_import_ms": import_ms,
        "qapplication_ms": qapplication_ms,
        "widget_constructor_ms": constructor_ms,
        "renderer_and_email_setup_ms": html_setup_ms,
        "pre_email_renderer_setup_ms": setup_ms_before_email,
        "html_ready_ms": outcome.get("html_ready_ms"),
        "total_to_html_ready_ms": outcome.get("total_to_html_ready_ms"),
        "marker_detected": outcome.get("marker_detected", False),
        "load_finished_count": outcome["load_finished_count"],
        "renderer_process_pid": int(page.renderProcessPid()),
        "renderer_terminated": outcome["renderer_terminated"],
        "webengine_imported": module.QWebEngineView is not None,
        "html_renderer_view_created": widget._html_view is not None,
        "qt_version": qVersion(),
    }
    widget.close()
    widget.deleteLater()
    QTimer.singleShot(100, app.quit)
    app.exec()
    print(json_module.dumps(result))
    return 0 if result["status"] == "success" and result["marker_detected"] else 3


def _median_range(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(values), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def _run_child(version: str, source: Path, run_index: int, output_dir: Path,
               python: Path, env: dict[str, str]) -> dict[str, object]:
    stdout_path = output_dir / f"run-{run_index:02d}-{version}.stdout.txt"
    stderr_path = output_dir / f"run-{run_index:02d}-{version}.stderr.txt"
    command = [str(python), str(Path(__file__).resolve()), "--child", str(source)]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=HTML_READY_TIMEOUT_SECONDS + 25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
    succeeded = (
        exit_code == 0
        and isinstance(child_result, dict)
        and child_result.get("status") == "success"
        and child_result.get("marker_detected") is True
        and child_result.get("renderer_process_pid", 0) > 0
    )
    return {
        "version": version,
        "exit_code": exit_code,
        "subprocess_elapsed_ms": round(elapsed_ms, 3),
        "success": succeeded,
        "child_measurements": child_result,
        "stdout_file": stdout_path.name,
        "stderr_file": stderr_path.name,
    }


def main() -> int:
    output_dir = PROJECT_ROOT / "build" / "performance-overnight" / f"html-ready-{uuid.uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=False)
    live_source = PROJECT_ROOT / SOURCE_RELATIVE
    current_bytes = live_source.read_bytes()
    baseline_bytes = subprocess.run(
        ["git", "show", f"HEAD:{SOURCE_RELATIVE.as_posix()}"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout
    baseline_path = output_dir / "baseline_message_widgets.py"
    current_path = output_dir / "current_message_widgets.py"
    baseline_path.write_bytes(baseline_bytes)
    current_path.write_bytes(current_bytes)
    initial_live_hash = _sha256(current_bytes)
    hashes = {"baseline": _sha256(baseline_bytes), "current": initial_live_hash}

    python = Path(sys.executable)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    runs: dict[str, list[dict[str, object]]] = {"baseline": [], "current": []}
    run_order: list[str] = []
    sources = {"baseline": baseline_path, "current": current_path}
    run_number = 0
    for pair_index in range(RUNS_PER_VERSION):
        pair = ("baseline", "current") if pair_index % 2 == 0 else ("current", "baseline")
        for version in pair:
            run_number += 1
            runs[version].append(
                _run_child(version, sources[version], run_number, output_dir, python, env)
            )
            run_order.append(version)

    final_live_hash = _sha256(live_source.read_bytes())
    source_stable = final_live_hash == initial_live_hash
    runs_successful = all(run["success"] for version_runs in runs.values() for run in version_runs)
    status = "success" if source_stable and runs_successful else (
        "refused_mixed_source" if not source_stable else "failed_measurement"
    )

    summary: dict[str, object] = {}
    if status == "success":
        for version, version_runs in runs.items():
            children = [run["child_measurements"] for run in version_runs]
            summary[version] = {
                field: _median_range([float(child[field]) for child in children])
                for field in (
                    "module_import_ms", "qapplication_ms", "widget_constructor_ms",
                    "renderer_and_email_setup_ms", "html_ready_ms", "total_to_html_ready_ms",
                )
            }
    result = {
        "benchmark": "message_body_widget_first_html_marker_ready",
        "status": status,
        "scope": "source widget plus synthetic HTML marker readiness; offscreen, warm OS file cache; not EXE/OS cold start",
        "html_ready_timeout_seconds": HTML_READY_TIMEOUT_SECONDS,
        "marker": MARKER,
        "environment": {
            "python_executable": str(python),
            "python_version": sys.version.split()[0],
            "qt_platform": "offscreen",
            "qt_version": next((run["child_measurements"].get("qt_version")
                                for group in runs.values() for run in group
                                if isinstance(run["child_measurements"], dict)), None),
        },
        "source": {
            "baseline_ref": "HEAD",
            "baseline_sha256": hashes["baseline"],
            "current_sha256_before_runs": initial_live_hash,
            "current_sha256_after_runs": final_live_hash,
            "current_source_unchanged_during_measurement": source_stable,
        },
        "counterbalanced_run_order": run_order,
        "runs_per_version": RUNS_PER_VERSION,
        "summary": summary,
        "runs": runs,
        "raw_output_directory": str(output_dir),
    }
    result_path = output_dir / "results.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "results_json": str(result_path), "summary": summary}, indent=2))
    return 0 if status == "success" else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(_child(Path(sys.argv[2])))
    raise SystemExit(main())
