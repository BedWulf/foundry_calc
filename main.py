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
    window.show()
    # CI-only check of the packaged executable (real Qt startup).
    import os
    if os.environ.get("FOUNDRY_SMOKE_TEST") == "1":
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1000, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())