"""Вкладка «Площади цеха» (Раздел 10 дипломного проекта).

Собирает ведомость площадей по принятому оборудованию всех отделений:

  F_полезн = Σ (кол-во единиц × габаритная площадь места),
  F_принят = F_полезн / K_исп   (K_исп = 0.7 — методичка, механиз. участки),

плюс склады (:mod:`core.warehouse`), подсобно-ремонтные и бытовые помещения
(по 15 % от производственной площади). Оборудование берётся из сохранённых
выборов пользователя (``user_data/choices.json``), при отсутствии выбора —
лучший вариант по скорингу каждого отделения.

Расчётное ядро — :func:`core.areas.calc_areas`; вкладка только отображает
результат и реагирует на сигнал ``on_project_changed`` из главного окна.
"""
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea,
)

from config import COLORS
from core.project import Project
from core.areas import AreasResult, calc_areas

#: Стиль групповой панели (тёмная тема, без белого фона — требование UI)
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
    QPushButton:hover {{ background-color: {COLORS['separator']}; }}
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
QTableWidget::item:selected {{
    background-color: {COLORS['separator']};
    color: {COLORS['text_primary']};
}}
"""


def _fmt_m2(value: float) -> str:
    """Отформатировать площадь с разделением разрядов, м²."""
    return f"{value:,.0f}".replace(",", " ") + " м²"


class AreasTab(QWidget):
    """Вкладка ведомости производственных и общецеховых площадей."""

    #: Сигнал о пересчёте площадей (для будущих связок/сводки)
    areas_recalculated = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self._result: Optional[AreasResult] = None
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("📐 Площади цеха")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel(
            "Раздел 10: ведомость площадей по принятому оборудованию "
            "отделений, склады, подсобно-ремонтные и бытовые помещения")
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

        # ── Верхняя панель: база расчёта + кнопка пересчёта ──
        top_box = QGroupBox("База расчёта")
        top_box.setStyleSheet(GROUP_STYLE)
        hbox = QHBoxLayout(top_box)
        hbox.setContentsMargins(12, 12, 12, 12)
        self._basis_lbl = QLabel("—")
        self._basis_lbl.setWordWrap(True)
        self._basis_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-weight: normal;")
        hbox.addWidget(self._basis_lbl, 1)
        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(BTN_STYLE)
        btn_refresh.clicked.connect(self.refresh)
        hbox.addWidget(btn_refresh)
        self._layout.addWidget(top_box)

        # ── Ведомость участков ──
        table_box = QGroupBox("Ведомость площадей производственных участков")
        table_box.setStyleSheet(GROUP_STYLE)
        tv = QVBoxLayout(table_box)
        tv.setContentsMargins(12, 12, 12, 12)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Участок", "Оборудование", "Кол-во, ед.",
             "F полезн., м²", "F принят., м²"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header_v = self._table.horizontalHeader()
        header_v.setSectionResizeMode(0, QHeaderView.Stretch)
        header_v.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3, 4):
            header_v.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._table.setStyleSheet(TABLE_STYLE)
        tv.addWidget(self._table)
        self._layout.addWidget(table_box)

        # ── Итоги по зданию цеха ──
        sum_box = QGroupBox("Итог: здание литейного цеха")
        sum_box.setStyleSheet(GROUP_STYLE)
        sgrid_box = QVBoxLayout(sum_box)
        sgrid_box.setContentsMargins(12, 12, 12, 12)
        sgrid_box.setSpacing(6)
        self._summary_labels: Dict[str, QLabel] = {}
        summary_rows = [
            ("production", "Производственные площади (участки + склады)"),
            ("aux", "Подсобно-ремонтные помещения (15 %)"),
            ("sanitary", "Бытовые помещения (15 %)"),
            ("building", "ОБЩАЯ ПЛОЩАДЬ ЗДАНИЯ ЦЕХА"),
        ]
        for key, title in summary_rows:
            row = QHBoxLayout()
            name_lbl = QLabel(f"{title}:")
            name_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            color = (COLORS['accent'] if key == "building"
                     else COLORS['success'])
            val_lbl.setStyleSheet(f"color: {color};")
            row.addWidget(name_lbl)
            row.addStretch()
            row.addWidget(val_lbl)
            sgrid_box.addLayout(row)
            self._summary_labels[key] = val_lbl
        self._layout.addWidget(sum_box)
        self._layout.addStretch()

    # ─────────────────────── данные/расчёт ───────────────────────
    def refresh(self) -> None:
        """Пересчитать ведомость площадей и обновить интерфейс."""
        try:
            result = calc_areas(self.project)
        except Exception as exc:  # не роняем UI при неполных данных
            self._basis_lbl.setText(
                f"Не удалось рассчитать площади: {exc}. "
                "Заполните исходные данные и оборудование отделений.")
            return
        self._result = result

        n_units = sum(r.units for r in result.rows)
        self._basis_lbl.setText(
            f"По принятому оборудованию {len(result.rows)} участка(ов), "
            f"{n_units} единиц. Принятая площадь = полезная / Kисп (0.7). "
            "Габариты — из справочников; для позиций без размеров взяты "
            "укрупнённые нормы площадей (методичка, раздел 10).")

        self._table.setRowCount(len(result.rows))
        for i, r in enumerate(result.rows):
            cells = [
                r.name,
                r.basis.split(" × ")[0] if r.basis else "",
                str(r.units),
                _fmt_m2(r.footprint_m2),
                _fmt_m2(r.area_m2),
            ]
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j >= 2:
                    item.setTextAlignment(
                        Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, j, item)

        self._summary_labels["production"].setText(
            _fmt_m2(result.production_total_m2)
            + f"  (в т.ч. склады {_fmt_m2(result.warehouse_area_m2)})")
        self._summary_labels["aux"].setText(_fmt_m2(result.aux_repair_m2))
        self._summary_labels["sanitary"].setText(_fmt_m2(result.sanitary_m2))
        self._summary_labels["building"].setText(
            _fmt_m2(result.building_total_m2))

        self.areas_recalculated.emit(result.as_dict())

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных/оборудования."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь representation результата :func:`calc_areas`
            (пустой, если расчёт ещё не выполнялся)
        """
        if self._result is None:
            return {}
        return self._result.as_dict()
