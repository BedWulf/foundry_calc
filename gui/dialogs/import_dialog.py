# -*- coding: utf-8 -*-
"""
import_dialog.py
================
Диалог импорта номенклатуры отливок из Excel-файла.

Сценарий использования:
    1. Пользователь нажимает «Импорт из Excel» в главном меню
    2. Открывается диалог → выбирает файл
    3. Файл парсится → данные показываются в QTableWidget (предпросмотр)
    4. Пользователь видит предупреждения (если есть)
    5. Нажимает «Импортировать» → данные загружаются в project
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QGroupBox,
    QMessageBox,
    QWidget,
)

from import_export.excel_importer import (
    ExcelImporter,
    ImportPreview,
    ImportError_,
    FileNotExistsError,
    InvalidFormatError,
    EmptyDataError,
)

logger = logging.getLogger(__name__)


class ImportDialog(QDialog):
    """
    Диалог импорта номенклатуры из Excel.

    Сигналы:
        import_completed(ImportPreview) — эмитится при успешном подтверждении
    """

    import_completed = Signal(object)  # ImportPreview

    # Цвета в стиле «Раскалённый горн»
    STYLE = """
        QDialog {
            background-color: #151C26;
            color: #E8EEF6;
        }
        QLabel {
            color: #E8EEF6;
            font-size: 13px;
        }
        QLabel#title {
            font-size: 18px;
            font-weight: bold;
            color: #E8A66F;
        }
        QLabel#summary {
            color: #B8C5D4;
            font-size: 12px;
        }
        QGroupBox {
            border: 1px solid #45566B;
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 16px;
            color: #E8EEF6;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
        }
        QTableWidget {
            background-color: #202A38;
            alternate-background-color: #111A25;
            color: #E8EEF6;
            gridline-color: #45566B;
            border: 1px solid #45566B;
            border-radius: 4px;
            font-size: 12px;
        }
        QTableWidget::item {
            padding: 4px;
        }
        QHeaderView::section {
            background-color: #293649;
            color: #E8A66F;
            padding: 6px;
            border: 1px solid #45566B;
            font-weight: bold;
        }
        QTextEdit {
            background-color: #111A25;
            color: #E8A66F;
            border: 1px solid #45566B;
            border-radius: 4px;
            font-size: 11px;
        }
        QPushButton {
            background-color: #E8A66F;
            color: #17202D;
            border: none;
            border-radius: 4px;
            padding: 8px 20px;
            font-weight: bold;
            font-size: 13px;
            min-width: 120px;
        }
        QPushButton:hover {
            background-color: #F3B989;
        }
        QPushButton:pressed {
            background-color: #C88858;
        }
        QPushButton:disabled {
            background-color: #344255;
            color: #91A0B3;
        }
        QPushButton#secondary {
            background-color: #202A38;
            border: 1px solid #45566B;
            color: #E8EEF6;
        }
        QPushButton#secondary:hover {
            background-color: #293649;
        }
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(self.STYLE)
        self.setWindowTitle("📥 Импорт номенклатуры отливок")
        self.setMinimumSize(780, 520)
        self.resize(1480, 860)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)

        self._importer = ExcelImporter()
        self._preview: Optional[ImportPreview] = None
        self._file_path: Optional[Path] = None

        self._init_ui()

    # ------------------------------------------------------------------
    # Инициализация UI
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Заголовок ---
        title = QLabel("📥 Импорт номенклатуры из Excel")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # --- Блок выбора файла ---
        file_group = QGroupBox("1. Выберите файл")
        file_layout = QHBoxLayout(file_group)

        self._file_label = QLabel("Файл не выбран")
        self._file_label.setObjectName("summary")
        file_layout.addWidget(self._file_label, 1)

        self._btn_browse = QPushButton("📂 Выбрать файл...")
        self._btn_browse.setObjectName("secondary")
        self._btn_browse.clicked.connect(self._on_browse)
        file_layout.addWidget(self._btn_browse)

        layout.addWidget(file_group)

        # --- Таблица предпросмотра ---
        preview_group = QGroupBox("2. Предпросмотр данных")
        preview_layout = QVBoxLayout(preview_group)

        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._table.verticalHeader().setDefaultSectionSize(26)
        preview_layout.addWidget(self._table)

        # --- Сводка ---
        self._summary_label = QLabel(
            "Позиций: 0  |  Форм/год: 0  |  Металл: 0 т"
        )
        self._summary_label.setObjectName("summary")
        preview_layout.addWidget(self._summary_label)

        layout.addWidget(preview_group, 1)  # stretch=1 → занимает всё свободное

        # --- Блок предупреждений ---
        self._warnings_group = QGroupBox("⚠️ Предупреждения")
        warnings_layout = QVBoxLayout(self._warnings_group)
        self._warnings_text = QTextEdit()
        self._warnings_text.setReadOnly(True)
        self._warnings_text.setMaximumHeight(100)
        warnings_layout.addWidget(self._warnings_text)
        self._warnings_group.setVisible(False)
        layout.addWidget(self._warnings_group)

        # --- Кнопки управления ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_cancel = QPushButton("Отмена")
        self._btn_cancel.setObjectName("secondary")
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_import = QPushButton("✅ Импортировать")
        self._btn_import.setEnabled(False)
        self._btn_import.clicked.connect(self._on_import)
        btn_layout.addWidget(self._btn_import)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Слоты
    # ------------------------------------------------------------------
    def _on_browse(self) -> None:
        """Открывает диалог выбора файла и загружает предпросмотр."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл номенклатуры",
            "",
            "Excel файлы (*.xlsx *.xlsm);;Все файлы (*.*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not file_path:
            return

        self._load_file(Path(file_path))

    def _load_file(self, file_path: Path) -> None:
        """Загружает файл и заполняет предпросмотр."""
        self._file_path = file_path
        self._file_label.setText(f"📄 {file_path.name}")

        try:
            self._preview = self._importer.load_preview(file_path)
        except FileNotExistsError as e:
            self._show_error("Файл не найден", str(e))
            return
        except InvalidFormatError as e:
            self._show_error("Неверный формат", str(e))
            return
        except EmptyDataError as e:
            self._show_error("Пустые данные", str(e))
            return
        except ImportError_ as e:
            self._show_error("Ошибка импорта", str(e))
            return
        except Exception as e:
            logger.exception("Непредвиденная ошибка при импорте")
            self._show_error("Непредвиденная ошибка", f"{type(e).__name__}: {e}")
            return

        self._fill_table()
        self._fill_warnings()
        self._update_summary()
        self._btn_import.setEnabled(True)

    def _fill_table(self) -> None:
        """Заполняет таблицу предпросмотра."""
        if not self._preview:
            return

        headers = self._preview.headers
        rows = self._preview.rows

        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(rows))

        for r, row_data in enumerate(rows):
            for c, value in enumerate(row_data):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)

                # Подсветка числовых колонок
                if c in (2, 4, 7, 8, 9, 10, 11, 12, 13):
                    item.setForeground(QColor("#E8A66F"))

                self._table.setItem(r, c, item)

        # Автоподбор ширины колонок
        self._table.resizeColumnsToContents()

    def _fill_warnings(self) -> None:
        """Заполняет блок предупреждений."""
        if not self._preview or not self._preview.warnings:
            self._warnings_group.setVisible(False)
            return

        self._warnings_group.setVisible(True)
        self._warnings_text.clear()
        for w in self._preview.warnings:
            self._warnings_text.append(f"• {w}")

    def _update_summary(self) -> None:
        """Обновляет сводку под таблицей."""
        if not self._preview:
            return

        p = self._preview
        self._summary_label.setText(
            f"✅ Позиций: <b>{p.total_castings}</b>  |  "
            f"Форм/год: <b>{p.total_forms_per_year:,}</b>  |  "
            f"Металл: <b>{p.total_metal_tons:,.1f} т</b>"
        )

    def _on_import(self) -> None:
        """Подтверждение импорта."""
        if not self._preview:
            return

        # Если есть предупреждения — спрашиваем подтверждение
        if self._preview.warnings:
            reply = QMessageBox.question(
                self,
                "Предупреждения при импорте",
                f"Обнаружено {len(self._preview.warnings)} предупреждений.\n"
                "Проблемные строки будут пропущены.\n\n"
                "Продолжить импорт?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

        # Эмитим сигнал с готовыми данными
        self.import_completed.emit(self._preview)
        self.accept()

    def _show_error(self, title: str, message: str) -> None:
        """Показывает сообщение об ошибке."""
        self._preview = None
        self._btn_import.setEnabled(False)
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._summary_label.setText("❌ Ошибка загрузки")
        self._warnings_group.setVisible(False)

        QMessageBox.critical(self, title, message)


# ------------------------------------------------------------------
# Точка входа для тестирования
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dlg = ImportDialog()
    dlg.show()
    sys.exit(app.exec())