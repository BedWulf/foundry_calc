"""Вкладка «Рабочая сила» (Раздел 9).

Считает ведомость численности основных и вспомогательных рабочих цеха
по методике методички/дипломов:

    Чс = n_оборудования · Тд / Тр   (списочная численность)

Данные берутся реактивно из остальных вкладок (через ``get_summary()``):
количество печей, АФЛ, стержневых машин, смесевых установок и очистного
парка. Вспомогательные рабочие — по ремонтным нормативам (рем.ед./т),
плотности оснастки, числу плавок и т. п. Выбор пользователя здесь не
требуется — вкладка расчётно-информационная.
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QGridLayout, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)

from config import COLORS
from core.project import Project
from core.workforce import WorkforceResult, calc_workforce

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
    padding: 0 8px;
}}
"""

BTN_STYLE = f"""
    QPushButton {{
        background-color: {COLORS['bg_panel']};
        color: {COLORS['accent']};
        border: 1px solid {COLORS['accent']};
        border-radius: 4px;
        padding: 6px 14px;
        font-weight: bold;
    }}
    QPushButton:hover {{ background-color: {COLORS['bg_panel']}; }}
"""

TABLE_STYLE = f"""
    QTableWidget {{
        background-color: {COLORS['bg_panel']};
        color: {COLORS['text_primary']};
        gridline-color: {COLORS['separator']};
        border: 1px solid {COLORS['separator']};
    }}
    QHeaderView::section {{
        background-color: {COLORS['bg_main']};
        color: {COLORS['accent']};
        border: 1px solid {COLORS['separator']};
        padding: 6px;
        font-weight: bold;
    }}
    QTableWidget::item {{ padding: 4px; }}
"""


def _fmt_int(value: float) -> str:
    """Отформатировать целое с пробелами-разделителями разрядов."""
    return f"{int(round(value)):,}".replace(",", " ")


class WorkforceTab(QWidget):
    """Вкладка рабочей силы: ведомость основных и вспомогательных рабочих."""

    #: Сигнал о пересчёте численности (для связей со складами/сводкой)
    workforce_changed = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self._result: Optional[WorkforceResult] = None
        self._deps_provider: Optional[Any] = None
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("👷 Рабочая сила")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel(
            "Раздел 9: списочная и явочная численность основных и "
            "вспомогательных рабочих (Чс = n·Тд/Тр)")
        subtitle.setObjectName("subtitle")
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ── Блок «Исходные параметры» ──
        params_box = QGroupBox("Параметры расчёта")
        params_box.setStyleSheet(GROUP_STYLE)
        grid = QGridLayout(params_box)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(24)
        rows = [
            ("output", "Годовая программа, т"),
            ("t_eq", "Действительный фонд оборудования (Тд), ч"),
            ("t_wr", "Действительный фонд рабочего (Тр), ч"),
            ("shifts", "Сменность работы"),
            ("repair", "Объём ремонтных работ, рем.ед./год"),
        ]
        self._param_labels: Dict[str, QLabel] = {}
        for r, (key, title) in enumerate(rows):
            n_lbl = QLabel(f"{title}:")
            n_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            v_lbl = QLabel("—")
            v_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            v_lbl.setStyleSheet(f"color: {COLORS['accent']};")
            grid.addWidget(n_lbl, r, 0)
            grid.addWidget(v_lbl, r, 1)
            self._param_labels[key] = v_lbl

        top_row = QHBoxLayout()
        top_row.addStretch()
        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(BTN_STYLE)
        btn_refresh.clicked.connect(self.refresh)
        top_row.addWidget(btn_refresh)
        grid.addLayout(top_row, len(rows), 1, Qt.AlignRight)
        self._layout.addWidget(params_box)

        # ── Ведомость ──
        table_box = QGroupBox("Ведомость рабочей силы")
        table_box.setStyleSheet(GROUP_STYLE)
        tv = QVBoxLayout(table_box)
        tv.setContentsMargins(12, 12, 12, 12)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Подразделение", "Профессия", "В смену, чел.",
             "Списочно, чел.", "Формула расчёта"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.table.setStyleSheet(TABLE_STYLE)
        tv.addWidget(self.table)
        self._layout.addWidget(table_box, 3)

        # ── Итоги ──
        res_box = QGroupBox("Итоговая численность")
        res_box.setStyleSheet(GROUP_STYLE)
        rgrid = QGridLayout(res_box)
        rgrid.setContentsMargins(12, 12, 12, 12)
        rgrid.setHorizontalSpacing(24)
        self._result_labels: Dict[str, QLabel] = {}
        result_rows = [
            ("main_total", "Основные рабочие (списочно)"),
            ("aux_total", "Вспомогательные рабочие (списочно)"),
            ("total", "ИТОГО списочная численность"),
            ("peak_shift", "Явочная численность в наиб. мног. смену"),
        ]
        for r, (key, title) in enumerate(result_rows):
            n_lbl = QLabel(f"{title}:")
            n_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            v_lbl = QLabel("—")
            v_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
            v_lbl.setStyleSheet(f"color: {COLORS['success']};")
            rgrid.addWidget(n_lbl, r, 0)
            rgrid.addWidget(v_lbl, r, 1)
            self._result_labels[key] = v_lbl
        self._layout.addWidget(res_box)
        self._layout.addStretch()

    # ─────────────────────── данные/расчёт ───────────────────────
    def set_dependencies_provider(self, provider: Any) -> None:
        """Установить источник данных смежных отделений (из MainWindow).

        Args:
            provider: callable, возвращающий dict с ключами ``melting``,
                ``molding``, ``cores``, ``sand_prep``, ``cleaning``,
                ``warehouses`` (словари из ``get_summary()`` вкладок);
                либо сам объект MainWindow с методом ``department_summaries()``
        """
        self._deps_provider = provider
        self.refresh()

    def _collect_dependencies(self) -> Dict[str, Any]:
        """Собрать данные отделений от провайдера (устойчиво к заглушкам)."""
        deps: Dict[str, Any] = {}
        if self._deps_provider is None:
            return deps
        try:
            fn = getattr(self._deps_provider, "department_summaries", None)
            raw = fn() if callable(fn) else self._deps_provider()
            if isinstance(raw, dict):
                deps = raw
        except Exception:
            deps = {}
        return deps

    def refresh(self) -> None:
        """Пересчитать ведомость и обновить таблицу."""
        deps = self._collect_dependencies()
        kwargs: Dict[str, Any] = {}
        for key in ("melting", "molding", "cores", "sand_prep", "cleaning"):
            value = deps.get(key)
            if isinstance(value, dict) and value:
                kwargs[key] = value
        wh = deps.get("warehouses")
        if wh:
            kwargs["warehouses"] = wh
        result = calc_workforce(self.project, **kwargs)
        self._result = result

        self._param_labels["output"].setText(
            f"{_fmt_int(self.project.annual_output_t)} т")
        self._param_labels["t_eq"].setText(f"{result.fund_equipment_h:g} ч")
        self._param_labels["t_wr"].setText(f"{result.fund_workers_h:g} ч")
        self._param_labels["shifts"].setText(f"{result.shifts}")
        self._param_labels["repair"].setText(
            f"{_fmt_int(result.repair_units_total)} рем.ед.")

        rows = result.rows
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = [row.department, row.profession, str(row.per_shift),
                      str(row.total), row.formula]
            for j, text in enumerate(values):
                item = QTableWidgetItem(text)
                if j >= 2:
                    f = QFont("Segoe UI", 10, QFont.Bold)
                    item.setFont(f)
                self.table.setItem(i, j, item)

        self._result_labels["main_total"].setText(f"{result.main_total} чел.")
        self._result_labels["aux_total"].setText(f"{result.aux_total} чел.")
        self._result_labels["total"].setText(f"{result.total} чел.")
        self._result_labels["peak_shift"].setText(
            f"{result.peak_shift} чел.")
        if not result.complete:
            for lbl in self._result_labels.values():
                lbl.setText("— (расчёт заблокирован)")
            self._param_labels["output"].setText(
                "⚠ Невыполнима формовочная программа; численность не подтверждена")
        self.workforce_changed.emit(result.as_dict())

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных (слот сигнала)."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь с полями результата ``WorkforceResult.as_dict()``
        """
        if self._result is None:
            return {}
        return self._result.as_dict()
