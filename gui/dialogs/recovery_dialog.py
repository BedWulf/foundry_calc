"""Явный выбор аварийной копии без автоматической порчи текущего проекта."""
from __future__ import annotations

from datetime import timezone
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QMessageBox,
)

from core.recovery import RecoveryEntry


class RecoveryDialog(QDialog):
    """Choose one snapshot. Recovery and deletion require user action."""

    def __init__(self, entries: list[RecoveryEntry], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Восстановление несохранённой работы")
        self.setMinimumSize(700, 420)
        self.resize(900, 520)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.selected_entry: RecoveryEntry | None = None
        self.delete_entry: RecoveryEntry | None = None

        root = QVBoxLayout(self)
        title = QLabel(
            "Найдены резервные копии несохранённой работы. "
            "Обычные файлы проектов не изменены.")
        title.setWordWrap(True)
        root.addWidget(title)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setMinimumHeight(250)
        for entry in entries:
            local = entry.saved_at.astimezone().strftime("%d.%m.%Y %H:%M")
            source = (str(entry.original_path)
                      if entry.original_path is not None
                      else "Проект ещё не сохранялся вручную")
            item = QListWidgetItem(
                f"{entry.project_name}  |  {local}\n"
                f"{entry.castings_count} отливок  |  {source}")
            item.setData(Qt.UserRole, entry)
            item.setSizeHint(item.sizeHint().expandedTo(
                item.sizeHint().__class__(0, 53)))
            self.list.addItem(item)
        if entries:
            self.list.setCurrentRow(0)
        root.addWidget(self.list, 1)

        hint = QLabel(
            "«Восстановить» откроет выбранную копию и не перезапишет "
            "основной файл. «Позже» сохранит копии. "
            "Удаление требует подтверждения.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QHBoxLayout()
        self.restore_button = QPushButton("Восстановить")
        self.later_button = QPushButton("Позже")
        self.remove_button = QPushButton("Удалить выбранную копию…")
        self.restore_button.clicked.connect(self._restore)
        self.later_button.clicked.connect(self.reject)
        self.remove_button.clicked.connect(self._remove)
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        buttons.addWidget(self.later_button)
        root.addLayout(buttons)

    def _current(self) -> RecoveryEntry | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _restore(self) -> None:
        entry = self._current()
        if entry is not None:
            self.selected_entry = entry
            self.accept()

    def _remove(self) -> None:
        entry = self._current()
        if entry is None:
            return
        confirm = QMessageBox.question(
            self,
            "Удалить аварийную копию?",
            f"Удалить резервную копию проекта «{entry.project_name}»?\n"
            "Исходный файл проекта останется нетронутым.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.delete_entry = entry
            self.done(2)
