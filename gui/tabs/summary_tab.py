"""Вкладка «Сводка» — итоговая ведомость проекта.

Собирает ``get_summary()`` всех вкладок через
:meth:`MainWindow.department_summaries` (инжектируется главным окном),
показывает ключевые показатели и ведомость принятого оборудования,
а также экспортирует всё в Excel (:func:`core.summary.export_to_excel`).

Пересчёт выполняется по кнопке «Пересчитать», при открытии вкладки и по
сигналам реактивности главного окна. Оформление — в тёмной палитре
приложения, белый фон/текст не используется.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QGridLayout, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QFileDialog,
)

from config import COLORS
from core.project import Project
from core.summary import SummaryResult, build_summary, export_to_excel

GROUP_STYLE = f"""
QGroupBox {{
    background-color: {COLORS['bg_panel']};
    border: 1px solid {COLORS['separator']};
    border-radius: 6px;
    margin-top: 24px;
    padding-top: 16px;
    font-weight: bold;
    color: {COLORS['accent']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
}}
QLabel {{ color: {COLORS['text_primary']}; background: transparent; }}
"""

TABLE_STYLE = f"""
QTableWidget {{
    background-color: {COLORS['bg_main']};
    color: {COLORS['text_primary']};
    gridline-color: {COLORS['separator']};
    border: 1px solid {COLORS['separator']};
}}
QHeaderView::section {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['separator']};
    padding: 4px;
    font-weight: bold;
}}
QTableWidget::item:selected {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['accent']};
}}
"""


class SummaryTab(QWidget):
    """Итоговая сводная ведомость по всем отделениям цеха."""

    #: Эмитируется после каждого пересчёта (для связок/тестов)
    summary_updated = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        #: Функция-поставщик сводок отделений (инжектируется MainWindow:
        #: ``lambda: self.department_summaries()``)
        self.summaries_provider: Optional[Callable[[], Dict[str, Dict]]] = None
        self._result: Optional[SummaryResult] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QLabel("📊 Сводная ведомость")
        header.setObjectName("title")
        subtitle = QLabel("Итоговые результаты расчёта литейного цеха")
        subtitle.setObjectName("subtitle")
        root.addWidget(header)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(14)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ── Ключевые показатели ────────────────────────────────────────
        kpi_box = QGroupBox("Ключевые показатели")
        kpi_box.setStyleSheet(GROUP_STYLE)
        grid = QGridLayout(kpi_box)
        grid.setHorizontalSpacing(24)
        kpi_titles = [
            ("Материал", "material"),
            ("Выпуск годных отливок", "output"),
            ("Металлозавалка", "charge"),
            ("Форм в год", "molds"),
            ("Стержней в год", "cores"),
            ("Численность рабочих", "workers"),
            ("Площадь здания цеха", "area"),
            ("Мостовых кранов", "cranes"),
        ]
        self._kpi_value_labels: Dict[str, QLabel] = {}
        for idx, (title, key) in enumerate(kpi_titles):
            row, col = divmod(idx, 4)
            cap = QLabel(title)
            cap.setStyleSheet(f"color: {COLORS['text_secondary']};")
            val = QLabel("—")
            val.setFont(QFont("Segoe UI", 15, QFont.Bold))
            val.setStyleSheet(f"color: {COLORS['text_primary']};")
            grid.addWidget(cap, row * 2, col)
            grid.addWidget(val, row * 2 + 1, col)
            self._kpi_value_labels[key] = val
        layout.addWidget(kpi_box)

        # ── Ведомость оборудования ─────────────────────────────────────
        park_box = QGroupBox("Принятое оборудование")
        park_box.setStyleSheet(GROUP_STYLE)
        park_layout = QVBoxLayout(park_box)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Отделение", "Оборудование", "Кол-во, шт", "Коэф. загрузки",
             "Примечание"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet(TABLE_STYLE)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        park_layout.addWidget(self.table)
        layout.addWidget(park_box)

        # Годовой баланс потоков между отделениями (без подмены единиц).
        capacity_box = QGroupBox("Баланс мощностей и узкие места")
        capacity_box.setStyleSheet(GROUP_STYLE)
        capacity_layout = QVBoxLayout(capacity_box)
        self.capacity_table = QTableWidget(0, 6)
        self.capacity_table.setHorizontalHeaderLabels([
            "Отделение", "Поток", "Потребность", "Мощность",
            "Оценка", "Основание"])
        self.capacity_table.setStyleSheet(TABLE_STYLE)
        self.capacity_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.capacity_table.verticalHeader().setVisible(False)
        self.capacity_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.capacity_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.Stretch)
        capacity_layout.addWidget(self.capacity_table)
        layout.addWidget(capacity_box)

        # ── Предупреждения ─────────────────────────────────────────────
        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet(
            f"color: {COLORS['warning']}; padding: 6px;")
        self.warn_label.hide()
        layout.addWidget(self.warn_label)

        # ── Кнопки ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        base_btn = (
            f"QPushButton {{ background-color: {COLORS['bg_panel']};"
            f" color: {COLORS['text_primary']}; border: 1px solid"
            f" {COLORS['separator']}; border-radius: 6px; padding: 8px 18px; }}"
            f"QPushButton:hover {{ border-color: {COLORS['accent']}; }}")
        export_btn = (
            f"QPushButton {{ background-color: {COLORS['bg_panel']};"
            f" color: {COLORS['accent']}; font-weight: bold; border: 1px solid"
            f" {COLORS['accent']}; border-radius: 6px; padding: 8px 18px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent']};"
            f" color: {COLORS['bg_main']}; }}")
        self.btn_refresh = QPushButton("🔄 Пересчитать")
        self.btn_refresh.setStyleSheet(base_btn)
        self.btn_export = QPushButton("💾 Экспорт в Excel")
        self.btn_export.setStyleSheet(export_btn)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_export)
        layout.addLayout(btn_row)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Логика
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Пересобрать сводку из вкладок и обновить отображение."""
        summaries: Dict[str, Dict[str, Any]] = {}
        if self.summaries_provider is not None:
            try:
                summaries = self.summaries_provider() or {}
            except Exception:
                summaries = {}
        result = build_summary(summaries, self.project)
        self._result = result
        self._render(result)
        self.summary_updated.emit(result.as_dict())

    def on_project_changed(self) -> None:
        """Слот для сигналов изменения проекта/оборудования."""
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Автопересчёт при открытии вкладки (вкладки уже рассчитаны)."""
        super().showEvent(event)
        if self.summaries_provider is not None:
            self.refresh()

    def _render(self, r: SummaryResult) -> None:
        """Заполнить KPI, таблицу и предупреждения."""
        cat_names = {"steel": "Сталь", "cast_iron": "Чугун",
                     "aluminum": "Алюминий"}
        vals = {
            "material": cat_names.get(r.material_category,
                                      r.material_category or "—"),
            "output": f"{r.annual_output_t:,.0f} т"
                      if r.annual_output_t else "—",
            "charge": f"{r.metal_charge_t:,.0f} т"
                      if r.metal_charge_t else "—",
            "molds": f"{r.annual_molds:,} шт" if r.annual_molds else "—",
            "cores": f"{r.annual_cores:,} шт" if r.annual_cores else "—",
            "workers": f"{r.workforce_total:,} чел."
                       if r.workforce_total else "—",
            "area": f"{r.building_area_m2:,.0f} м²"
                    if r.building_area_m2 else "—",
            "cranes": f"{r.cranes_total} шт" if r.cranes_total else "—",
        }
        for key, text in vals.items():
            self._kpi_value_labels[key].setText(text)

        self.table.setRowCount(len(r.rows))
        for i, row in enumerate(r.rows):
            items = [
                QTableWidgetItem(row.department),
                QTableWidgetItem(row.equipment),
                QTableWidgetItem(str(row.units)),
                QTableWidgetItem(f"{row.load_factor:.2f}"
                                 if row.load_factor else "—"),
                QTableWidgetItem(row.note),
            ]
            for j, it in enumerate(items):
                if j >= 2:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j, it)

        messages = list(r.warnings)
        self.capacity_table.setRowCount(len(r.capacity_rows))
        status_labels = {"ok": "По году достаточно",
                         "deficit": "ДЕФИЦИТ", "unknown": "Не проверено"}
        for i, cap in enumerate(r.capacity_rows):
            demand = cap.get("demand")
            supply = cap.get("capacity")
            unit = str(cap.get("unit", ""))
            values = [
                str(cap.get("department", "")),
                str(cap.get("stream", "")),
                f"{demand:,.1f} {unit}" if demand is not None else "—",
                f"{supply:,.1f} {unit}" if supply is not None else "—",
                status_labels.get(cap.get("status", ""), "Не проверено"),
                str(cap.get("note", "")),
            ]
            for column, value in enumerate(values):
                self.capacity_table.setItem(i, column, QTableWidgetItem(value))
        self.capacity_table.resizeRowsToContents()

        if r.missing_sections:
            messages.append("Разделы без данных: " + ", ".join(r.missing_sections))
        if not r.ready:
            messages.insert(0, "ПРОЕКТ НЕ ГОТОВ: результаты предварительные.")
        if messages:
            self.warn_label.setText("\n".join("⚠ " + m for m in messages))
            self.warn_label.show()
        else:
            self.warn_label.hide()

    # ------------------------------------------------------------------
    # Экспорт
    # ------------------------------------------------------------------
    def _on_export(self) -> None:
        """Сохранить сводку в .xlsx через диалог выбора пути."""
        if self._result is None:
            self.refresh()
        if self._result is None:
            return
        default_name = (self.project.name or "project").strip()
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт сводной ведомости",
            f"{default_name}_сводка.xlsx",
            "Excel файлы (*.xlsx);;Все файлы (*.*)")
        if not path:
            return
        try:
            saved = export_to_excel(self._result, path)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))
            return
        QMessageBox.information(
            self, "Экспорт выполнен",
            f"Сводная ведомость сохранена:\n{saved}")
