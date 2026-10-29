"""Встроенное пошаговое руководство для первого запуска программы."""
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextBrowser, QLineEdit, QPushButton,
)

from config import DOCS_DIR, COLORS


class HelpTab(QWidget):
    """Руководство живёт внутри приложения и доступно без интернета."""

    tutorial_requested = Signal()
    example_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        title = QLabel("❓ Руководство пользователя")
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(
            "Пошаговое заполнение программы, Excel, формовочные линии и проверка результатов")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)
        tutorial_tools = QHBoxLayout()
        self.start_tutorial_button = QPushButton("▶ Начать обучение по программе")
        self.start_tutorial_button.setToolTip(
            "Экскурсия проходит по настоящим вкладкам и не изменяет проект")
        self.start_tutorial_button.clicked.connect(self.tutorial_requested.emit)
        self.save_example_button = QPushButton("Сохранить учебный Excel")
        self.save_example_button.setToolTip(
            "Создать пример из двух отливок, не импортируя его в рабочий проект")
        self.save_example_button.clicked.connect(self.example_requested.emit)
        tutorial_tools.addWidget(self.start_tutorial_button)
        tutorial_tools.addWidget(self.save_example_button)
        root.addLayout(tutorial_tools)

        tools = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Найти в руководстве (например: опока, брак)")
        self.search_button = QPushButton("Найти")
        self.top_button = QPushButton("В начало")
        tools.addWidget(self.search_edit, 1)
        tools.addWidget(self.search_button)
        tools.addWidget(self.top_button)
        root.addLayout(tools)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(
            f"QTextBrowser {{ background: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['separator']}; padding: 12px; }}")
        root.addWidget(self.browser, 1)

        manual_file = Path(DOCS_DIR) / "USER_MANUAL.md"
        if manual_file.is_file():
            self.browser.setMarkdown(manual_file.read_text(encoding="utf-8"))
        else:
            self.browser.setPlainText(
                "Руководство не найдено в комплекте программы. "
                "Проверьте папку docs/USER_MANUAL.md и состав Windows-сборки.")
        self.search_edit.returnPressed.connect(self.find_next)
        self.search_button.clicked.connect(self.find_next)
        self.top_button.clicked.connect(self.scroll_to_top)

    def find_next(self) -> None:
        term = self.search_edit.text().strip()
        if not term:
            return
        if not self.browser.find(term):
            cursor = self.browser.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.browser.setTextCursor(cursor)
            self.browser.find(term)

    def scroll_to_top(self) -> None:
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.browser.setTextCursor(cursor)
