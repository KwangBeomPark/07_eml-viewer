from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eml_viewer.models.attachment_data import AttachmentInfo
from eml_viewer.gui.i18n import tr


class AttachmentPanel(QWidget):
    """첨부파일 목록과 저장 버튼을 가진 화면입니다."""

    save_requested = Signal(object)
    open_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._attachments: list[AttachmentInfo] = []
        self._expanded = False

        self._title_label = QLabel(self)
        self._toggle_button = QPushButton(self)
        self._table = QTableWidget(0, 4, self)
        self._select_all_button = QPushButton(self)
        self._open_button = QPushButton(self)
        self._save_button = QPushButton(self)

        self.retranslate_ui()
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)

        self._toggle_button.clicked.connect(self._toggle_expanded)
        self._select_all_button.setEnabled(False)
        self._select_all_button.clicked.connect(self._toggle_select_all)
        self._open_button.setEnabled(False)
        self._open_button.clicked.connect(self._emit_open_requested)
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._emit_save_requested)
        self._table.itemChanged.connect(self._update_button_state)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self._select_all_shortcut = QShortcut(QKeySequence("Ctrl+A"), self)
        self._select_all_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._select_all_shortcut.activated.connect(self._toggle_select_all)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self._toggle_button)
        header_layout.addWidget(self._select_all_button)
        header_layout.addWidget(self._open_button)
        header_layout.addWidget(self._save_button)

        layout = QVBoxLayout(self)
        layout.addLayout(header_layout)
        layout.addWidget(self._table)
        self.setVisible(False)

    def retranslate_ui(self) -> None:
        self._table.setHorizontalHeaderLabels(
            ["", tr("attachment.table.filename"), tr("attachment.table.kind"), tr("attachment.table.size")]
        )
        self._select_all_button.setText(tr("button.select_all"))
        self._open_button.setText(tr("button.open_selected"))
        self._save_button.setText(tr("button.save_selected"))
        self._update_summary()
        self._toggle_button.setText(tr("button.collapse") if self._expanded else tr("button.expand"))

    def set_attachments(self, attachments: list[AttachmentInfo]) -> None:
        self._attachments = list(attachments)
        self._expanded = bool(self._attachments)
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._attachments))

        for row, attachment in enumerate(self._attachments):
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            checkbox_item.setCheckState(Qt.CheckState.Unchecked)

            filename_item = QTableWidgetItem(attachment.filename)
            filename_item.setData(Qt.ItemDataRole.UserRole, attachment.index)

            self._table.setItem(row, 0, checkbox_item)
            self._table.setItem(row, 1, filename_item)
            self._table.setItem(row, 2, QTableWidgetItem(attachment.content_type))
            self._table.setItem(row, 3, QTableWidgetItem(attachment.display_size))

        self._table.blockSignals(False)
        self._table.setColumnWidth(0, 34)
        self._table.resizeColumnsToContents()
        self._update_summary()
        self._apply_expanded_state()
        self._update_button_state()

    def clear(self) -> None:
        self.set_attachments([])

    def current_attachment(self) -> AttachmentInfo | None:
        selected = self.selected_attachments()
        if not selected:
            return None
        return selected[0]

    def selected_attachments(self) -> list[AttachmentInfo]:
        selected: list[AttachmentInfo] = []
        for row, attachment in enumerate(self._attachments):
            item = self._table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(attachment)
        return selected

    def _update_button_state(self) -> None:
        self._update_summary()
        has_selection = self._expanded and bool(self.selected_attachments())
        self._save_button.setEnabled(has_selection)
        self._open_button.setEnabled(has_selection)
        self._select_all_button.setEnabled(self._expanded and bool(self._attachments))
        all_checked = all(
            self._table.item(row, 0) is not None and self._table.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(len(self._attachments))
        ) if self._attachments else False
        self._select_all_button.setText(tr("button.deselect_all") if all_checked else tr("button.select_all"))

    def _emit_save_requested(self) -> None:
        attachments = self.selected_attachments()
        if attachments:
            self.save_requested.emit(attachments)

    def _emit_open_requested(self) -> None:
        attachments = self.selected_attachments()
        if attachments:
            self.open_requested.emit(attachments)

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column > 0 and 0 <= row < len(self._attachments):
            self.open_requested.emit([self._attachments[row]])

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded_state()
        self._update_button_state()

    def _toggle_select_all(self) -> None:
        if not self._attachments or not self._expanded:
            return
        all_checked = all(
            self._table.item(row, 0) is not None and self._table.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(len(self._attachments))
        )
        new_state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        self._table.blockSignals(True)
        for row in range(len(self._attachments)):
            item = self._table.item(row, 0)
            if item is not None:
                item.setCheckState(new_state)
        self._table.blockSignals(False)
        self._update_button_state()

    def _update_summary(self) -> None:
        count = len(self._attachments)
        selected_count = len(self.selected_attachments()) if count else 0
        total_size = sum(max(0, attachment.size) for attachment in self._attachments)
        self._title_label.setText(
            tr("attachment.title", count=count, size=self._display_size(total_size), selected_count=selected_count)
        )

    def _apply_expanded_state(self) -> None:
        has_attachments = bool(self._attachments)
        self.setVisible(has_attachments)
        self._table.setVisible(has_attachments and self._expanded)
        self._select_all_button.setVisible(has_attachments and self._expanded)
        self._open_button.setVisible(has_attachments and self._expanded)
        self._save_button.setVisible(has_attachments and self._expanded)
        self._toggle_button.setVisible(has_attachments)
        self._toggle_button.setText(tr("button.collapse") if self._expanded else tr("button.expand"))

        if not has_attachments:
            self.setMaximumHeight(0)
            return

        if not self._expanded:
            self.setMaximumHeight(48)
            return

        row_height = 30
        table_header = 34
        panel_header = 42
        max_visible_rows = min(len(self._attachments), 6)
        self.setMaximumHeight(panel_header + table_header + (max_visible_rows * row_height))

    def _display_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"
