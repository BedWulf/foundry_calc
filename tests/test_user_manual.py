"""The built-in help must work offline on the first screen."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from config import DOCS_DIR
from gui.main_window import MainWindow


def test_manual_is_packaged_source_and_available_without_internet():
    content = (DOCS_DIR / "USER_MANUAL.md").read_text(encoding="utf-8")
    for word in ("Исходные данные", "Годовой выпуск", "Отливок в год",
                 "отливок/форму", "Сводка", "ДЕФИЦИТ", "Excel"):
        assert word.lower() in content.lower()


def test_project_help_button_opens_manual_section():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    project_tab = window.tabs["project_tab"]
    help_tab = window.tabs["help_tab"]
    assert "Годовой выпуск" in help_tab.browser.toPlainText()
    project_tab.help_requested.emit()
    assert window.content_stack.currentWidget() is help_tab
    help_tab.search_edit.setText("Формовочное")
    help_tab.find_next()
    window.close()
