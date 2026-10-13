"""Вкладка «Транспорт» (Раздел 12 дипломного проекта).

Показывает расчёт внутрицехового транспорта: мостовые краны (нормы
длины участка), транспортные ковши (формула К = П·Тц/(Т·n) с ремонтом
и резервом), конвейерные трассы и пневмотранспорт.

Два интерактивных выбора пользователя (сохраняются в
``user_data/choices.json``, категория ``transport_units``):

  • **Ковш** — карточки справочника ``transport.json`` (категория
    ``ladle``): ёмкость и цикл работы влияют на парк ковшей;
  • **Мостовой кран** — карточки категории ``crane``: модель и
    площадь группы крана влияют на ведомость.

Расчётное ядро — :func:`core.transport.calc_transport`; вкладка только
отображает результат и реагирует на сигнал ``on_project_changed`` из
главного окна. Все стили — тёмная тема, без белого фона.
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QButtonGroup, QRadioButton,
)

from config import COLORS
from core.project import Project
from core.transport import (
    TransportResult, calc_transport, load_transport_catalog,
)
from core.user_choices import UserChoices
from gui.widgets.equipment_picker import EquipmentCard, EquipmentPicker

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

LABEL_STYLE = f"color: {COLORS['text_secondary']}; font-weight: normal;"


def _fmt_int(value: float) -> str:
    """Отформатировать целое с разделением разрядов."""
    return f"{int(round(value)):,}".replace(",", " ")


def _fmt_m2(value: float) -> str:
    """Отформатировать площадь, м²."""
    return f"{value:,.0f}".replace(",", " ") + " м²"


class TransportTab(QWidget):
    """Вкладка расчёта внутрицехового транспорта цеха."""

    #: Сигнал о смене выбора транспортного оборудования (для связок/сводки)
    equipment_choice_changed = Signal(dict)
    #: Сигнал о завершении пересчёта (для будущей сводки)
    transport_recalculated = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self.choices = UserChoices()
        self._result: Optional[TransportResult] = None
        #: Флаг «идёт программное обновление»: подавляет реактивный
        #: пересчёт в _on_choice, иначе set_equipment_options → сигнал
        #: equipment_selected → refresh() даёт бесконечную рекурсию.
        self._updating: bool = False
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("🚛 Внутрицеховой транспорт")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel(
            "Раздел 12: мостовые краны по нормам длины участков, "
            "транспортные ковши по циклу заливки, конвейеры и "
            "пневмотранспорт")
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
        self._basis_lbl.setStyleSheet(LABEL_STYLE)
        hbox.addWidget(self._basis_lbl, 1)
        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(BTN_STYLE)
        btn_refresh.clicked.connect(self.refresh)
        hbox.addWidget(btn_refresh)
        self._layout.addWidget(top_box)

        # ── Выбор ковша (карточки с радио-кнопками) ──
        ladle_box = QGroupBox("Транспортные ковши: выбор модели")
        ladle_box.setStyleSheet(GROUP_STYLE)
        lv = QVBoxLayout(ladle_box)
        lv.setContentsMargins(12, 12, 12, 12)
        self.ladle_formula_lbl = QLabel("—")
        self.ladle_formula_lbl.setWordWrap(True)
        self.ladle_formula_lbl.setStyleSheet(
            f"color: {COLORS['success']}; font-weight: bold;")
        lv.addWidget(self.ladle_formula_lbl)
        self.ladle_cards_host = QWidget()
        self.ladle_cards_layout = QHBoxLayout(self.ladle_cards_host)
        self.ladle_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.ladle_cards_layout.setSpacing(10)
        self._ladle_group = None
        lv.addWidget(self.ladle_cards_host)
        self._layout.addWidget(ladle_box)

        # ── Выбор мостового крана ──
        crane_box = QGroupBox("Мостовые краны: выбор модели")
        crane_box.setStyleSheet(GROUP_STYLE)
        cv = QVBoxLayout(crane_box)
        cv.setContentsMargins(12, 12, 12, 12)
        self.crane_note_lbl = QLabel("—")
        self.crane_note_lbl.setWordWrap(True)
        self.crane_note_lbl.setStyleSheet(LABEL_STYLE)
        cv.addWidget(self.crane_note_lbl)
        self.crane_cards_host = QWidget()
        self.crane_cards_layout = QHBoxLayout(self.crane_cards_host)
        self.crane_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.crane_cards_layout.setSpacing(10)
        self._crane_group = None
        cv.addWidget(self.crane_cards_host)
        self._layout.addWidget(crane_box)

        # ── Ведомость транспорта ──
        table_box = QGroupBox("Ведомость транспортного оборудования")
        table_box.setStyleSheet(GROUP_STYLE)
        tv = QVBoxLayout(table_box)
        tv.setContentsMargins(12, 12, 12, 12)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Позиция", "Модель", "Кол-во", "Обоснование", "Отделение"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        for col in (0, 1, 2, 4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._table.setStyleSheet(TABLE_STYLE)
        tv.addWidget(self._table)
        self._layout.addWidget(table_box)

        # ── Итоги ──
        sum_box = QGroupBox("Итог по транспорту")
        sum_box.setStyleSheet(GROUP_STYLE)
        sv = QVBoxLayout(sum_box)
        sv.setContentsMargins(12, 12, 12, 12)
        sv.setSpacing(6)
        self._summary_labels: Dict[str, QLabel] = {}
        summary_rows = [
            ("cranes", "Мостовые краны, всего шт."),
            ("ladles", "Парк транспортных ковшей (раб./ремонт/резерв)"),
            ("area", "Транспортные площади (группы кранов, трассы)"),
        ]
        for key, title in summary_rows:
            row = QHBoxLayout()
            name_lbl = QLabel(f"{title}:")
            name_lbl.setStyleSheet(LABEL_STYLE)
            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            val_lbl.setStyleSheet(
                f"color: {COLORS['accent'] if key == 'area' else COLORS['success']};")
            row.addWidget(name_lbl)
            row.addStretch()
            row.addWidget(val_lbl)
            sv.addLayout(row)
            self._summary_labels[key] = val_lbl
        self._notes_lbl = QLabel("")
        self._notes_lbl.setWordWrap(True)
        self._notes_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-style: italic;")
        sv.addWidget(self._notes_lbl)
        self._layout.addWidget(sum_box)
        self._layout.addStretch()

    # ──────────────────── карточки для picker'ов ────────────────────
    def _ladle_options(self, liquid_t: float) -> List[Dict[str, Any]]:
        """Построить карточки ковшей с расчётом парка для каждой модели.

        Args:
            liquid_t: годовое количество жидкого металла П, т

        Returns:
            Список словарей для :class:`EquipmentPicker`
        """
        from core.transport import calc_ladles
        options: List[Dict[str, Any]] = []
        catalog = [c for c in load_transport_catalog()
                   if str(c.get("category")) == "ladle"]
        # Лучший вариант — минимальный общий парк ковшей (оптимальность
        # выше у крупнее ёмкость/короче цикл); сортировка по парку.
        scored = []
        for card in catalog:
            res = calc_ladles(liquid_t, ladle_id=str(card.get("id")))
            scored.append((res.total, res, card))
        scored.sort(key=lambda x: x[0])
        for rank, (total, res, card) in enumerate(scored):
            card = dict(card)
            specs = dict(card.get("specs") or {})
            specs["capacity_t"] = res.capacity_t
            card["specs"] = specs
            card["card_fields"] = [
                ("capacity_t", "Ёмкость, т"),
                ("cycle_time_min", "Цикл, мин"),
            ]
            card["description"] = (
                f"Рабочих: {res.working}, ремонт: {res.in_repair}, "
                f"резерв: {res.reserve}")
            card["_num_required"] = total
            card["_load_factor"] = round(
                liquid_t * res.cycle_time_h
                / max(res.fund_h * res.capacity_t * total, 1e-9), 2)
            options.append(card)
        return options

    def _crane_options(self) -> List[Dict[str, Any]]:
        """Построить карточки мостовых кранов из справочника."""
        options: List[Dict[str, Any]] = []
        catalog = [c for c in load_transport_catalog()
                   if str(c.get("category")) == "crane"]
        catalog.sort(key=lambda c: -float(c.get("capacity_t") or 0.0))
        for card in catalog:
            card = dict(card)
            specs = dict(card.get("specs") or {})
            card["card_fields"] = [
                ("capacity_t", "Г/п, т"),
                ("group_area_m2", "Площадь группы, м²"),
                ("power_kw", "Мощность, кВт"),
            ]
            footprint = specs.get("footprint_mm")
            if footprint:
                card["description"] = f"Габариты тележки: {footprint}"
            options.append(card)
        return options

    # ──────────────────── отрисовка карточек выбора ────────────────────
    def _render_cards(self,
                      layout: QHBoxLayout,
                      group_attr: str,
                      options: List[Dict[str, Any]],
                      selected_id: Optional[str],
                      position_key: str) -> None:
        """Отрисовать ряд карточек :class:`EquipmentCard` с радио-выбором.

        Args:
            layout: горизонтальный контейнер для карточек
            group_attr: имя атрибута, хранящего ``QButtonGroup`` ряда
            options: карточки (первая — лучшая по оптимальности)
            selected_id: восстанавливаемый выбор пользователя
            position_key: ``ladle`` / ``crane`` — позиция в choices.json
        """
        # Очистить старый ряд (виджеты + отвязка radio-кнопок от группы)
        old_group = getattr(self, group_attr, None)
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                for btn in widget.findChildren(QRadioButton):
                    if old_group is not None:
                        old_group.removeButton(btn)
                widget.deleteLater()
                widget.setParent(None)

        group = QButtonGroup(self)
        setattr(self, group_attr, group)
        for i, equip in enumerate(options):
            card = EquipmentCard(equip)
            layout.addWidget(card)
            group.addButton(card.radio, i)
            card.selected.connect(
                lambda data, key=position_key: self._on_choice(key, data))

        if options:
            idx = 0
            if selected_id is not None:
                for i, equip in enumerate(options):
                    if equip.get("id") == selected_id:
                        idx = i
                        break
            button = group.button(idx)
            if button is not None:
                button.setChecked(True)

    # ─────────────────────── данные/расчёт ───────────────────────
    def refresh(self) -> None:
        """Пересчитать транспорт и обновить интерфейс."""
        saved = self.choices.get_operation_choices(
            self.project.project_id, UserChoices.TRANSPORT_CATEGORY)

        try:
            result = calc_transport(self.project, selected_ids=saved)
        except Exception as exc:  # не роняем UI при неполных данных
            self._basis_lbl.setText(
                f"Не удалось рассчитать транспорт: {exc}. Заполните "
                "исходные данные (годовой выпуск, материал).")
            return
        self._result = result

        ladle = result.ladles
        liquid_t = float(ladle.liquid_metal_t) if ladle else 0.0
        self._basis_lbl.setText(
            f"Жидкий металл: {_fmt_int(liquid_t)} т/год. "
            f"Длины участков взяты из ведомости площадей (типовой пролёт "
            "12 м), нормы кранов — табл. 16/18 дипломов.")

        # Карточки (с восстановлением сохранённого выбора). Флаг
        # _updating подавляет реактивный пересчёт из _on_choice:
        # программная установка radio-кнопки тоже эмитирует selected.
        self._updating = True
        try:
            self._render_cards(
                self.ladle_cards_layout, "_ladle_group",
                self._ladle_options(liquid_t), saved.get("ladle"), "ladle")
            self._render_cards(
                self.crane_cards_layout, "_crane_group",
                self._crane_options(), saved.get("crane"), "crane")
        finally:
            self._updating = False

        if ladle is not None:
            self.ladle_formula_lbl.setText(ladle.formula)

        crane_model = saved.get("crane") or "рекомендуемая модель"
        self.crane_note_lbl.setText(
            f"Число кранов определяется нормами длины участков "
            f"(модель '{crane_model}' влияет на площадь группы).")

        # Ведомость
        rows = result.rows
        self._table.setRowCount(len(rows))
        kind_titles = {"crane": "🏗", "ladle": "🥣", "conveyor": "⛰",
                       "pneumatic": "💨", "auxiliary": "🚜"}
        for i, r in enumerate(rows):
            cells = [
                f"{kind_titles.get(r.kind, '')} {r.name}",
                r.model,
                _fmt_int(r.units),
                r.basis,
                r.department,
            ]
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, j, item)

        # Итоги
        self._summary_labels["cranes"].setText(_fmt_int(result.cranes_total))
        if ladle is not None:
            self._summary_labels["ladles"].setText(
                f"{_fmt_int(ladle.total)} шт. "
                f"(рабочих {ladle.working}, ремонт {ladle.in_repair}, "
                f"резерв {ladle.reserve})")
        self._summary_labels["area"].setText(_fmt_m2(result.total_area_m2))
        self._notes_lbl.setText("\n".join(result.notes))

        self.transport_recalculated.emit(result.as_dict())

    # ─────────────────────── выбор пользователя ───────────────────────
    def _on_choice(self, position_key: str, equipment_data: Dict[str, Any]) -> None:
        """Сохранить выбранный ковш/кран и пересчитать раздел.

        Args:
            position_key: ``ladle`` или ``crane``
            equipment_data: карточка из picker'а
        """
        self.choices.save_operation_choice(
            self.project.project_id, UserChoices.TRANSPORT_CATEGORY,
            position_key, equipment_data)
        self.equipment_choice_changed.emit(
            {"position": position_key, **equipment_data})
        # Пересчёт только при «живом» клике пользователя: программный
        # выбор в refresh() (_updating=True) не должен запускать его
        # повторно (рекурсия).
        if not self._updating:
            self.refresh()

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь-представление :func:`calc_transport` (пустой, если
            расчёт ещё не выполнялся)
        """
        if self._result is None:
            return {}
        return self._result.as_dict()
