"""Diagnose real QPrinter PDF output for synthetic plain text.

The script compares HEAD and current MessageBodyWidget sources with several
printer modes, plus direct QTextDocument controls. It uses isolated offscreen
processes and never reads user mail or invokes a physical printer.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE = Path("src/eml_viewer/gui/message_widgets.py")
MARKER = "SYNTHETIC_PLAIN_PDF_MARKER_42A"
HTML_MARKER = "SYNTHETIC_HTML_CID_RED_IMAGE_MARKER_93B"
VARIANTS = (
    "widget_high_resolution",
    "widget_screen_resolution",
    "widget_300_dpi",
    "direct_high_resolution",
    "direct_screen_resolution",
    "direct_300_dpi",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _child(source_path: Path, variant: str, pdf_path: Path) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    import importlib.util
    import json as json_module
    from PySide6.QtCore import QCoreApplication, QTimer, Qt, qVersion
    from PySide6.QtGui import QTextDocument
    from PySide6.QtPrintSupport import QPrinter
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    printer_mode = (
        QPrinter.PrinterMode.ScreenResolution
        if "screen_resolution" in variant
        else QPrinter.PrinterMode.HighResolution
    )
    printer = QPrinter(printer_mode)
    if "300_dpi" in variant:
        printer.setResolution(300)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(pdf_path))

    callback: dict[str, object] = {"called": False, "ok": None}
    widget = None
    document = None
    widget_text = None
    if variant.startswith("widget_"):
        spec = importlib.util.spec_from_file_location("benchmark_message_widgets", source_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load source: {source_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from eml_viewer.models.email_data import ParsedEmail

        widget = module.MessageBodyWidget()
        widget.set_email(ParsedEmail("", "", "", "", MARKER, ""))
        widget_text = widget._plain_browser.toPlainText()
        widget.print_content(printer, lambda ok: callback.update(called=True, ok=bool(ok)))
    else:
        document = QTextDocument()
        document.setPlainText(MARKER)
        document.print_(printer)
        callback.update(called=True, ok=True)

    printer_resolution = printer.resolution()
    printer = None
    gc.collect()
    app.processEvents()

    deadline = time.monotonic() + 5
    last_size = -1
    stable_rounds = 0
    while time.monotonic() < deadline:
        try:
            size = pdf_path.stat().st_size
        except OSError:
            size = -1
        stable_rounds = stable_rounds + 1 if size > 0 and size == last_size else 0
        if stable_rounds >= 2:
            break
        last_size = size
        time.sleep(0.1)

    exists = pdf_path.exists()
    size_bytes = pdf_path.stat().st_size if exists else 0
    header_ok = False
    if exists:
        with pdf_path.open("rb") as pdf:
            header_ok = pdf.read(5) == b"%PDF-"
    result = {
        "status": "output_created" if callback["called"] and callback["ok"] is True and header_ok else "failed",
        "callback_called": callback["called"],
        "callback_ok": callback["ok"],
        "widget_print_busy_after_callback": getattr(widget, "print_busy", None),
        "widget_plain_text_before_print": widget_text,
        "printer_mode": "ScreenResolution" if "screen_resolution" in variant else "HighResolution",
        "printer_resolution_dpi": printer_resolution,
        "pdf_exists": exists,
        "pdf_size_bytes": size_bytes,
        "pdf_header": header_ok,
        "qt_version": qVersion(),
    }
    if widget is not None:
        widget.close()
        widget.deleteLater()
    del document
    cleanup_timer = QTimer()
    cleanup_timer.setSingleShot(True)
    cleanup_timer.timeout.connect(app.quit)
    cleanup_timer.start(100)
    app.exec()
    print(json_module.dumps(result))
    return 0 if result["status"] == "output_created" else 1


def _preview(pdf_path: Path, output_dir: Path) -> dict[str, object]:
    pdftoppm = shutil.which("pdftoppm")
    pdftotext = shutil.which("pdftotext")
    result: dict[str, object] = {
        "png_preview": None,
        "pdftotext_available": pdftotext is not None,
        "extracted_text": None,
        "text_contains_marker": None,
        "text_readability_verified": False,
        "manual_visual_review_required": pdftotext is None,
    }
    if pdftotext:
        extraction = subprocess.run(
            [pdftotext, str(pdf_path), "-"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10, check=False,
        )
        text = extraction.stdout.decode("utf-8", "replace")
        result["extracted_text"] = text
        result["text_contains_marker"] = MARKER in text
        result["pdftotext_exit_code"] = extraction.returncode
        result["text_readability_verified"] = extraction.returncode == 0 and MARKER in text
    if pdftoppm:
        prefix = output_dir / f"{pdf_path.stem}-preview"
        rendered = subprocess.run(
            [pdftoppm, "-f", "1", "-l", "1", "-scale-to", "600", "-singlefile", "-png",
             str(pdf_path), str(prefix)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
        )
        png_path = prefix.with_suffix(".png")
        if rendered.returncode == 0 and png_path.exists():
            result["png_preview"] = str(png_path)
        else:
            result["preview_error"] = rendered.stderr.decode("utf-8", "replace")[-1000:]
    else:
        result["preview_error"] = "pdftoppm unavailable"
    return result


def _cid_child(source_path: Path, pdf_path: Path, png_path: Path) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    import importlib.util
    import json as json_module
    import time as time_module
    from PySide6.QtCore import QBuffer, QCoreApplication, QIODevice, QTimer, Qt, qVersion
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtPrintSupport import QPrinter
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    spec = importlib.util.spec_from_file_location("benchmark_message_widgets", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load source: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from eml_viewer.models.attachment_data import InlineResource
    from eml_viewer.models.email_data import ParsedEmail

    red_image = QImage(32, 32, QImage.Format.Format_RGBA8888)
    red_image.fill(QColor(240, 16, 16))
    image_buffer = QBuffer()
    image_buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    red_image.save(image_buffer, "PNG")
    red_png = bytes(image_buffer.data())
    image_buffer.close()

    widget = module.MessageBodyWidget()
    view = widget._ensure_html_view() if hasattr(widget, "_ensure_html_view") else widget._html_view
    result: dict[str, object] = {
        "status": "failed",
        "failure": None,
        "html_marker_ready": False,
        "cid_file_exists": False,
        "cid_file_matches_fixture": False,
        "print_callback_called": False,
        "print_callback_ok": None,
        "print_busy_after_callback": None,
        "busy_signal_events": [],
        "renderer_terminated": [],
        "pdf_header": False,
        "pdf_size_bytes": 0,
        "png_preview": str(png_path),
        "red_pixels_in_pdf_preview": 0,
        "qt_version": qVersion(),
    }
    if module.QWebEngineView is None or view is None or not isinstance(view, module.QWebEngineView):
        result["failure"] = "QtWebEngine view unavailable"
        print(json_module.dumps(result))
        return 2

    page = view.page()
    busy_events: list[bool] = []
    widget.print_busy_changed.connect(busy_events.append)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(pdf_path))
    state = {"printed": False, "load_finished": 0}
    overall_timer = QTimer()
    overall_timer.setSingleShot(True)

    def finish(ok: bool) -> None:
        state["printed"] = True
        result["print_callback_called"] = True
        result["print_callback_ok"] = bool(ok)
        result["print_busy_after_callback"] = widget.print_busy
        result["busy_signal_events"] = busy_events[:]
        if not ok:
            result["failure"] = "MessageBodyWidget print callback returned false"
        app.quit()

    def on_plain_text(text: str) -> None:
        if HTML_MARKER not in text or state["printed"]:
            return
        result["html_marker_ready"] = True
        prepared = widget.current_prepared_html()
        inline_dir = widget._inline_temp_dir
        resource_files = list(Path(inline_dir.name).glob("*")) if inline_dir else []
        result["cid_file_exists"] = bool(resource_files)
        result["cid_file_matches_fixture"] = bool(
            resource_files and resource_files[0].read_bytes() == red_png
        )
        result["prepared_html_has_local_cid_uri"] = "file:///" in prepared
        widget._tabs.setCurrentIndex(1)
        widget.print_content(printer, finish)

    def on_load_finished(_ok: bool) -> None:
        state["load_finished"] += 1
        page.toPlainText(on_plain_text)

    def on_renderer_terminated(status: object, exit_code: int) -> None:
        result["renderer_terminated"].append({"status": str(status), "exit_code": exit_code})
        result["failure"] = f"WebEngine renderer terminated: {status}, exit {exit_code}"
        app.quit()

    page.loadFinished.connect(on_load_finished)
    page.renderProcessTerminated.connect(on_renderer_terminated)
    overall_timer.timeout.connect(app.quit)
    overall_timer.start(15_000)
    widget.set_email(ParsedEmail(
        "Synthetic CID PDF smoke", "benchmark@example.invalid", "", "",
        "Synthetic HTML print fixture",
        f'<html><body><p>{HTML_MARKER}</p>'
        '<img src="cid:red-square@example.invalid" width="32" height="32" '
        'style="width:32px;height:32px"></body></html>',
        inline_resources=[InlineResource(
            "red-square@example.invalid", "red-square.png", "image/png", red_png
        )],
    ))
    app.exec()
    overall_timer.stop()
    result["load_finished_count"] = state["load_finished"]
    if not result["print_callback_called"] and result["failure"] is None:
        result["failure"] = "HTML marker or print callback timed out"

    printer = None
    gc.collect()
    deadline = time_module.monotonic() + 5
    last_size = -1
    stable_rounds = 0
    while time_module.monotonic() < deadline:
        try:
            size = pdf_path.stat().st_size
        except OSError:
            size = -1
        stable_rounds = stable_rounds + 1 if size > 0 and size == last_size else 0
        if stable_rounds >= 2:
            break
        last_size = size
        time_module.sleep(0.1)
    result["output_stable"] = stable_rounds >= 2
    if pdf_path.exists():
        result["pdf_size_bytes"] = pdf_path.stat().st_size
        with pdf_path.open("rb") as pdf:
            result["pdf_header"] = pdf.read(5) == b"%PDF-"

    if shutil.which("pdftoppm") and pdf_path.exists():
        render = subprocess.run(
            [shutil.which("pdftoppm"), "-f", "1", "-l", "1", "-scale-to", "600",
             "-singlefile", "-png", str(pdf_path), str(png_path.with_suffix(""))],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
        )
        if render.returncode == 0 and png_path.exists():
            preview = QImage(str(png_path)).convertToFormat(QImage.Format.Format_RGB32)
            red_pixels = 0
            for y in range(preview.height()):
                for x in range(preview.width()):
                    pixel = preview.pixelColor(x, y)
                    if pixel.red() > 150 and pixel.red() > pixel.green() * 1.5 and pixel.red() > pixel.blue() * 1.5:
                        red_pixels += 1
            result["red_pixels_in_pdf_preview"] = red_pixels
        else:
            result["preview_error"] = render.stderr.decode("utf-8", "replace")[-1000:]

    result["status"] = "success" if (
        result["html_marker_ready"]
        and result["cid_file_exists"]
        and result["cid_file_matches_fixture"]
        and result.get("prepared_html_has_local_cid_uri")
        and result["print_callback_called"]
        and result["print_callback_ok"] is True
        and result["print_busy_after_callback"] is False
        and result["pdf_header"]
        and result["output_stable"]
        and result["red_pixels_in_pdf_preview"] > 10
    ) else "failed"
    widget.close()
    widget.deleteLater()
    cleanup = QTimer()
    cleanup.setSingleShot(True)
    cleanup.timeout.connect(app.quit)
    cleanup.start(100)
    app.exec()
    print(json_module.dumps(result))
    return 0 if result["status"] == "success" else 1


def _final_cid_smoke() -> int:
    output_dir = PROJECT_ROOT / "build" / "performance-overnight" / f"pdf-cid-final-{uuid.uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=False)
    live_source = PROJECT_ROOT / SOURCE_RELATIVE
    source_before = live_source.read_bytes()
    source_hash = _sha256(source_before)
    snapshot = output_dir / "current_message_widgets.py"
    snapshot.write_bytes(source_before)
    pdf_path = output_dir / "synthetic_html_cid_red.pdf"
    png_path = output_dir / "synthetic_html_cid_red-preview.png"
    python = Path(sys.executable)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    command = [str(python), str(Path(__file__).resolve()), "--cid-child",
               str(snapshot), str(pdf_path), str(png_path)]
    try:
        completed = subprocess.run(
            command, cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=40,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        exit_code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as error:
        exit_code = None
        stdout, stderr = error.stdout or b"", error.stderr or b""
    (output_dir / "child.stdout.txt").write_bytes(stdout)
    (output_dir / "child.stderr.txt").write_bytes(stderr)
    try:
        child = json.loads(stdout.decode("utf-8").strip().splitlines()[-1])
    except (IndexError, UnicodeDecodeError, json.JSONDecodeError):
        child = None
    source_after = _sha256(live_source.read_bytes())
    stable_source = source_hash == source_after
    success = stable_source and exit_code == 0 and isinstance(child, dict) and child.get("status") == "success"
    results = {
        "benchmark": "synthetic_html_cid_pdf_smoke",
        "status": "success" if success else "failed_or_source_changed",
        "scope": "current source snapshot; offscreen Qt print path; synthetic HTML and generated red CID image; no physical printer",
        "source_sha256_before": source_hash,
        "source_sha256_after": source_after,
        "source_unchanged_during_run": stable_source,
        "exit_code": exit_code,
        "child": child,
        "stdout_file": "child.stdout.txt",
        "stderr_file": "child.stderr.txt",
        "output_directory": str(output_dir),
        "plain_text_comparison": {
            "baseline_and_current_high_resolution": "manual PNG previews show black bars; marker is unreadable",
            "screen_resolution_and_300_dpi": "manual PNG previews show unreadable bars/pixels",
            "direct_qtextdocument": "manual PNG previews show black bars; marker is unreadable",
            "interpretation": "same failure across baseline/current and direct Qt controls suggests an offscreen Qt font/print rendering limitation; not proof about installed GUI or physical printers",
        },
        "text_extraction": {
            "pdftotext_available": shutil.which("pdftotext") is not None,
            "readability_claim": "plain text print is not counted as successful without marker extraction or verified readable preview",
        },
    }
    result_path = output_dir / "results.json"
    result_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"status": results["status"], "results_json": str(result_path), "child": child}, indent=2))
    return 0 if success else 1


def main() -> int:
    output_dir = PROJECT_ROOT / "build" / "performance-overnight" / f"pdf-print-diagnosis-{uuid.uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=False)
    live_source = PROJECT_ROOT / SOURCE_RELATIVE
    current_bytes = live_source.read_bytes()
    baseline_bytes = subprocess.run(
        ["git", "show", f"HEAD:{SOURCE_RELATIVE.as_posix()}"], cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    ).stdout
    snapshots = {
        "baseline": output_dir / "baseline_message_widgets.py",
        "current": output_dir / "current_message_widgets.py",
    }
    snapshots["baseline"].write_bytes(baseline_bytes)
    snapshots["current"].write_bytes(current_bytes)
    hashes = {"baseline": _sha256(baseline_bytes), "current": _sha256(current_bytes)}

    python = Path(sys.executable)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    runs: list[dict[str, object]] = []
    run_number = 0
    for version in ("baseline", "current"):
        for variant in VARIANTS[:3]:
            run_number += 1
            pdf_path = output_dir / f"{version}-{variant}.pdf"
            stdout_path = output_dir / f"run-{run_number:02d}.stdout.txt"
            stderr_path = output_dir / f"run-{run_number:02d}.stderr.txt"
            command = [str(python), str(Path(__file__).resolve()), "--child",
                       str(snapshots[version]), variant, str(pdf_path)]
            try:
                completed = subprocess.run(
                    command, cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=35,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                exit_code = completed.returncode
                stdout, stderr = completed.stdout, completed.stderr
            except subprocess.TimeoutExpired as error:
                exit_code = None
                stdout, stderr = error.stdout or b"", error.stderr or b""
            stdout_path.write_bytes(stdout)
            stderr_path.write_bytes(stderr)
            try:
                child = json.loads(stdout.decode("utf-8").strip().splitlines()[-1])
            except (IndexError, UnicodeDecodeError, json.JSONDecodeError):
                child = None
            record = {
                "version": version,
                "variant": variant,
                "exit_code": exit_code,
                "child": child,
                "stdout_file": stdout_path.name,
                "stderr_file": stderr_path.name,
            }
            if child and child.get("pdf_exists"):
                record["preview"] = _preview(pdf_path, output_dir)
            runs.append(record)

    for variant in VARIANTS[3:]:
        run_number += 1
        pdf_path = output_dir / f"direct-{variant}.pdf"
        stdout_path = output_dir / f"run-{run_number:02d}.stdout.txt"
        stderr_path = output_dir / f"run-{run_number:02d}.stderr.txt"
        command = [str(python), str(Path(__file__).resolve()), "--child",
                   str(snapshots["current"]), variant, str(pdf_path)]
        try:
            completed = subprocess.run(
                command, cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=35,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            exit_code = completed.returncode
            stdout, stderr = completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as error:
            exit_code = None
            stdout, stderr = error.stdout or b"", error.stderr or b""
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        try:
            child = json.loads(stdout.decode("utf-8").strip().splitlines()[-1])
        except (IndexError, UnicodeDecodeError, json.JSONDecodeError):
            child = None
        record = {
            "version": "direct_control",
            "variant": variant,
            "exit_code": exit_code,
            "child": child,
            "stdout_file": stdout_path.name,
            "stderr_file": stderr_path.name,
        }
        if child and child.get("pdf_exists"):
            record["preview"] = _preview(pdf_path, output_dir)
        runs.append(record)

    current_after = _sha256(live_source.read_bytes())
    source_stable = current_after == hashes["current"]
    result = {
        "benchmark": "qprinter_plain_text_output_diagnosis",
        "status": "diagnostic_complete" if source_stable else "refused_mixed_source",
        "scope": "synthetic text only; offscreen Qt PDF output; no physical printer",
        "source_hashes": {
            "baseline_head": hashes["baseline"],
            "current_before": hashes["current"],
            "current_after": current_after,
            "unchanged_during_run": source_stable,
        },
        "marker": MARKER,
        "readability_policy": (
            "PDF signature and nonblank render do not prove readable text; "
            "use pdftotext when available or review each rendered PNG manually"
        ),
        "variants": list(VARIANTS),
        "baseline_and_current_widget_runs": 3,
        "direct_document_control_runs": 3,
        "runs": runs,
        "output_directory": str(output_dir),
    }
    result_path = output_dir / "results.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "results_json": str(result_path),
                      "runs": [{"version": run["version"], "variant": run["variant"],
                                "exit_code": run["exit_code"],
                                "callback_ok": run["child"].get("callback_ok") if run["child"] else None,
                                "size": run["child"].get("pdf_size_bytes") if run["child"] else None,
                                "resolution": run["child"].get("printer_resolution_dpi") if run["child"] else None,
                                "text_contains_marker": run.get("preview", {}).get("text_contains_marker")}
                               for run in runs]}, indent=2))
    return 0 if source_stable else 1


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        raise SystemExit(_child(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])))
    if len(sys.argv) == 5 and sys.argv[1] == "--cid-child":
        raise SystemExit(_cid_child(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    if len(sys.argv) == 2 and sys.argv[1] == "--final-smoke":
        raise SystemExit(_final_cid_smoke())
    raise SystemExit(main())
