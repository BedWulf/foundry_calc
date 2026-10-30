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


def main() -> int:
    if os.environ.get("FOUNDRY_SMOKE_TEST") == "1":
        # Standard-library-only resource test, before importing PySide6.
        # Frozen builds store data next to the executable in _internal.
        from config import DATA_DIR, DOCS_DIR, EXAMPLES_DIR
        if not (DATA_DIR / "equipment" / "molding_lines.json").is_file():
            return 21
        if not (DOCS_DIR / "USER_MANUAL.md").is_file():
            return 22
        if any(
            not (EXAMPLES_DIR / f"Диплом_{n}_ведомость_формовки.xlsx").is_file()
            for n in (1, 2)
        ):
            return 23
        return 0

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from config import APP_ICON, APP_NAME
    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
