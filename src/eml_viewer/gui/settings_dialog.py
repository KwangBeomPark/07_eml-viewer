from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from eml_viewer.gui.i18n import tr
from eml_viewer.app_identity import user_data_dir
from eml_viewer.models.app_settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
        *,
        settings_directory: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))

        self._language_combo = QComboBox(self)
        self._language_combo.addItem(tr("language.ko"), "ko")
        self._language_combo.addItem(tr("language.en"), "en")
        self._set_combo_value(self._language_combo, settings.language)

        self._theme_combo = QComboBox(self)
        self._theme_combo.addItem(tr("theme.system"), "system")
        self._theme_combo.addItem(tr("theme.light"), "light")
        self._theme_combo.addItem(tr("theme.dark"), "dark")
        self._set_combo_value(self._theme_combo, settings.theme)

        self._auto_load_remote_images_check = QCheckBox(
            tr("settings.auto_load_remote_images"), self
        )
        self._auto_load_remote_images_check.setChecked(settings.auto_load_remote_images)

        self._startup_with_windows_check = QCheckBox(
            tr("settings.startup_with_windows"), self
        )
        self._startup_with_windows_check.setChecked(settings.startup_with_windows)

        self._minimize_to_tray_check = QCheckBox(
            tr("settings.minimize_to_tray_on_close"), self
        )
        self._minimize_to_tray_check.setChecked(settings.minimize_to_tray_on_close)

        self._smtp_host_edit = QLineEdit(settings.smtp_host, self)
        self._smtp_host_edit.setPlaceholderText("smtp.example.com")

        self._smtp_sender_edit = QLineEdit(settings.smtp_sender, self)
        self._smtp_sender_edit.setPlaceholderText("sender@example.com")

        self._smtp_port_spin = QSpinBox(self)
        self._smtp_port_spin.setRange(1, 65535)
        self._smtp_port_spin.setValue(settings.smtp_port)

        general_layout = QFormLayout()
        general_layout.addRow(tr("settings.language"), self._language_combo)
        general_layout.addRow(tr("settings.theme"), self._theme_combo)
        general_layout.addRow("", self._auto_load_remote_images_check)
        general_layout.addRow("", self._startup_with_windows_check)
        general_layout.addRow("", self._minimize_to_tray_check)

        smtp_group = QGroupBox(tr("settings.smtp_group"), self)
        smtp_layout = QFormLayout(smtp_group)
        smtp_layout.addRow(tr("settings.smtp_host"), self._smtp_host_edit)
        smtp_layout.addRow(tr("settings.smtp_sender"), self._smtp_sender_edit)
        smtp_layout.addRow(tr("settings.smtp_port"), self._smtp_port_spin)

        storage_group = QGroupBox(tr("settings.storage_group"), self)
        storage_layout = QVBoxLayout(storage_group)
        self._settings_location_label = QLabel(
            str(settings_directory or user_data_dir()), self
        )
        self._settings_location_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._settings_location_label.setWordWrap(True)
        storage_layout.addWidget(self._settings_location_label)
        backup_hint = QLabel(tr("settings.backup_scope"), self)
        backup_hint.setWordWrap(True)
        storage_layout.addWidget(backup_hint)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("settings.ok"))
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("settings.cancel")
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(general_layout)
        layout.addWidget(smtp_group)
        layout.addWidget(storage_group)
        layout.addWidget(button_box)

    @property
    def language(self) -> str:
        return str(self._language_combo.currentData())

    @property
    def theme(self) -> str:
        return str(self._theme_combo.currentData())

    @property
    def auto_load_remote_images(self) -> bool:
        return self._auto_load_remote_images_check.isChecked()

    @property
    def startup_with_windows(self) -> bool:
        return self._startup_with_windows_check.isChecked()

    @property
    def minimize_to_tray_on_close(self) -> bool:
        return self._minimize_to_tray_check.isChecked()

    @property
    def smtp_host(self) -> str:
        return self._smtp_host_edit.text().strip()

    @property
    def smtp_sender(self) -> str:
        return self._smtp_sender_edit.text().strip()

    @property
    def smtp_port(self) -> int:
        return int(self._smtp_port_spin.value())

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
