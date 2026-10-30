"""Точка входа в приложение «ЛитейныйЦех PRO».

Import GUI modules lazily: smoke mode on headless Windows CI should not
initialize Qt before it has verified bundled resources.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



def _smoke_test_frozen() -> int:
    """Check ACTUAL packaged Qt imports and window creation, without showing UI.

    Unlike checking files on disk, this triggers importing all tabs, including
    the melting package. It therefore catches missing frozen Python modules.
    """
    import traceback

    try:
        from config import DATA_DIR, DOCS_DIR, EXAMPLES_DIR, APP_NAME
        for resource, code in (
            (DATA_DIR / "equipment" / "molding_lines.json", 21),
            (DOCS_DIR / "USER_MANUAL.md", 22),
            (EXAMPLES_DIR / "Диплом_1_ведомость_формовки.xlsx", 23),
            (EXAMPLES_DIR / "Диплом_2_ведомость_формовки.xlsx", 24),
        ):
            if not resource.is_file():
                raise FileNotFoundError(f"Missing resource ({code}): {resource}")

        # Imports must occur inside the packaged executable. A test against
        # development Python would not catch frozen-module path assumptions.
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow
        from core.melting import calc_metal_charge

        assert calc_metal_charge(37000, 7.2, 44.1, 5.0) > 58000
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        window = MainWindow()
        assert "melting_tab" in window.tabs
        assert "molding_tab" in window.tabs
        assert "help_tab" in window.tabs
        window.close()
        return 0
    except BaseException:
        report = os.environ.get("FOUNDRY_SMOKE_REPORT")
        if report:
            try:
                Path(report).write_text(traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass
        return 91


def main() -> int:
    if os.environ.get("FOUNDRY_SMOKE_TEST") == "1":
        return _smoke_test_frozen()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from config import APP_ICON, APP_NAME
    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))

    window = MainWindow()
    window.showMaximized()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
