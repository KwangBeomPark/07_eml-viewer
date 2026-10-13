from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication | None, theme: str) -> None:
    if app is None:
        return
    app._eml_theme_name = theme
    if not getattr(app, "_eml_theme_connected", False):
        app.styleHints().colorSchemeChanged.connect(
            lambda _scheme: _refresh_system_theme(app)
        )
        app._eml_theme_connected = True

    app._eml_applying_theme = True
    try:
        # Qt >= 6.8 is the project's dependency floor. Explicit themes also
        # tell the native Windows style which scheme to use.
        scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(
            theme, Qt.ColorScheme.Unknown
        )
        app.styleHints().setColorScheme(scheme)
        native_palette = app.style().standardPalette()
        system_dark = (
            theme == "system"
            and (
                app.styleHints().colorScheme() == Qt.ColorScheme.Dark
                or native_palette.color(QPalette.ColorRole.Window).lightness() < 128
            )
        )
        if theme == "dark" or system_dark:
            app.setPalette(_dark_palette())
            app.setStyleSheet(_common_style_sheet() + _dark_style_sheet())
        else:
            # Keep the native accent, but correct unreadable accent text.
            _ensure_highlight_contrast(native_palette)
            app.setPalette(native_palette)
            app.setStyleSheet(_common_style_sheet())
    finally:
        app._eml_applying_theme = False


def _refresh_system_theme(app: QApplication) -> None:
    if (
        getattr(app, "_eml_theme_name", "system") == "system"
        and not getattr(app, "_eml_applying_theme", False)
    ):
        apply_theme(app, "system")


def _ensure_highlight_contrast(palette: QPalette) -> None:
    def luminance(color: QColor) -> float:
        values = [color.redF(), color.greenF(), color.blueF()]
        values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(values, (0.2126, 0.7152, 0.0722)))

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        background = luminance(palette.color(group, QPalette.ColorRole.Highlight))
        foreground = luminance(palette.color(group, QPalette.ColorRole.HighlightedText))
        ratio = (max(background, foreground) + 0.05) / (min(background, foreground) + 0.05)
        if ratio < 4.5:
            black_ratio = (background + 0.05) / 0.05
            white_ratio = 1.05 / (background + 0.05)
            palette.setColor(group, QPalette.ColorRole.HighlightedText,
                             QColor("#000000" if black_ratio >= white_ratio else "#ffffff"))


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(32, 34, 37))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(238, 238, 238))
    palette.setColor(QPalette.ColorRole.Base, QColor(24, 26, 29))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(38, 41, 45))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(238, 238, 238))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(24, 26, 29))
    palette.setColor(QPalette.ColorRole.Text, QColor(238, 238, 238))
    palette.setColor(QPalette.ColorRole.Button, QColor(43, 47, 52))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(238, 238, 238))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 98, 98))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#959ca6"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, QColor("#2563eb"))
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#959ca6"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#959ca6"))
    return palette


def _common_style_sheet() -> str:
    """Use palette colours so light/system keep their native contrast settings."""
    return """
    QToolBar#mainToolbar {
        spacing: 6px;
        padding: 5px 8px;
        border-bottom: 1px solid palette(mid);
    }
    QToolBar#mainToolbar QToolButton {
        min-height: 28px;
        padding: 2px 8px;
        border: 2px solid transparent;
        border-radius: 5px;
    }
    QToolBar#mainToolbar QToolButton:hover { background: palette(alternate-base); }
    QWidget#messageHeader { border-bottom: 1px solid palette(mid); }
    QLabel#messageSubject { font-size: 17px; font-weight: 600; }
    QLabel#welcomeHeading { font-size: 24px; font-weight: 600; }
    QLabel#welcomeIcon { font-size: 44px; font-family: "Segoe UI Symbol"; color: palette(highlight); }
    QLabel#welcomeHint, QLabel#secondaryText { color: palette(text); }
    QWidget#attachmentPanel {
        background: palette(base);
        border: 1px solid palette(mid);
        border-radius: 7px;
    }
    QToolButton#attachmentHeader {
        font-weight: 600;
        border: 2px solid transparent;
        padding: 3px 8px;
        text-align: left;
    }
    QPushButton#actionPrimary, QToolButton#actionPrimary,
    QPushButton#actionSecondary {
        padding: 4px 12px;
        border: 2px solid palette(highlight);
        border-radius: 5px;
    }
    QPushButton#actionPrimary, QToolButton#actionPrimary {
        background: palette(highlight);
        color: palette(highlighted-text);
        font-weight: 600;
    }
    QPushButton#actionSecondary { background: palette(button); color: palette(button-text); }
    QPushButton#actionPrimary:disabled, QToolButton#actionPrimary:disabled,
    QPushButton#actionSecondary:disabled {
        background: palette(button);
        color: palette(placeholder-text);
        border-color: palette(mid);
    }
    QToolButton#attachmentHeader:focus, QToolButton#metadataDetailsToggle:focus,
    QToolBar#mainToolbar QToolButton:focus { border: 2px solid palette(highlight); }
    QPushButton#actionSecondary:focus { border-color: palette(text); }
    QPushButton#actionPrimary:focus, QToolButton#actionPrimary:focus {
        border-color: palette(text);
    }
    QTableWidget { selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }
    QHeaderView::section {
        background: palette(alternate-base);
        color: palette(text);
        border: none;
        border-bottom: 1px solid palette(mid);
        padding: 5px 8px;
        font-weight: 600;
    }
    QTabBar::tab { padding: 6px 12px; }
    QToolTip { padding: 5px; }
    """


def _dark_style_sheet() -> str:
    return """
    QMenuBar, QMenu, QStatusBar, QToolBar {
        background: #202225;
        color: #eeeeee;
    }
    QWidget#updateBanner {
        background: #25364a;
        color: #f5f7fb;
        border: 1px solid #3f6ea5;
    }
    QTabWidget::pane {
        border: 1px solid #4b4f58;
    }
    QTabBar::tab {
        background: #2b2f34;
        color: #eeeeee;
        border: 1px solid #4b4f58;
        padding: 6px 12px;
    }
    QTabBar::tab:selected {
        background: #181a1d;
        color: #ffffff;
        border-bottom-color: #181a1d;
    }
    QTabBar::tab:!selected {
        color: #c5cbd3;
    }
    QGroupBox {
        border: 1px solid #4b4f58;
        margin-top: 10px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }
    QLineEdit, QTextBrowser, QWebEngineView, QTableWidget, QComboBox {
        background: #181a1d;
        color: #eeeeee;
        border: 1px solid #4b4f58;
        selection-background-color: palette(highlight);
    }
    QPushButton {
        background: #2b2f34;
        color: #eeeeee;
        border: 1px solid #5a606a;
        padding: 5px 10px;
    }
    QPushButton#copyButton {
        padding: 2px;
    }
    QPushButton:disabled {
        color: #858b94;
        border-color: #3d4148;
    }
    QLabel#plainNotice {
        color: #f0c36a;
    }
    QLabel#remoteNotice {
        color: #f0c36a;
    }
    """
