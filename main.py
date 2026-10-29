"""Точка входа в приложение «ЛитейныйЦех PRO»."""
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path (на случай запуска из подпапки)
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from config import APP_ICON, APP_NAME
from gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))

    window = MainWindow()
    import os
    if os.environ.get("FOUNDRY_SMOKE_TEST") == "1":
        # Headless CI validates bundled imports and full widget construction.
        # Showing a top-level Qt window without an interactive Windows desktop
        # can block indefinitely; real visual launch needs a desktop smoke test.
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())