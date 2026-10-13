"""Вкладка «Отделение обрубки, очистки и термообработки» (Раздел 7).

Реализует подбор очистного оборудования по «умной» архитектуре,
совместимой с плавильным, формовочным и стержневым отделениями:

  1. Оборудование фильтруется строго по категории выбранного материала
     (сталь / чугун / алюминий) и по позиции техпроцесса — см.
     ``applicable_for`` в ``data/equipment/thermal_equip.json``.
  2. По каждой позиции (охлаждение, выбивка, дробемёт, обрубка ЛПС,
     зачистка, термообработка) показывается топ-3…5 карточек с
     радио-кнопками (переиспользуется виджет ``EquipmentPicker``).
  3. Лучший вариант выбирается автоматически по скорингу
     (близость Кзо парка к идеальной зоне 0.70–0.85; дипломы — примеры,
     поэтому оптимальность важнее флага ``recommended``).
  4. Выбор сохраняется в ``user_data/choices.json`` (категория
     ``cleaning_equipment``, подсловарь по ключу позиции) и
     восстанавливается при следующем запуске.
  5. Есть кнопка добавления своей установки через ``EquipmentDialog``
     (запись в ``user_data/custom_cleaning_machines.json``).
  6. Связка с формовочным отделением: тоннаж выбивки включает стержневую
     смесь, число форм берётся из программы формовки; при изменении
     программы/выбора линии вкладка пересчитывается реактивно.

Эталонные формулы (методичка, раздел «Обрубка и очистка»):
    П₁ = M·k_н / (Q_ч · Фд · η) ;  Nпр = ceil(П₁) ;  Кзо = П₁ / Nпр
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QGridLayout, QScrollArea, QMessageBox, QDialog,
)

from config import COLORS
from core.project import Project
from core.cleaning import (
    CleaningCalculator, OPERATION_TITLES, OPERATIONS,
    LOAD_OPTIMAL_MIN, LOAD_OPTIMAL_MAX, calc_cleaning, to_picker_options,
)
from core.user_choices import UserChoices
from gui.widgets.equipment_picker import EquipmentPicker
from gui.dialogs.equipment_dialog import EquipmentDialog

# Человекочитаемые названия категорий материалов
CATEGORY_TITLES: Dict[str, str] = {
    "steel": "Сталь",
    "cast_iron": "Чугун",
    "aluminum": "Алюминий",
}

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


def _fmt_int(value: float) -> str:
    """Отформатировать целое с пробелами-разделителями разрядов."""
    return f"{int(round(value)):,}".replace(",", " ")


class CleaningTab(QWidget):
    """Вкладка ОООиТО: баланс тоннажей и подбор оборудования по позициям."""

    #: Сигнал о том, что выбор очистного оборудования изменился
    equipment_choice_changed = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self.calculator = CleaningCalculator()
        self.choices = UserChoices()
        self._last_result: Dict[str, Any] = {}
        self._selected: Dict[str, Dict[str, Any]] = {}
        self._pickers: Dict[str, EquipmentPicker] = {}
        self._op_labels: Dict[str, Dict[str, QLabel]] = {}
        self._prog_labels: Dict[str, QLabel] = {}
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("🧹 Обрубка, очистка и термообработка")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel(
            "Раздел 7: баланс тоннажей, подбор оборудования по позициям "
            "техпроцесса (связка с формовочным отделением)")
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

        # ── Блок «Тоннажи отделения» ──
        prog_box = QGroupBox("Тоннаж, проходящий через отделение")
        prog_box.setStyleSheet(GROUP_STYLE)
        grid = QGridLayout(prog_box)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(24)

        rows = [
            ("material", "Материал / сплав"),
            ("casting_count_t",
             "Литьё с ЛПС (охлаждение, выбивка, дробемёт, обрубка), т/год"),
            ("clean_casting_t", "Литьё после обрубки (зачистка, ТО), т/год"),
            ("cores_ton_t", "Стержневая смесь на выбивку, т/год"),
            ("annual_molds", "Годовое число форм (из формовочного отд.), шт"),
            ("fund_hours", "Действительный фонд времени оборудования, ч"),
        ]
        for r, (key, title) in enumerate(rows):
            name_lbl = QLabel(f"{title}:")
            name_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            val_lbl.setStyleSheet(f"color: {COLORS['accent']};")
            grid.addWidget(name_lbl, r, 0)
            grid.addWidget(val_lbl, r, 1)
            self._prog_labels[key] = val_lbl

        top_row = QHBoxLayout()
        top_row.addStretch()
        btn_add = QPushButton("＋ Добавить свою установку")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(BTN_STYLE)
        btn_add.clicked.connect(self._on_add_custom_machine)
        top_row.addWidget(btn_add)
        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(BTN_STYLE)
        btn_refresh.clicked.connect(self.refresh)
        top_row.addWidget(btn_refresh)
        grid.addLayout(top_row, len(rows), 1, Qt.AlignRight)
        self._layout.addWidget(prog_box)

        # ── Блоки по позициям техпроцесса ──
        for op in OPERATIONS:
            box = QGroupBox(OPERATION_TITLES[op])
            box.setStyleSheet(GROUP_STYLE)
            vbox = QVBoxLayout(box)
            vbox.setContentsMargins(12, 12, 12, 12)
            vbox.setSpacing(8)

            info_lbl = QLabel("—")
            info_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            vbox.addWidget(info_lbl)

            picker = EquipmentPicker(category=OPERATION_TITLES[op].lower())
            picker.equipment_selected.connect(
                lambda eq, o=op: self._on_equipment_selected(o, eq))
            vbox.addWidget(picker, 1)
            self._pickers[op] = picker
            self._op_labels[op] = {"info": info_lbl}
            self._layout.addWidget(box)

        # ── Блок «Итоги отделения» ──
        result_box = QGroupBox("Итоговый расчёт по принятому парку")
        result_box.setStyleSheet(GROUP_STYLE)
        rgrid = QGridLayout(result_box)
        rgrid.setContentsMargins(12, 12, 12, 12)
        rgrid.setHorizontalSpacing(24)
        self._result_labels: Dict[str, QLabel] = {}
        result_rows = [
            ("total_units", "Суммарное количество установок"),
            ("avg_load_factor", "Средний коэффициент загрузки (Кзо)"),
            ("park_list", "Принятое оборудование по позициям"),
        ]
        for r, (key, title) in enumerate(result_rows):
            n_lbl = QLabel(f"{title}:")
            n_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            v_lbl = QLabel("—")
            v_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            v_lbl.setStyleSheet(f"color: {COLORS['success']};")
            v_lbl.setWordWrap(True)
            rgrid.addWidget(n_lbl, r, 0)
            rgrid.addWidget(v_lbl, r, 1)
            self._result_labels[key] = v_lbl
        self._layout.addWidget(result_box)
        self._layout.addStretch()

    # ─────────────────────── данные/расчёт ───────────────────────
    def refresh(self) -> None:
        """Пересчитать всё отделение и обновить карточки.

        Сохранённые ранее выборы пользователя восстанавливаются из
        ``user_data/choices.json`` (категория ``cleaning_equipment``); если
        оборудование больше не подходит (сменили материал/программу) —
        берётся лучший вариант по скорингу.
        """
        saved_ids = self.choices.get_operation_choices(
            self.project.project_id, UserChoices.CLEANING_CATEGORY)
        result = calc_cleaning(self.project, calculator=self.calculator,
                               selected_ids=saved_ids, top_n=5)
        self._last_result = result

        masses = result.get("masses", {})
        summary = result.get("summary", {})
        category = result.get("material_category", "")
        cat_title = CATEGORY_TITLES.get(category, category or "—")
        alloy_name = getattr(self.project, "alloy", "") or \
            getattr(self.project, "selected_alloy_id", "")
        self._prog_labels["material"].setText(
            f"{cat_title} (сплав: {alloy_name})")
        self._prog_labels["casting_count_t"].setText(
            f"{_fmt_int(masses.get('casting_count_t', 0))} т")
        self._prog_labels["clean_casting_t"].setText(
            f"{_fmt_int(masses.get('clean_casting_t', 0))} т")
        self._prog_labels["fund_hours"].setText(
            f"{_fmt_int(summary.get('fund_hours', 0))} ч")
        self._prog_labels["annual_molds"].setText(
            f"{_fmt_int(summary.get('annual_molds', 0))} шт")

        ops: Dict[str, Dict[str, Any]] = result.get("operations", {})
        cores_t = max((o.get("cores_ton_t", 0.0) for o in ops.values()),
                      default=0.0)
        self._prog_labels["cores_ton_t"].setText(f"{_fmt_int(cores_t)} т")

        for op in OPERATIONS:
            data = ops.get(op, {})
            options = to_picker_options(data.get("options", []))
            picker = self._pickers[op]
            info = self._op_labels[op]["info"]
            if not options:
                picker.set_equipment_options([])
                info.setText(
                    f"Тоннаж: {_fmt_int(data.get('tonnage_t', 0))} т — "
                    f"подходящего оборудования не найдено, добавьте своё")
                continue
            tonnage = data.get("tonnage_t", 0.0)
            p1 = data.get("p1_required", 0.0)
            info.setText(
                f"Тоннаж: {tonnage:g} т/год · Потребно установок (П₁): "
                f"{p1:.2f} · Принято: {data.get('machine_count', 0)} шт · "
                f"Кзо: {data.get('load_factor', 0.0):.3f}")
            picker.set_equipment_options(
                options, selected_id=data.get("selected_id") or None)

        self._update_summary()

    def _update_summary(self) -> None:
        """Обновить блок итогов по принятому парку оборудования."""
        ops: Dict[str, Any] = self._last_result.get("operations", {})
        chosen_names: List[str] = []
        total_units = 0
        factors: List[float] = []
        for op in OPERATIONS:
            data = ops.get(op, {})
            sel = self._selected.get(op) or {}
            machine = sel or next(
                (o for o in data.get("options", [])
                 if o.get("id") == data.get("selected_id")), {})
            if not machine:
                continue
            units = int(machine.get("_num_required", 0))
            factor = float(machine.get("_load_factor", 0.0))
            total_units += units
            if units > 0:
                factors.append(factor)
            chosen_names.append(
                f"{OPERATION_TITLES[op]}: {machine.get('name', '?')} — "
                f"{units} шт (Кзо {factor:.2f})")
        self._result_labels["total_units"].setText(f"{total_units} шт")
        avg = sum(factors) / len(factors) if factors else 0.0
        if LOAD_OPTIMAL_MIN <= avg <= LOAD_OPTIMAL_MAX:
            color = COLORS["success"]
        elif avg < LOAD_OPTIMAL_MIN:
            color = COLORS["warning"]
        else:
            color = COLORS["accent"]
        self._result_labels["avg_load_factor"].setText(f"{avg:.3f}")
        self._result_labels["avg_load_factor"].setStyleSheet(
            f"color: {color};")
        self._result_labels["park_list"].setText(
            "\n".join(chosen_names) if chosen_names else "—")

    # ─────────────────────── обработчики ───────────────────────
    def _on_equipment_selected(self, operation: str,
                               equipment: Dict[str, Any]) -> None:
        """Обработать выбор оборудования по позиции: сохранить и обновить итоги.

        Args:
            operation: ключ позиции техпроцесса
            equipment: карточка выбранного оборудования
        """
        self._selected[operation] = equipment
        data = self._last_result.get("operations", {}).get(operation, {})
        info = self._op_labels[operation]["info"]
        units = int(equipment.get("_num_required", 0))
        factor = float(equipment.get("_load_factor", 0.0))
        info.setText(
            f"Тоннаж: {data.get('tonnage_t', 0):g} т/год · Потребно "
            f"установок (П₁): {equipment.get('_p1_required', 0):.2f} · "
            f"Принято: {units} шт · Кзо: {factor:.3f}")

        # Сохранение выбора пользователя (требование №4)
        self.choices.save_operation_choice(
            self.project.project_id, UserChoices.CLEANING_CATEGORY,
            operation, equipment)
        self._update_summary()
        self.equipment_choice_changed.emit(
            {"operation": operation, **equipment})

    def _on_add_custom_machine(self) -> None:
        """Открыть диалог добавления своей очистной установки (требование №5)."""
        dialog = EquipmentDialog(self, kind="cleaning_machine")
        if dialog.exec() == QDialog.Accepted:
            card = dialog.get_result()
            if not card:
                return
            record = self.calculator.add_custom_machine(card)
            QMessageBox.information(
                self, "Добавлено",
                f"Установка «{record.get('name')}» сохранена в "
                f"user_data/custom_cleaning_machines.json и добавлена "
                f"в подбор.")
            self.refresh()

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных (слот сигнала)."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь: total_units, avg_load_factor, casting_count_t,
            clean_casting_t, park (позиция → название/кол-во/Кзо)
        """
        ops: Dict[str, Any] = self._last_result.get("operations", {})
        summary = self._last_result.get("summary", {})
        park: Dict[str, Any] = {}
        for op in OPERATIONS:
            data = ops.get(op, {})
            if not data.get("selected_id"):
                continue
            park[op] = {
                "title": OPERATION_TITLES[op],
                "machine_count": data.get("machine_count", 0),
                "load_factor": data.get("load_factor", 0.0),
            }
        return {
            "total_units": summary.get("total_units", 0),
            "avg_load_factor": summary.get("avg_load_factor", 0.0),
            "casting_count_t": self._last_result.get(
                "masses", {}).get("casting_count_t", 0.0),
            "clean_casting_t": self._last_result.get(
                "masses", {}).get("clean_casting_t", 0.0),
            "park": park,
        }
