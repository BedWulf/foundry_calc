"""Вкладка «Смесеприготовительное отделение» (Раздел 6).

Реализует подбор смесеприготовительного оборудования по «умной» архитектуре,
совместимой с плавильным, формовочным, стержневым и очистным отделениями:

  1. Оборудование фильтруется по категории материала и по операции
     (``applicable_for.materials`` + ключ ``operation`` в
     ``data/equipment/mixers.json``).
  2. По каждой операции (приготовление формовочной/стержневой смеси,
     раздавливание комьев, просев, охлаждение, магнитная сепарация)
     показывается топ-3…5 карточек с радио-кнопками (``EquipmentPicker``).
  3. Лучший вариант выбирается автоматически по скорингу (близость Кзо
     парка к идеальной зоне 0.70–0.85; дипломы — примеры, оптимальность
     важнее флага ``recommended``).
  4. Выбор сохраняется в ``user_data/choices.json`` (категория
     ``sand_prep_equipment``, подсловарь по ключу операции) и
     восстанавливается при следующем запуске.
  5. Есть кнопка добавления своей установки через ``EquipmentDialog``
     (запись в ``user_data/custom_mixers.json``).
  6. Связка с формовочным отделением: годовой объём смеси считается от
     числа форм и объёма опок программы формовки; при изменении
     программы/выбора линии вкладка пересчитывается реактивно.

Эталонные формулы (методичка, раздел 6):
    n = Q · k_н / (q · Фд) ;  Рд = pick_unit_count(n) ;  кз = n / Рд
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
from core.sand_prep import (
    SandPrepCalculator, OPERATION_ORDER, OPERATION_TITLES,
    LOAD_OPTIMAL_MIN, LOAD_OPTIMAL_MAX, calc_sand_prep, to_picker_options,
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


class SandTab(QWidget):
    """Вкладка смесеприготовления: расход смеси и подбор установок."""

    #: Сигнал о том, что выбор смесеприготовительного оборудования изменился
    equipment_choice_changed = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self.calculator = SandPrepCalculator()
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

        header = QLabel("⚙️ Смесеприготовительное отделение")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel(
            "Раздел 6: расход смеси, подбор бегунов/смесителей и "
            "оборудования регенерации по операциям (связка с формовкой)")
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

        # ── Блок «Расход смеси» ──
        prog_box = QGroupBox("Годовой расход смеси")
        prog_box.setStyleSheet(GROUP_STYLE)
        grid = QGridLayout(prog_box)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(24)

        rows = [
            ("material", "Материал / сплав"),
            ("annual_molds", "Годовое число форм (из формовочного отд.), шт"),
            ("mold_volume_total_m3", "Геометрический объём форм, м³/год"),
            ("sand_volume_loose_m3", "Формовочная смесь (неуплотнённая), м³/год"),
            ("core_mix_m3", "Стержневая смесь, м³/год"),
            ("lumps_mass_t", "Комья на раздавливание, т/год"),
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
        btn_add.clicked.connect(self._on_add_custom_mixer)
        top_row.addWidget(btn_add)
        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(BTN_STYLE)
        btn_refresh.clicked.connect(self.refresh)
        top_row.addWidget(btn_refresh)
        grid.addLayout(top_row, len(rows), 1, Qt.AlignRight)
        self._layout.addWidget(prog_box)

        # ── Блоки по операциям отделения ──
        for op in OPERATION_ORDER:
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
            ("park_list", "Принятое оборудование по операциям"),
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
        ``user_data/choices.json`` (категория ``sand_prep_equipment``); если
        оборудование больше не подходит (сменили материал/программу) —
        берётся лучший вариант по скорингу.
        """
        saved_ids = self.choices.get_operation_choices(
            self.project.project_id, UserChoices.SAND_PREP_CATEGORY)
        result = calc_sand_prep(self.project, calculator=self.calculator,
                                selected_ids=saved_ids, top_n=5)
        self._last_result = result

        volumes = result.get("volumes", {})
        summary = result.get("summary", {})
        category = _current_category(self.project)
        cat_title = CATEGORY_TITLES.get(category, category or "—")
        alloy_name = getattr(self.project, "alloy", "") or \
            getattr(self.project, "selected_alloy_id", "")
        self._prog_labels["material"].setText(
            f"{cat_title} (сплав: {alloy_name})")
        self._prog_labels["annual_molds"].setText(
            f"{_fmt_int(summary.get('annual_molds', 0))} шт")
        self._prog_labels["mold_volume_total_m3"].setText(
            f"{_fmt_int(volumes.get('mold_volume_total_m3', 0))} м³")
        self._prog_labels["sand_volume_loose_m3"].setText(
            f"{_fmt_int(volumes.get('sand_volume_loose_m3', 0))} м³")
        self._prog_labels["core_mix_m3"].setText(
            f"{_fmt_int(volumes.get('core_mix_m3', 0))} м³")
        self._prog_labels["lumps_mass_t"].setText(
            f"{_fmt_int(volumes.get('lumps_mass_t', 0))} т")
        self._prog_labels["fund_hours"].setText(
            f"{_fmt_int(summary.get('working_hours', 0))} ч")

        operations: List[Dict[str, Any]] = result.get("operations", [])
        for data in operations:
            op = data["operation"]
            options = to_picker_options(data.get("options", []))
            picker = self._pickers[op]
            info = self._op_labels[op]["info"]
            if not options:
                picker.set_equipment_options([])
                info.setText(
                    f"Объём: {data.get('quantity', 0):g} "
                    f"{data.get('quantity_unit', '')} — подходящего "
                    f"оборудования не найдено, добавьте своё")
                continue
            info.setText(
                f"Объём работы: {data.get('quantity', 0):g} "
                f"{data.get('quantity_unit', '')}/год · Потребно (n): "
                f"{data.get('n_required', 0):.2f} · Принято: "
                f"{data.get('units', 0)} шт · Кзо: "
                f"{data.get('load_factor', 0.0):.3f}")
            picker.set_equipment_options(
                options, selected_id=data.get("selected_id") or None)

        self._update_summary()

    def _update_summary(self) -> None:
        """Обновить блок итогов по принятому парку оборудования."""
        ops: Dict[str, Dict[str, Any]] = {
            o["operation"]: o for o in self._last_result.get("operations", [])
        }
        chosen_names: List[str] = []
        total_units = 0
        factors: List[float] = []
        for op in OPERATION_ORDER:
            data = ops.get(op, {})
            sel = self._selected.get(op) or {}
            machine = sel or next(
                (o for o in data.get("options", [])
                 if o.get("id") == data.get("selected_id")), {})
            if not machine:
                continue
            units = int(machine.get("_units", data.get("units", 0)))
            factor = float(machine.get("_load_factor",
                                       data.get("load_factor", 0.0)))
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
        """Обработать выбор установки по операции: сохранить и обновить итоги.

        Args:
            operation: ключ операции (``molding_mix`` и т.п.)
            equipment: карточка выбранного оборудования
        """
        self._selected[operation] = equipment
        ops: Dict[str, Dict[str, Any]] = {
            o["operation"]: o for o in self._last_result.get("operations", [])
        }
        data = ops.get(operation, {})
        info = self._op_labels[operation]["info"]
        units = int(equipment.get("count", equipment.get("_units", 0)))
        factor = float(equipment.get("load_factor",
                                    equipment.get("_load_factor", 0.0)))
        info.setText(
            f"Объём работы: {data.get('quantity', 0):g} "
            f"{data.get('quantity_unit', '')}/год · Принято: {units} шт · "
            f"Кзо: {factor:.3f}")

        # Сохранение выбора пользователя (требование №4)
        record = dict(equipment)
        record.setdefault("_num_required",
                          equipment.get("n_required",
                                        data.get("n_required")))
        record.setdefault("_units", units)
        record.setdefault("_load_factor", factor)
        self.choices.save_operation_choice(
            self.project.project_id, UserChoices.SAND_PREP_CATEGORY,
            operation, record)
        self._update_summary()
        self.equipment_choice_changed.emit({"operation": operation,
                                            **equipment})

    def _on_add_custom_mixer(self) -> None:
        """Открыть диалог добавления своей установки (требование №5)."""
        dialog = EquipmentDialog(self, kind="mixer")
        if dialog.exec() == QDialog.Accepted:
            card = dialog.get_result()
            if not card:
                return
            record = self.calculator.add_custom_mixer(card)
            QMessageBox.information(
                self, "Добавлено",
                f"Установка «{record.get('name')}» сохранена в "
                f"user_data/custom_mixers.json и добавлена в подбор.")
            self.refresh()

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных (слот сигнала)."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь: total_park_units, avg_load_factor, volumes,
            park (операция → название/кол-во/Кзо)
        """
        ops: List[Dict[str, Any]] = self._last_result.get("operations", [])
        summary = self._last_result.get("summary", {})
        park: Dict[str, Any] = {}
        for data in ops:
            if not data.get("selected_id"):
                continue
            park[data["operation"]] = {
                "title": data["title"],
                "model": data.get("model_name", ""),
                "units": data.get("units", 0),
                "load_factor": data.get("load_factor", 0.0),
            }
        from core.sand_prep import machine_productivity
        capacity_operations = []
        for op in ops:
            selected_card = self._selected.get(op["operation"]) or {}
            selected_id = str(selected_card.get("id") or op.get("selected_id") or "")
            raw = next((card for card in op.get("options", [])
                        if str(card.get("id")) == selected_id), None)
            # Manual UI selection may return a picker representation rather
            # than a source equipment card. Resolve back to raw option only.
            count = (int(selected_card.get("count", selected_card.get("_units", 0)))
                     if selected_card else int(op.get("units") or 0))
            unit = str(raw.get("unit", "")) if raw else ""
            # Original sand-preparation equations use tonnes for lumps and
            # cubic metres for every other operation. Machine catalogues
            # are not allowed to silently change those physical dimensions.
            expected_unit = "t_h" if op["operation"] == "lumps" else "m3_h"
            quantity = op.get("quantity")
            working_hours = summary.get("working_hours")
            throughput = machine_productivity(raw) if raw else 0
            capacity = (throughput * count * float(working_hours)
                        if raw and throughput > 0 and count > 0
                        and working_hours and unit == expected_unit else None)
            capacity_operations.append({
                "operation": op["operation"],
                "title": op["title"],
                "quantity": quantity,
                "capacity_year": capacity,
                "unit": ("т/год" if expected_unit == "t_h" else "м³/год"),
                "note": ("Без проверки пиковых сменных нагрузок"
                         if capacity is not None else
                         "Единицы каталога не совпадают с потребностью"
                         if raw and unit != expected_unit else
                         "Нет выбранного оборудования или паспортной мощности"),
            })
        return {
            "total_park_units": summary.get("total_park_units", 0),
            "avg_load_factor": summary.get("avg_load_factor", 0.0),
            "volumes": self._last_result.get("volumes", {}),
            "park": park,
            "capacity_operations": capacity_operations,
        }


def _current_category(project: Project) -> str:
    """Категория сплава текущего проекта (для подписи в шапке вкладки).

    Args:
        project: модель проекта

    Returns:
        'steel' / 'cast_iron' / 'aluminum'
    """
    from core.sand_prep import _alloy_category
    return _alloy_category(str(getattr(project, "selected_alloy_id", "")))
