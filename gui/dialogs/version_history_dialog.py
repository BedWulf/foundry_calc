"""A large, dark-theme-compatible picker for previously saved project versions."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton,
)

from core.version_history import VersionEntry


class VersionHistoryDialog(QDialog):
    """Opens a selected saved version as an unsaved copy, never overwrites."""

    def __init__(self, entries: list[VersionEntry], parent=None):
        super().__init__(parent)
        self.setWindowTitle("История версий проекта")
        self.setMinimumSize(700, 420)
        self.resize(920, 540)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.selected_entry: VersionEntry | None = None

        root = QVBoxLayout(self)
        title = QLabel(
            "Предыдущие сохранённые версии выбранного файла проекта. "
            "Это не аварийные копии автосохранения.")
        title.setWordWrap(True)
        root.addWidget(title)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        for entry in entries:
            when = entry.saved_at.astimezone().strftime("%d.%m.%Y %H:%M:%S")
            item = QListWidgetItem(
                f"{when}  |  {entry.project_name}\n"
                f"{entry.castings_count} отливок")
            item.setData(Qt.UserRole, entry)
            item.setSizeHint(QSize(0, 56))
            self.list.addItem(item)
        if entries:
            self.list.setCurrentRow(0)
        root.addWidget(self.list, 1)

        hint = QLabel(
            "Выбранная версия откроется как НЕСОХРАНЁННАЯ КОПИЯ. "
            "Исходный файл останется без изменений. Для фиксации "
            "восстановленной версии используйте «Сохранить как…».")
        hint.setWordWrap(True)
        root.addWidget(hint)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Открыть копию версии")
        self.cancel_button = QPushButton("Отмена")
        self.open_button.clicked.connect(self._choose)
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.open_button)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

    def _choose(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.selected_entry = item.data(Qt.UserRole)
            self.accept()
