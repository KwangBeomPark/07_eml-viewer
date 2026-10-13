from __future__ import annotations

import mimetypes

from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from eml_viewer.gui.i18n import tr
from eml_viewer.gui.ui_helpers import ElidedLabel, display_safe_text, safe_tooltip
from eml_viewer.models.attachment_data import AttachmentInfo
from eml_viewer.services.attachment_policy import DANGEROUS_EXTENSIONS


_PROGRAM_EXTENSIONS = DANGEROUS_EXTENSIONS
_MIME_ALIASES = {
    ".zip": {"application/x-zip-compressed", "application/x-zip"},
    ".jpg": {"image/pjpeg"},
    ".jpeg": {"image/pjpeg"},
}
_EXTENSION_TYPES = {
    ".pdf": ("PDF", "application/pdf"),
    ".doc": ("Word", "application/msword"),
    ".docx": ("Word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": ("Excel", "application/vnd.ms-excel"),
    ".xlsx": ("Excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".ppt": ("PowerPoint", "application/vnd.ms-powerpoint"),
    ".pptx": ("PowerPoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".png": ("Image", "image/png"), ".jpg": ("Image", "image/jpeg"),
    ".jpeg": ("Image", "image/jpeg"), ".gif": ("Image", "image/gif"),
    ".bmp": ("Image", "image/bmp"), ".webp": ("Image", "image/webp"), ".svg": ("Image", "image/svg+xml"),
    ".zip": ("Archive", "application/zip"), ".eml": ("Email", "message/rfc822"),
    ".ics": ("Calendar", "text/calendar"), ".txt": ("Text", "text/plain"),
}
class _AttachmentTable(QTableWidget):
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self.selectionModel().hasSelection():
                self.clearSelection()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Menu or (
            event.key() == Qt.Key.Key_F10
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            current = self.currentIndex()
            if current.isValid():
                self.scrollTo(current)
            point = self.visualRect(current).center() if current.isValid() else QPoint(-1, -1)
            self.customContextMenuRequested.emit(point)
            event.accept()
            return
        super().keyPressEvent(event)


class AttachmentPanel(QWidget):
    """Attachment list, selection actions, and bulk save entry point."""

    save_requested = Signal(object)
    open_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._attachments: list[AttachmentInfo] = []
        self._expanded = True
        self._appearance_refresh_pending = False
        self.setObjectName("attachmentPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Keep these historical private attributes available to existing callers.
        self._toggle_button = QToolButton(self)
        self._table = _AttachmentTable(0, 3, self)
        self._open_button = QPushButton(self)
        self._save_button = QPushButton(self)
        self._save_all_button = QPushButton(self)
        self._hint_label = ElidedLabel(self)
        self._open_button.setObjectName("actionPrimary")
        self._save_button.setObjectName("actionSecondary")
        self._save_all_button.setObjectName("actionSecondary")
        self._hint_label.setObjectName("secondaryText")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._toggle_button.setObjectName("attachmentHeader")

        self._toggle_button.setCheckable(True)
        self._toggle_button.setChecked(True)
        self._toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_button.setMinimumHeight(32)
        self._toggle_button.clicked.connect(self._toggle_expanded)
        self._open_button.setMinimumHeight(32)
        self._save_button.setMinimumHeight(32)
        self._save_all_button.setMinimumHeight(32)
        self._open_button.clicked.connect(self._emit_open_requested)
        self._save_button.clicked.connect(self._emit_save_requested)
        self._save_all_button.clicked.connect(self._emit_save_all_requested)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setTabKeyNavigation(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(False)
        self._table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.activated.connect(self._on_activated)
        self._table.itemSelectionChanged.connect(self._update_button_state)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setAccessibleName(tr("attachment.panel.title"))
        self._table.setAccessibleDescription(tr("attachment.hint.none"))
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.Fixed)
        header.setSectionResizeMode(2, header.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 108)
        self._table.setColumnWidth(2, 82)
        self._table.setMinimumHeight(0)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self._toggle_button)
        header_layout.addStretch(1)

        command_layout = QHBoxLayout()
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(6)
        command_layout.addWidget(self._open_button)
        command_layout.addWidget(self._save_button)
        command_layout.addWidget(self._save_all_button)
        command_layout.addWidget(self._hint_label, 1)
        self._command_row = QWidget(self)
        self._command_row.setLayout(command_layout)
        self._command_row.setMinimumHeight(36)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)
        self._layout.addLayout(header_layout)
        self._layout.addWidget(self._command_row)
        self._layout.addWidget(self._table)
        QWidget.setTabOrder(self._toggle_button, self._open_button)
        QWidget.setTabOrder(self._open_button, self._save_button)
        QWidget.setTabOrder(self._save_button, self._save_all_button)
        QWidget.setTabOrder(self._save_all_button, self._table)
        self._table.setVisible(False)
        self._command_row.setVisible(False)
        self.setVisible(False)
        self.retranslate_ui()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._recompute_size_limits()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_attachments", None):
            self._recompute_size_limits()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if not hasattr(self, "_table"):
            return
        if event.type() in {
            QEvent.Type.StyleChange,
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        }:
            self._schedule_appearance_refresh()

    def retranslate_ui(self) -> None:
        self._table.setHorizontalHeaderLabels(
            [tr("attachment.table.filename"), tr("attachment.table.kind"), tr("attachment.table.size")]
        )
        self._refresh_type_cells()
        self._open_button.setText(tr("button.open_selected"))
        self._save_button.setText(tr("button.save_selected"))
        self._save_all_button.setText(tr("attachment.action.save_all"))
        self._open_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self._save_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self._save_all_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveAllButton))
        for button, label in (
            (self._open_button, tr("button.open_selected")),
            (self._save_button, tr("button.save_selected")),
            (self._save_all_button, tr("attachment.action.save_all")),
        ):
            button.setToolTip(safe_tooltip(label))
            button.setAccessibleName(label)
        self._update_summary()
        self._apply_expanded_state()
        self._update_button_state()

    def set_attachments(self, attachments: list[AttachmentInfo]) -> None:
        self._attachments = list(attachments)
        self._table.clearSelection()
        self._table.selectionModel().clearCurrentIndex()
        self._table.scrollToTop()
        self._table.setRowCount(len(self._attachments))
        for row, attachment in enumerate(self._attachments):
            filename = QTableWidgetItem(display_safe_text(attachment.filename))
            filename.setData(Qt.ItemDataRole.UserRole, attachment.index)
            filename.setToolTip(safe_tooltip(attachment.filename))
            filename.setFlags(filename.flags() & ~Qt.ItemFlag.ItemIsEditable)

            extension = self._final_extension(attachment.filename)
            type_label, mismatch = self._type_label(attachment)
            type_item = QTableWidgetItem(type_label)
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if extension in _PROGRAM_EXTENSIONS:
                type_item.setForeground(self._warning_color())
            mime_text = attachment.content_type or tr("attachment.type.file")
            type_item.setToolTip(
                safe_tooltip(mime_text, tr("attachment.type.mime_mismatch"))
                if mismatch else safe_tooltip(mime_text)
            )

            size_item = QTableWidgetItem(attachment.display_size)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            size_item.setToolTip(safe_tooltip(attachment.display_size))

            self._table.setItem(row, 0, filename)
            self._table.setItem(row, 1, type_item)
            self._table.setItem(row, 2, size_item)

        self._update_summary()
        self._apply_expanded_state()
        if len(self._attachments) == 1:
            index = self._table.model().index(0, 0)
            self._table.selectionModel().setCurrentIndex(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        self._update_button_state()

    def clear(self) -> None:
        self.set_attachments([])

    def current_attachment(self) -> AttachmentInfo | None:
        selected = self.selected_attachments()
        return selected[0] if selected else None

    def selected_attachments(self) -> list[AttachmentInfo]:
        selected_rows = {
            index.row() for index in self._table.selectionModel().selectedRows(0)
        }
        selected: list[AttachmentInfo] = []
        for row in sorted(selected_rows):
            item = self._table.item(row, 0)
            if item is None:
                continue
            attachment_index = item.data(Qt.ItemDataRole.UserRole)
            match = next((attachment for attachment in self._attachments
                          if attachment.index == attachment_index), None)
            if match is not None:
                selected.append(match)
        return selected

    def _type_label(self, attachment: AttachmentInfo) -> tuple[str, bool]:
        extension = self._final_extension(attachment.filename)
        if extension in _PROGRAM_EXTENSIONS:
            guessed, _encoding = mimetypes.guess_type(attachment.filename, strict=False)
            mismatch = self._mime_mismatch(extension, attachment.content_type, guessed)
            return tr("attachment.type.program", extension=extension[1:].upper()), mismatch
        known = _EXTENSION_TYPES.get(extension)
        if known:
            kind, expected_mime = known
            mismatch = self._mime_mismatch(extension, attachment.content_type, expected_mime)
            return tr(f"attachment.type.{kind.lower()}"), mismatch
        if extension:
            guessed, _encoding = mimetypes.guess_type(attachment.filename, strict=False)
            mismatch = self._mime_mismatch(extension, attachment.content_type, guessed)
            return display_safe_text(extension[1:].upper()), mismatch
        return tr("attachment.type.file"), False

    @staticmethod
    def _mime_mismatch(extension: str, declared_mime: str, expected_mime: str | None) -> bool:
        declared = declared_mime.strip().lower()
        if not declared or declared == "application/octet-stream":
            return False
        aliases = _MIME_ALIASES.get(extension, set())
        if declared in aliases:
            return False
        return bool(expected_mime and declared != expected_mime.lower())

    def _warning_color(self) -> QColor:
        base = self._table.palette().color(QPalette.ColorRole.Base)
        return QColor("#9f1239" if base.lightness() > 127 else "#f0c36a")

    def _refresh_type_cells(self) -> None:
        selected_rows = {
            index.row() for index in self._table.selectionModel().selectedRows(0)
        }
        self._table.blockSignals(True)
        try:
            for row, attachment in enumerate(self._attachments):
                item = self._table.item(row, 1)
                if item is None:
                    continue
                label, mismatch = self._type_label(attachment)
                item.setText(label)
                mime_text = attachment.content_type or tr("attachment.type.file")
                item.setToolTip(
                    safe_tooltip(mime_text, tr("attachment.type.mime_mismatch"))
                    if mismatch else safe_tooltip(mime_text)
                )
                if self._final_extension(attachment.filename) in _PROGRAM_EXTENSIONS:
                    item.setForeground(self._warning_color())
                else:
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)
        finally:
            self._table.blockSignals(False)
        actual_rows = {
            index.row() for index in self._table.selectionModel().selectedRows(0)
        }
        if actual_rows != selected_rows:
            self._table.clearSelection()
            for row in sorted(selected_rows):
                self._table.selectionModel().select(
                    self._table.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )

    @staticmethod
    def _final_extension(filename: str) -> str:
        base = filename.replace("\\", "/").rsplit("/", 1)[-1].rstrip(". \t")
        return ("." + base.rsplit(".", 1)[-1].lower()) if "." in base and not base.endswith(".") else ""

    def _update_button_state(self, *_args) -> None:
        selected = self.selected_attachments()
        has_selection = bool(selected)
        self._open_button.setEnabled(has_selection)
        self._save_button.setEnabled(has_selection)
        self._save_all_button.setEnabled(bool(self._attachments))
        self._update_summary()

    def _emit_save_requested(self) -> None:
        attachments = self.selected_attachments()
        if attachments:
            self.save_requested.emit(attachments)

    def _emit_open_requested(self) -> None:
        attachments = self.selected_attachments()
        if attachments:
            self.open_requested.emit(attachments)

    def _emit_save_all_requested(self) -> None:
        if self._attachments:
            self.save_requested.emit(list(self._attachments))

    def _on_activated(self, index) -> None:
        row = index.row()
        if not 0 <= row < len(self._attachments):
            return
        selected = self.selected_attachments()
        if not any(item.index == self._attachments[row].index for item in selected):
            selected = [self._attachments[row]]
        self.open_requested.emit(selected)

    def _toggle_expanded(self, checked: bool | None = None) -> None:
        self._expanded = self._toggle_button.isChecked()
        self._apply_expanded_state()

    def _update_summary(self) -> None:
        selected = self.selected_attachments() if self._attachments else []
        if selected:
            selected_size = sum(max(0, item.size) for item in selected)
            hint = tr("attachment.hint.selected", selected_count=len(selected), count=len(self._attachments),
                      size=self._display_size(selected_size))
        else:
            hint = tr("attachment.hint.none")
        self._hint_label.setText(hint)
        self._hint_label.setToolTip(safe_tooltip(hint))
        self._table.setAccessibleDescription(hint)
        total_size = sum(max(0, attachment.size) for attachment in self._attachments)
        title = tr("attachment.panel.title", count=len(self._attachments), size=self._display_size(total_size))
        self._table.setAccessibleName(title)
        expanded_text = tr("attachment.state.expanded" if self._expanded else "attachment.state.collapsed")
        self._toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        )
        self._toggle_button.setText(title)
        self._toggle_button.setAccessibleName(f"{title}, {expanded_text}")
        self._toggle_button.setToolTip(safe_tooltip(expanded_text))

    def _apply_expanded_state(self) -> None:
        has_attachments = bool(self._attachments)
        self.setVisible(has_attachments)
        self._toggle_button.setVisible(has_attachments)
        self._command_row.setVisible(has_attachments)
        self._table.setVisible(has_attachments and self._expanded)
        self._toggle_button.setChecked(self._expanded)
        self._update_summary()
        self._recompute_size_limits()

    def _recompute_size_limits(self) -> None:
        if not hasattr(self, "_table") or not hasattr(self, "_layout"):
            return
        if not self._attachments:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            return

        self.ensurePolished()
        self._toggle_button.ensurePolished()
        self._command_row.ensurePolished()
        self._table.ensurePolished()
        self._table.horizontalHeader().ensurePolished()
        self._layout.activate()

        toggle_height = max(32, self._toggle_button.sizeHint().height())
        self._toggle_button.setMinimumHeight(toggle_height)
        if self._expanded:
            header = self._table.horizontalHeader()
            header_height = max(26, header.sizeHint().height(), header.fontMetrics().height() + 10)
            header.setMinimumHeight(header_height)
            row_height = max(
                28,
                self._table.fontMetrics().height() + 10,
                self._table.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize) + 8,
            )
            self._table.verticalHeader().setDefaultSectionSize(row_height)
            frame = 2 * self._table.frameWidth()
            visible_rows = min(3, len(self._attachments))
            table_height = header_height + visible_rows * row_height + frame
            self._table.setMinimumHeight(table_height)
            self._table.setMaximumHeight(table_height)
        else:
            self._table.setMinimumHeight(0)
            self._table.setMaximumHeight(16777215)

        button_height = max(
            36,
            self._open_button.sizeHint().height(),
            self._save_button.sizeHint().height(),
            self._save_all_button.sizeHint().height(),
        )
        self._command_row.setMinimumHeight(button_height)
        self._layout.activate()
        panel_height = max(0, self._layout.sizeHint().height())
        self.setMinimumHeight(panel_height)
        self.setMaximumHeight(panel_height)

    def _schedule_appearance_refresh(self) -> None:
        if self._appearance_refresh_pending:
            return
        self._appearance_refresh_pending = True
        QTimer.singleShot(0, self, self._refresh_appearance)

    def _refresh_appearance(self) -> None:
        self._appearance_refresh_pending = False
        if not self._attachments:
            return
        self._refresh_type_cells()
        self._recompute_size_limits()

    def _show_context_menu(self, point: QPoint) -> None:
        row = self._table.rowAt(point.y())
        if row >= 0:
            self._select_context_row(row)
            menu = QMenu(self)
            open_action = menu.addAction(tr("attachment.context.open"))
            save_action = menu.addAction(tr("attachment.context.save"))
            menu.addSeparator()
            copy_action = menu.addAction(tr("attachment.context.copy_name"))
            chosen = menu.exec(self._table.viewport().mapToGlobal(point))
            if chosen is open_action:
                self._emit_open_requested()
            elif chosen is save_action:
                self._emit_save_requested()
            elif chosen is copy_action:
                from PySide6.QtWidgets import QApplication
                QApplication.clipboard().setText(self.current_attachment().filename if self.current_attachment() else "")
            return
        menu = QMenu(self)
        save_all = menu.addAction(tr("attachment.context.save_all"))
        save_all.setEnabled(bool(self._attachments))
        if menu.exec(self._table.viewport().mapToGlobal(point)) is save_all:
            self._emit_save_all_requested()

    def _select_context_row(self, row: int) -> None:
        if not 0 <= row < len(self._attachments):
            return
        selected_rows = {
            index.row() for index in self._table.selectionModel().selectedRows(0)
        }
        if row not in selected_rows:
            self._table.selectionModel().select(
                self._table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )

    @staticmethod
    def _display_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"
