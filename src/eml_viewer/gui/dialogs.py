from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from eml_viewer.gui.i18n import tr
from eml_viewer.gui.ui_helpers import display_safe_text


@dataclass(frozen=True)
class ForwardRecipientSelection:
    recipients: str
    recent_recipients: tuple[str, ...]


def select_eml_file(parent: QWidget, start_dir: Path | None = None) -> Path | None:
    filename, _ = QFileDialog.getOpenFileName(
        parent,
        tr("dialog.open_eml.title"),
        str(start_dir or Path.home()),
        tr("dialog.open_eml.filter"),
    )
    return Path(filename) if filename else None


def select_attachment_destination(parent: QWidget, default_filename: str) -> Path | None:
    filename, _ = QFileDialog.getSaveFileName(
        parent,
        tr("dialog.save_attachment.title"),
        str(Path.home() / default_filename),
        tr("dialog.save_attachment.filter"),
    )
    return Path(filename) if filename else None


def select_attachment_directory(parent: QWidget) -> Path | None:
    directory = QFileDialog.getExistingDirectory(
        parent,
        tr("dialog.save_attachment_dir.title"),
        str(Path.home()),
    )
    return Path(directory) if directory else None


def request_forward_recipients(
    parent: QWidget,
    recent_recipients: tuple[str, ...],
) -> ForwardRecipientSelection | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("forward.title"))
    dialog.setMinimumWidth(480)

    prompt_label = QLabel(tr("forward.recipient_prompt"), dialog)
    hint_label = QLabel(tr("forward.recipient_hint"), dialog)
    recipient_combo = QComboBox(dialog)
    recipient_combo.setEditable(True)
    recipient_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    recipient_combo.addItems(recent_recipients)
    recipient_combo.setCurrentIndex(-1)
    recipient_combo.lineEdit().setPlaceholderText(tr("forward.recipient_placeholder"))

    remove_button = QToolButton(dialog)
    remove_button.setIcon(dialog.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
    remove_button.setToolTip(tr("forward.recipient_remove_saved"))
    remove_button.setEnabled(bool(recent_recipients))

    def remove_selected_recipient() -> None:
        index = recipient_combo.findText(recipient_combo.currentText(), Qt.MatchFlag.MatchFixedString)
        if index < 0:
            return
        recipient_combo.removeItem(index)
        recipient_combo.setEditText("")
        remove_button.setEnabled(recipient_combo.count() > 0)

    remove_button.clicked.connect(remove_selected_recipient)

    recipient_layout = QHBoxLayout()
    recipient_layout.setContentsMargins(0, 0, 0, 0)
    recipient_layout.addWidget(recipient_combo, stretch=1)
    recipient_layout.addWidget(remove_button)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=dialog,
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)

    layout = QVBoxLayout(dialog)
    layout.addWidget(prompt_label)
    layout.addLayout(recipient_layout)
    layout.addWidget(hint_label)
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    return ForwardRecipientSelection(
        recipients=recipient_combo.currentText(),
        recent_recipients=tuple(recipient_combo.itemText(index) for index in range(recipient_combo.count())),
    )


def ask_overwrite(parent: QWidget, path: Path) -> bool:
    return ask_warning_yes_no(
        parent,
        tr("dialog.overwrite.title"),
        tr("dialog.overwrite.body", path=display_safe_text(path)),
    )


def ask_execute_file_operation(parent: QWidget, title: str, preview_message: str) -> bool:
    safe_preview = "\n".join(display_safe_text(line) for line in str(preview_message).split("\n"))
    return ask_warning_yes_no(
        parent,
        title,
        tr("dialog.execute.body", preview_message=safe_preview),
    )


def show_error(parent: QWidget, title: str, message: str) -> None:
    # Email filenames and parser errors are untrusted; never auto-detect markup.
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setIcon(QMessageBox.Icon.Critical)
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.setText(message)
    dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    dialog.exec()


def ask_warning_yes_no(parent: QWidget, title: str, message: str) -> bool:
    """Confirm attachment operations with literal text and a safe default."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.setText(message)
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    dialog.setDefaultButton(QMessageBox.StandardButton.No)
    dialog.setEscapeButton(QMessageBox.StandardButton.No)
    return dialog.exec() == QMessageBox.StandardButton.Yes


def show_warning(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def show_info(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def show_source_dialog(parent: QWidget, title: str, source_text: str) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(750, 550)

    layout = QVBoxLayout(dialog)
    text_edit = QPlainTextEdit(dialog)
    text_edit.setPlainText(source_text)
    text_edit.setReadOnly(True)
    text_edit.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 10pt;")

    btn_layout = QHBoxLayout()
    copy_btn = QPushButton(tr("dialog.copy_to_clipboard"), dialog)
    close_btn = QPushButton(tr("dialog.close"), dialog)
    close_btn.clicked.connect(dialog.accept)

    def copy_content():
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        clipboard.setText(source_text)
        show_info(dialog, tr("dialog.copy_success.title"), tr("dialog.copy_success.message"))

    copy_btn.clicked.connect(copy_content)

    btn_layout.addWidget(copy_btn)
    btn_layout.addStretch(1)
    btn_layout.addWidget(close_btn)

    layout.addWidget(text_edit)
    layout.addLayout(btn_layout)
    dialog.exec()
