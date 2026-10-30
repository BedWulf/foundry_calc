"""An offline manual check: export a diploma ledger, then import it."""
import os
from pathlib import Path
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from config import EXAMPLES_DIR
from core.casting_item import CastingItem
from gui.main_window import MainWindow
from import_export.excel_importer import ExcelImporter


@pytest.mark.parametrize("number,expected_molds", [(1, 1368325), (2, 768159)])
def test_help_exports_real_diploma_without_replacing_user_data(
    tmp_path, monkeypatch, number, expected_molds
):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    original = CastingItem(name="Рабочая номенклатура", molds_per_year=9)
    window.project.castings = [original]
    path = tmp_path / f"Ведомость_диплома_{number}.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args, **kw: (str(path), "Excel (*.xlsx)"))
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args, **kw: QMessageBox.Ok)
    help_tab = window.tabs["help_tab"]
    if number == 1:
        help_tab.diploma1_button.click()
    else:
        help_tab.diploma2_button.click()

    source = EXAMPLES_DIR / f"Диплом_{number}_ведомость_формовки.xlsx"
    assert source.is_file()
    assert path.read_bytes() == source.read_bytes()
    imported = ExcelImporter(path).parse()
    assert len(imported) == 20
    assert sum(c.molds_per_year for c in imported) == expected_molds
    assert window.project.castings == [original]
    window.close()
