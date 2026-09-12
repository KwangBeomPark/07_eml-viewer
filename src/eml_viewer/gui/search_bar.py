from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from eml_viewer.gui.i18n import tr


class SearchBarWidget(QWidget):
    """본문 내 텍스트 검색을 위한 인라인 검색 바 위젯입니다."""

    # text, forward, case_sensitive
    search_requested = Signal(str, bool, bool)
    search_cleared = Signal()
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchBarWidget")

        self._search_input = QLineEdit(self)
        self._search_input.setClearButtonEnabled(True)

        self._prev_button = QPushButton("◀", self)
        self._next_button = QPushButton("▶", self)
        self._case_check = QCheckBox(self)
        self._count_label = QLabel(self)
        self._close_button = QPushButton("✕", self)

        self._prev_button.setFixedWidth(32)
        self._next_button.setFixedWidth(32)
        self._close_button.setFixedWidth(28)
        self._close_button.setFlat(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        layout.addWidget(self._search_input)
        layout.addWidget(self._prev_button)
        layout.addWidget(self._next_button)
        layout.addWidget(self._case_check)
        layout.addWidget(self._count_label)
        layout.addWidget(self._close_button)

        self._search_input.textChanged.connect(self._on_text_changed)
        self._search_input.returnPressed.connect(self._on_find_next)
        self._prev_button.clicked.connect(self._on_find_prev)
        self._next_button.clicked.connect(self._on_find_next)
        self._case_check.toggled.connect(lambda _: self._on_find_current())
        self._close_button.clicked.connect(self.close_search)

        # Esc 키 단축키
        self._esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._esc_shortcut.activated.connect(self.close_search)

        self.retranslate_ui()
        self.hide()

    def retranslate_ui(self) -> None:
        self._search_input.setPlaceholderText(tr("find.placeholder"))
        self._prev_button.setToolTip(tr("find.previous") + " (Shift+F3)")
        self._next_button.setToolTip(tr("find.next") + " (F3 / Enter)")
        self._case_check.setText(tr("find.case_sensitive"))
        self._close_button.setToolTip(tr("find.close") + " (Esc)")

    def show_and_focus(self) -> None:
        self.show()
        self._search_input.setFocus()
        self._search_input.selectAll()
        if self._search_input.text():
            self._on_find_current()

    def query(self) -> str:
        return self._search_input.text()

    def is_case_sensitive(self) -> bool:
        return self._case_check.isChecked()

    def is_open(self) -> bool:
        return not self.isHidden()

    def find_next(self) -> None:
        self._on_find_next()

    def find_previous(self) -> None:
        self._on_find_prev()

    def close_search(self) -> None:
        self.hide()
        self.search_cleared.emit()
        self.closed.emit()

    def set_match_status(self, current: int, total: int) -> None:
        if not self._search_input.text():
            self._count_label.setText("")
        elif total <= 0:
            self._count_label.setText(tr("find.no_matches"))
        else:
            self._count_label.setText(tr("find.matches_count", current=current, total=total))

    def _on_text_changed(self, text: str) -> None:
        if not text:
            self._count_label.setText("")
            self.search_cleared.emit()
            return
        self.search_requested.emit(text, True, self._case_check.isChecked())

    def _on_find_next(self) -> None:
        text = self._search_input.text()
        if text:
            self.search_requested.emit(text, True, self._case_check.isChecked())

    def _on_find_prev(self) -> None:
        text = self._search_input.text()
        if text:
            self.search_requested.emit(text, False, self._case_check.isChecked())

    def _on_find_current(self) -> None:
        text = self._search_input.text()
        if text:
            self.search_requested.emit(text, True, self._case_check.isChecked())

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._on_find_prev()
            else:
                self._on_find_next()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close_search()
            event.accept()
            return
        super().keyPressEvent(event)
