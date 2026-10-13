from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-software-rasterizer --no-sandbox")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QUrl, Signal

from eml_viewer.gui.message_widgets import MessageBodyWidget
from eml_viewer.models.attachment_data import InlineResource
from eml_viewer.models.email_data import ParsedEmail


class MessageBodyWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_prepare_html_replaces_cid_image_reference(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body='<html><body><img src="cid:image001@example"></body></html>',
            inline_resources=[
                InlineResource(
                    content_id="image001@example",
                    filename="image001.png",
                    content_type="image/png",
                    payload=b"fake-png",
                )
            ],
        )

        prepared_html = widget._prepare_html(email)

        self.assertIn("file:///", prepared_html)
        self.assertNotIn("cid:image001@example", prepared_html)
        widget.clear()

    def test_prepare_html_keeps_duplicate_inline_filenames_distinct(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body=(
                '<html><body><img src="cid:first@example">'
                '<img src="cid:second@example"></body></html>'
            ),
            inline_resources=[
                InlineResource(
                    content_id="first@example",
                    filename="image.png",
                    content_type="image/png",
                    payload=b"first",
                ),
                InlineResource(
                    content_id="second@example",
                    filename="image.png",
                    content_type="image/png",
                    payload=b"second",
                ),
            ],
        )

        prepared_html = widget._prepare_html(email)

        self.assertIn("1-image.png", prepared_html)
        self.assertIn("2-image.png", prepared_html)
        self.assertNotIn("cid:first@example", prepared_html)
        self.assertNotIn("cid:second@example", prepared_html)
        widget.clear()

    def test_prepare_html_replaces_content_location_and_relative_image_reference(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body='<html><body><table><tr><td><img src="images/logo.png"></td></tr></table></body></html>',
            inline_resources=[
                InlineResource(
                    content_id="",
                    filename="logo.png",
                    content_type="image/png",
                    payload=b"fake-png",
                    content_location="images/logo.png",
                )
            ],
        )

        prepared_html = widget._prepare_html(email)

        self.assertIn("file:///", prepared_html)
        self.assertNotIn('src="images/logo.png"', prepared_html)
        widget.clear()

    def test_prepare_html_blocks_remote_images_by_default(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body='<html><body><img src="https://example.com/logo.png"></body></html>',
            inline_resources=[],
        )

        prepared_html = widget._prepare_html(email)

        self.assertNotIn("https://example.com/logo.png", prepared_html)
        self.assertIn("data:image/gif", prepared_html)

    def test_prepare_html_preserves_remote_images_when_allowed(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body='<html><body><img src="https://example.com/logo.png"></body></html>',
            inline_resources=[],
        )

        prepared_html = widget._prepare_html(email, allow_remote_resources=True)

        self.assertIn("https://example.com/logo.png", prepared_html)

    def test_prepare_html_replaces_unsafe_local_and_custom_resource_urls(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            "", "", "", "", "",
            '<img src="file://server/share/a.png">'
            '<img src="\\\\server\\share\\a.png">'
            '<img src="file:///C:/Windows/win.ini">'
            '<div style="background:url(custom-scheme:secret)"></div>',
            [],
        )
        prepared_html = widget._prepare_html(email)
        self.assertEqual(prepared_html.count("data:image/gif"), 4)
        self.assertNotIn("file://", prepared_html)
        self.assertNotIn("custom-scheme:", prepared_html)

    def test_inline_filename_is_bounded_and_failed_write_becomes_unresolved(self) -> None:
        widget = MessageBodyWidget()
        filename = "a" * 400 + "." + "b" * 120
        safe_filename = widget._safe_filename(filename)
        self.assertLessEqual(len(safe_filename), 112)
        self.assertTrue(safe_filename.endswith("." + "b" * 31))

        email = ParsedEmail(
            "", "", "", "", "", '<img src="cid:large@example">', [],
            [InlineResource("large@example", filename, "image/png", b"content")],
        )
        with patch.object(Path, "write_bytes", side_effect=OSError("path too long")):
            prepared_html = widget._prepare_html(email)
        self.assertIn("data:image/gif", prepared_html)
        self.assertIn("표시하지 못한 임베드 이미지", prepared_html)
        self.assertIn(widget._unresolved_resource_notice(3), prepared_html)
        self.assertEqual(widget._inline_temp_files, set())

    def test_request_interceptor_allows_only_scoped_local_and_permitted_remote_resources(self) -> None:
        from eml_viewer.gui import message_widgets

        self.assertTrue(message_widgets._load_webengine_types())

        class RequestInfo:
            def __init__(self, url: QUrl) -> None:
                self.url = url
                self.blocked = False

            def requestUrl(self) -> QUrl:
                return self.url

            def block(self, value: bool) -> None:
                self.blocked = value

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "inline"
            root.mkdir()
            valid_cid_image = root / "1-logo.png"
            valid_cid_image.write_bytes(b"image")
            interceptor = message_widgets.RemoteContentInterceptor()
            resolved_alias = Path(temp_dir) / "resolved-alias" / "inline"
            def resolved_path(path: Path, *_args, **_kwargs) -> Path:
                return resolved_alias if path == root else resolved_alias / path.name

            with patch.object(Path, "resolve", resolved_path):
                interceptor.set_allowed_inline_root(root, {valid_cid_image})

            def blocked(url: QUrl) -> bool:
                info = RequestInfo(url)
                interceptor.interceptRequest(info)
                return info.blocked

            inside_url = QUrl.fromLocalFile(str(valid_cid_image))
            host_url = QUrl("file://example.invalid/share/image.png")
            unc_url = QUrl("file://///server/share/secret.png")
            device_unc_url = QUrl("file:////?/C:/Windows/win.ini")
            traversal_url = QUrl.fromLocalFile(str(root / ".." / "outside.png"))
            trailing_space_url = QUrl.fromLocalFile(str(root / ".. " / "outside.png"))
            trailing_dot_url = QUrl.fromLocalFile(str(root / "..." / "outside.png"))
            ads_url = QUrl.fromLocalFile(str(root / "image.png:secret"))
            relative_url = QUrl("file:relative.png")
            outside_url = QUrl.fromLocalFile(str(Path(temp_dir) / "outside.png"))
            unknown_inside_url = QUrl.fromLocalFile(str(root / "sender-chosen.png"))
            custom_url = QUrl("custom-scheme:secret")
            remote_url = QUrl("https://example.invalid/image.png")
            with patch.object(Path, "resolve", side_effect=AssertionError("untrusted path resolved")):
                self.assertFalse(blocked(inside_url))
                self.assertTrue(blocked(host_url))
                self.assertTrue(blocked(unc_url))
                self.assertTrue(blocked(device_unc_url))
                self.assertTrue(blocked(traversal_url))
                self.assertTrue(blocked(trailing_space_url))
                self.assertTrue(blocked(trailing_dot_url))
                self.assertTrue(blocked(ads_url))
                self.assertTrue(blocked(relative_url))
                self.assertTrue(blocked(outside_url))
                self.assertTrue(blocked(unknown_inside_url))
                self.assertTrue(blocked(custom_url))
                self.assertTrue(blocked(remote_url))
            interceptor.allow_remote_content = True
            self.assertFalse(blocked(remote_url))
            self.assertFalse(blocked(QUrl("data:image/png;base64,AA==")))
            self.assertFalse(blocked(QUrl("about:blank")))

    @unittest.skipUnless(os.name == "nt", "Windows cross-drive TEMP aliases")
    def test_cid_alias_on_other_drive_is_allowed_in_either_root_order(self) -> None:
        from eml_viewer.gui import message_widgets

        self.assertTrue(message_widgets._load_webengine_types())

        class RequestInfo:
            def __init__(self, path: Path) -> None:
                self.url = QUrl.fromLocalFile(str(path))
                self.blocked = False

            def requestUrl(self) -> QUrl:
                return self.url

            def block(self, value: bool) -> None:
                self.blocked = value

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resource = root / "1-logo.png"
            resource.write_bytes(b"image")
            other_drive = "Z:" if root.drive.upper() != "Z:" else "Y:"
            alias = Path(other_drive + "/trusted-temp/inline")
            interceptor = message_widgets.RemoteContentInterceptor()

            def resolve_trusted(path: Path, *_args, **_kwargs) -> Path:
                return alias if path == root else alias / path.name

            with patch.object(Path, "resolve", resolve_trusted):
                interceptor.set_allowed_inline_root(root, {resource})

            lexical_root = interceptor._normalized_trusted_path(root)
            alias_root = interceptor._normalized_trusted_path(alias)
            # Control iteration order; a mismatched drive must not abort the loop.
            for roots in ([lexical_root, alias_root], [alias_root, lexical_root]):
                for candidate in (resource, alias / resource.name):
                    with self.subTest(roots=roots, candidate=candidate):
                        with patch.object(interceptor, "allowed_inline_roots", roots), patch.object(
                            Path, "resolve", side_effect=AssertionError("request path resolved")
                        ):
                            info = RequestInfo(candidate)
                            interceptor.interceptRequest(info)
                            self.assertFalse(info.blocked)

    def test_prepare_html_replaces_css_url_reference(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body='<html><body><div style="background-image:url(cid:bg@example)"></div></body></html>',
            inline_resources=[
                InlineResource(
                    content_id="bg@example",
                    filename="bg.png",
                    content_type="image/png",
                    payload=b"fake-png",
                )
            ],
        )

        prepared_html = widget._prepare_html(email)

        self.assertIn("file:///", prepared_html)
        self.assertNotIn("cid:bg@example", prepared_html)
        widget.clear()

    def test_prepare_html_replaces_srcset_reference(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body='<html><body><img srcset="cid:small@example 1x, images/large.png 2x"></body></html>',
            inline_resources=[
                InlineResource(
                    content_id="small@example",
                    filename="small.png",
                    content_type="image/png",
                    payload=b"small",
                ),
                InlineResource(
                    content_id="",
                    filename="large.png",
                    content_type="image/png",
                    payload=b"large",
                    content_location="images/large.png",
                ),
            ],
        )

        prepared_html = widget._prepare_html(email)

        self.assertIn("1-small.png", prepared_html)
        self.assertIn("2-large.png", prepared_html)
        self.assertNotIn("cid:small@example", prepared_html)
        self.assertNotIn("images/large.png", prepared_html)
        widget.clear()

    def test_zoom_controls_clamp_and_reset_percent(self) -> None:
        widget = MessageBodyWidget()

        widget.set_zoom_percent(25)
        self.assertEqual(widget.zoom_percent, 50)
        self.assertFalse(widget._zoom_out_button.isEnabled())

        widget.set_zoom_percent(250)
        self.assertEqual(widget.zoom_percent, 200)
        self.assertFalse(widget._zoom_in_button.isEnabled())

        widget.reset_zoom()
        self.assertEqual(widget.zoom_percent, 100)
        self.assertEqual(widget._zoom_label.text(), "100%")

    def test_plain_and_empty_mail_do_not_create_html_renderer(self) -> None:
        widget = MessageBodyWidget()
        with patch.object(widget, "_create_html_view", wraps=widget._create_html_view) as create_view:
            self.assertIsNone(widget._html_view)
            widget.set_email(ParsedEmail("", "", "", "", "plain body", "", []))
            self.assertIsNone(widget._html_view)
            widget.clear()
            self.assertIsNone(widget._html_view)
            create_view.assert_not_called()

    def test_first_html_mail_creates_renderer_once_and_reuses_it(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail("", "", "", "", "plain", "<html><body>hello</body></html>", [])
        with patch.object(widget, "_create_html_view", wraps=widget._create_html_view) as create_view:
            widget.set_email(email)
            first_view = widget._html_view
            self.assertIsNotNone(first_view)
            widget.set_email(email)
            widget.clear()
            widget.set_email(ParsedEmail("", "", "", "", "plain again", "", []))
            widget.set_email(email)
            self.assertIs(widget._html_view, first_view)
            create_view.assert_called_once_with()

    def test_webengine_import_fallback_uses_lazy_loader(self) -> None:
        from eml_viewer.gui import message_widgets

        with patch.object(message_widgets, "_load_webengine_types", return_value=False) as load_types:
            widget = MessageBodyWidget()
            widget.set_email(ParsedEmail("", "", "", "", "plain", "<p>hello</p>", []))
            self.assertIsInstance(widget._html_view, message_widgets.ZoomTextBrowser)
            load_types.assert_called_once_with()

    def test_lazy_webengine_keeps_security_policy(self) -> None:
        widget = MessageBodyWidget()
        widget.set_email(ParsedEmail("", "", "", "", "plain", "<p>hello</p>", []))
        from eml_viewer.gui.message_widgets import QWebEngineSettings

        if QWebEngineSettings is None:
            self.skipTest("Qt WebEngine is unavailable")
        settings = widget._html_view.page().settings()
        self.assertFalse(settings.testAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled))
        self.assertFalse(settings.testAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls))
        self.assertTrue(settings.testAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls))
        self.assertFalse(widget._remote_content_interceptors[0].allow_remote_content)

    def test_plain_print_and_search_work_without_html_renderer(self) -> None:
        widget = MessageBodyWidget()
        widget.set_email(ParsedEmail("", "", "", "", "needle needle", "", []))
        widget.show_search_bar()
        widget._handle_search("needle", True, False)
        self.assertEqual(len(widget._search_matches), 2)

        with patch.object(widget._plain_browser.document(), "print_") as print_document:
            result = Mock()
            widget.print_content(object(), result)
            print_document.assert_called_once()
            result.assert_called_once_with(True)
        self.assertIsNone(widget._html_view)

    def test_unrendered_html_tab_uses_plain_content_for_search_and_print(self) -> None:
        widget = MessageBodyWidget()
        widget.set_email(ParsedEmail("", "", "", "", "readable fallback", "", []))
        widget._tabs.setCurrentIndex(1)

        with patch.object(widget._search_bar, "set_match_status") as set_status:
            widget._handle_search("missing", True, False)
            set_status.assert_called_with(0, 0)

        with patch.object(widget._plain_browser.document(), "print_") as print_document:
            result = Mock()
            widget.print_content(object(), result)
            print_document.assert_called_once()
            result.assert_called_once_with(True)
        self.assertIsNone(widget._html_view)

    def test_print_rejects_concurrent_request_without_replacing_active_printer(self) -> None:
        widget = MessageBodyWidget()
        current_printer = object()
        rejected_printer = object()
        widget._active_printer = current_printer
        busy_changes: list[bool] = []
        widget.print_busy_changed.connect(busy_changes.append)
        rejected: list[bool] = []

        widget.print_content(rejected_printer, rejected.append)

        self.assertIs(widget._active_printer, current_printer)
        self.assertEqual(rejected, [False])
        self.assertEqual(busy_changes, [])

    def test_html_print_without_qt6_print_api_fails_and_clears_busy_state(self) -> None:
        from eml_viewer.gui import message_widgets

        class FakeWebView:
            def print_(self, _printer) -> None:
                raise AssertionError("unsupported print must not be called")

        widget = MessageBodyWidget()
        widget._tabs.setCurrentIndex(1)
        widget._html_view = FakeWebView()
        finished: list[bool] = []
        busy_changes: list[bool] = []
        widget.print_busy_changed.connect(busy_changes.append)
        with patch.object(message_widgets, "QWebEngineView", FakeWebView):
            widget.print_content(object(), finished.append)

        self.assertEqual(finished, [False])
        self.assertFalse(widget.print_busy)
        self.assertEqual(busy_changes, [True, False])

    def test_async_print_defers_mail_and_setting_renders_until_job_finishes(self) -> None:
        from eml_viewer.gui import message_widgets

        self.assertTrue(message_widgets._load_webengine_types())

        class FakeSignal:
            def __init__(self) -> None:
                self.callbacks = []

            def connect(self, callback, *_args) -> None:
                self.callbacks.append(callback)

            def disconnect(self, callback) -> None:
                if callback in self.callbacks:
                    self.callbacks.remove(callback)

            def emit(self, *args) -> None:
                callbacks, self.callbacks = self.callbacks, []
                for callback in callbacks:
                    callback(*args)

        class FakeSettings:
            def setAttribute(self, *_args) -> None:
                pass

        class FakePage:
            def __init__(self) -> None:
                self._settings = FakeSettings()
                self.renderProcessTerminated = FakeSignal()

            def settings(self) -> FakeSettings:
                return self._settings

        class FakeWebView(QWidget):
            def __init__(self, *_args) -> None:
                super().__init__()
                self.printFinished = FakeSignal()
                self.zoom_delta_requested = FakeSignal()
                self.loaded_html: list[str] = []
                self._page = FakePage()

            def page(self) -> FakePage:
                return self._page

            def setZoomFactor(self, _factor: float) -> None:
                pass

            def setHtml(self, content: str, _base_url=None) -> None:
                self.loaded_html.append(content)

            def print_(self, _printer) -> None:
                pass

            def findText(self, *_args) -> None:
                pass

        widget = MessageBodyWidget()
        view = FakeWebView()
        old_email = ParsedEmail(
            "", "", "", "", "old plain", '<img src="cid:old@example">',
            [], [InlineResource("old@example", "old.png", "image/png", b"old image")],
        )
        new_email = ParsedEmail(
            "", "", "", "", "new plain", '<img src="https://example.invalid/new.png">', [],
        )
        with patch.object(message_widgets, "QWebEngineView", FakeWebView), patch.object(
            widget, "_create_html_view", return_value=view
        ):
            widget.set_email(old_email)
            old_temp_dir = widget._inline_temp_dir.name
            finished: list[bool] = []
            widget.print_content(object(), finished.append)
            stale_finish = view.printFinished.callbacks[0]
            self.assertTrue(widget.print_busy)
            self.assertFalse(widget._open_browser_button.isEnabled())

            with patch.object(widget, "_prepare_html", wraps=widget._prepare_html) as prepare_html:
                widget.set_email(new_email)
                widget.set_remote_images_auto_load(True)
                widget._allow_remote_images()
                self.assertTrue(Path(old_temp_dir).exists())
                self.assertEqual(len(view.loaded_html), 1)
                self.assertEqual(widget.current_prepared_html(), "")
                prepare_html.assert_not_called()

                view.printFinished.emit(True)

                self.assertEqual(finished, [True])
                self.assertFalse(widget.print_busy)
                self.assertFalse(Path(old_temp_dir).exists())
                self.assertEqual(len(view.loaded_html), 2)
                self.assertIn("https://example.invalid/new.png", view.loaded_html[-1])
                self.assertTrue(widget._open_browser_button.isEnabled())
                prepare_html.assert_called_once_with(new_email, allow_remote_resources=True)

            second_printer = object()
            second_finished: list[bool] = []
            widget.print_content(second_printer, second_finished.append)
            stale_finish(False)
            self.assertTrue(widget.print_busy)
            self.assertIs(widget._active_printer, second_printer)
            view.printFinished.emit(True)
            self.assertEqual(second_finished, [True])

            widget._tabs.setCurrentIndex(1)
            clear_printer = object()
            widget.print_content(clear_printer)
            before_clear_retranslate = len(view.loaded_html)
            widget.clear()
            widget.retranslate_ui()
            self.assertEqual(len(view.loaded_html), before_clear_retranslate)
            self.assertEqual(widget.current_prepared_html(), "")
            with patch.object(widget, "_set_html_placeholder", wraps=widget._set_html_placeholder) as set_placeholder:
                view.printFinished.emit(True)
                self.assertGreaterEqual(set_placeholder.call_count, 1)
            self.assertIsNone(widget._current_email)
            self.assertIs(widget._html_view, view)
            self.assertEqual(len(view.loaded_html), before_clear_retranslate + 1)
            self.assertFalse(widget._open_browser_button.isEnabled())

            widget._tabs.setCurrentIndex(1)
            empty_print = object()
            widget.print_content(empty_print)
            before_empty_retranslate = len(view.loaded_html)
            widget.retranslate_ui()
            self.assertEqual(len(view.loaded_html), before_empty_retranslate)
            view.printFinished.emit(True)
            self.assertEqual(len(view.loaded_html), before_empty_retranslate + 1)

            render_failure_finished: list[bool] = []
            widget._tabs.setCurrentIndex(1)
            widget.print_content(object(), render_failure_finished.append)
            widget.set_email(new_email)
            with patch.object(widget, "_render_email", side_effect=OSError("render failed")):
                view.printFinished.emit(True)
            self.assertEqual(render_failure_finished, [True])
            self.assertFalse(widget.print_busy)
            self.assertTrue(widget._current_render_failed)
            self.assertIn("new plain", widget.current_prepared_html())

            terminated_finished: list[bool] = []
            widget.print_content(object(), terminated_finished.append)
            view.page().renderProcessTerminated.emit(object(), -1)
            self.assertEqual(terminated_finished, [False])
            self.assertFalse(widget.print_busy)

    def test_html_body_gets_zoom_wrapper(self) -> None:
        widget = MessageBodyWidget()

        widget.set_zoom_percent(150)

        self.assertIn("font-size: 150%", widget._zoomed_html("<p>Hello</p>"))

    def test_remote_controls_appear_for_blocked_remote_images(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="plain",
            html_body='<html><body><img src="https://example.com/logo.png"></body></html>',
            inline_resources=[],
        )

        widget.set_email(email)

        self.assertFalse(widget._load_remote_images_button.isHidden())
        widget._allow_remote_images()
        self.assertTrue(widget._load_remote_images_button.isHidden())

    def test_remote_images_auto_load_setting_preserves_remote_urls(self) -> None:
        widget = MessageBodyWidget()
        widget.set_remote_images_auto_load(True)
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="plain",
            html_body='<html><body><img src="https://example.com/logo.png"></body></html>',
            inline_resources=[],
        )

        widget.set_email(email)

        self.assertIn("https://example.com/logo.png", widget._current_prepared_html)
        self.assertNotIn("data:image/gif", widget._current_prepared_html)
        self.assertTrue(widget._load_remote_images_button.isHidden())


if __name__ == "__main__":
    unittest.main()
