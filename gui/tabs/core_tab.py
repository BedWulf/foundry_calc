"""Вкладка «Стержневое отделение» (Раздел 5).

Реализует подбор стержневого оборудования по «умной» архитектуре,
совместимой с плавильным и формовочным отделениями:

  1. Машины фильтруются строго по категории выбранного материала
     (сталь / чугун / алюминий) — см. ``applicable_for.materials`` в
     ``data/equipment/core_machines.json``.
  2. Пользователю показывается топ-3…5 подходящих машин карточками с
     радио-кнопками (переиспользуется виджет ``EquipmentPicker``).
  3. Лучший вариант выбирается автоматически по скорингу
     (близость Кзо парка к идеальной зоне 0.70–0.85; дипломы — примеры,
     поэтому оптимальность важнее флага ``recommended``).
  4. Выбор сохраняется в ``user_data/choices.json`` (категория
     ``core_machine``) и восстанавливается при следующем запуске.
  5. Есть кнопка добавления своей машины через ``EquipmentDialog``
     (запись в ``user_data/custom_core_machines.json``).
  6. Связка с формовочным отделением: годовая программа стержней
     Nст.год = Nф.год · k_ст (число стержней на форму из номенклатуры
     либо вручную); при изменении программы формовки вкладка
     пересчитывается реактивно.

Эталонные формулы (методичка, раздел «Стержневое отделение»):
    Nст.год = Nф.год · k_ст ;  Q_ч = 3600/t_цикл · N_гнёзд ;
    L = Nст.год / Q_ч ;  Ппр = ceil(L / Фд) ;  Кзо = L / (Ппр · Фд)
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QGridLayout, QScrollArea, QMessageBox, QDialog, QDoubleSpinBox,
)

from config import COLORS
from core.project import Project
from core.core_making import (
    CoreCalculator, DEFAULT_CORES_PER_MOLD, calc_annual_cores,
)
from core.molding import calc_avg_cores_per_mold, calc_molding
from core.user_choices import UserChoices
from gui.widgets.equipment_picker import EquipmentPicker
from gui.dialogs.equipment_dialog import EquipmentDialog

# Человекочитаемые названия категорий материалов
CATEGORY_TITLES: Dict[str, str] = {
    "steel": "Сталь",
    "cast_iron": "Чугун",
    "aluminum": "Алюминий",
}

#: Идеальная зона загрузки парка стержневых машин (методичка, 0.70–0.85)
LOAD_OPTIMAL_MIN: float = 0.70
LOAD_OPTIMAL_MAX: float = 0.85

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


def _fmt_int(value: float) -> str:
    """Отформатировать целое с пробелами-разделителями разрядов."""
    return f"{int(round(value)):,}".replace(",", " ")


class CoreTab(QWidget):
    """Вкладка стержневого отделения: программа стержней и подбор машин."""

    #: Сигнал о том, что выбор стержневой машины изменился
    machine_choice_changed = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self.calculator = CoreCalculator()
        self.choices = UserChoices()
        self._current_options: List[Dict[str, Any]] = []
        self._selected: Dict[str, Any] = {}
        self._last_result: Dict[str, Any] = {}
        self._cores_per_mold_override: Optional[float] = None
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("🧱 Стержневое отделение")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel(
            "Раздел 5: программа стержней, подбор стержневых автоматов "
            "(связка с формовочным отделением)")
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

        # ── Блок «Программа стержней» ──
        prog_box = QGroupBox("Расчёт годовой программы стержней")
        prog_box.setStyleSheet(GROUP_STYLE)
        grid = QGridLayout(prog_box)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(24)
        self._prog_labels: Dict[str, QLabel] = {}

        self._add_grid_row(grid, 0, "Материал / сплав", "material")
        self._add_grid_row(grid, 1,
                           "Годовое число форм (из формовочного отд.), Nф.год",
                           "annual_molds")

        # Строка с редактором среднего числа стержней на форму
        name_lbl = QLabel("Среднее число стержней на форму, k_ст:")
        name_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-weight: normal;")
        grid.addWidget(name_lbl, 2, 0)
        spin_row = QHBoxLayout()
        self.spin_cores_per_mold = QDoubleSpinBox()
        self.spin_cores_per_mold.setRange(0.0, 20.0)
        self.spin_cores_per_mold.setDecimals(2)
        self.spin_cores_per_mold.setSingleStep(0.1)
        self.spin_cores_per_mold.setValue(DEFAULT_CORES_PER_MOLD)
        self.spin_cores_per_mold.setToolTip(
            "По умолчанию рассчитывается по номенклатуре "
            "(взвешенно по числу форм); можно задать вручную")
        self.spin_cores_per_mold.valueChanged.connect(
            self._on_cores_per_mold_changed)
        spin_row.addWidget(self.spin_cores_per_mold)
        self.lbl_kst_source = QLabel("(по номенклатуре)")
        self.lbl_kst_source.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-style: italic;")
        spin_row.addWidget(self.lbl_kst_source)
        spin_row.addStretch()
        grid.addLayout(spin_row, 2, 1)

        self._add_grid_row(grid, 3, "Годовая программа стержней, Nст.год",
                           "annual_cores")
        self._add_grid_row(grid, 4, "Действительный фонд работы машин, Фд",
                           "fund_hours")
        self._layout.addWidget(prog_box)

        # ── Блок «Выбор оборудования» ──
        equip_box = QGroupBox("Подбор стержневых машин (фильтр по материалу)")
        equip_box.setStyleSheet(GROUP_STYLE)
        vbox = QVBoxLayout(equip_box)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(10)

        top_row = QHBoxLayout()
        self.lbl_material = QLabel("Материал: —")
        self.lbl_material.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_material.setStyleSheet(f"color: {COLORS['text_primary']};")
        top_row.addWidget(self.lbl_material)
        top_row.addStretch()

        btn_style = f"""
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
        btn_add = QPushButton("＋ Добавить свою машину")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(btn_style)
        btn_add.clicked.connect(self._on_add_custom_machine)
        top_row.addWidget(btn_add)

        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(btn_style)
        btn_refresh.clicked.connect(self.refresh)
        top_row.addWidget(btn_refresh)
        vbox.addLayout(top_row)

        self.picker = EquipmentPicker(category="стержневые машины")
        self.picker.equipment_selected.connect(self._on_machine_selected)
        vbox.addWidget(self.picker, 1)
        self._layout.addWidget(equip_box, 1)

        # ── Блок «Итоги по выбранной машине» ──
        result_box = QGroupBox("Итоговый расчёт по выбранному оборудованию")
        result_box.setStyleSheet(GROUP_STYLE)
        rgrid = QGridLayout(result_box)
        rgrid.setContentsMargins(12, 12, 12, 12)
        rgrid.setHorizontalSpacing(24)
        self._result_labels: Dict[str, QLabel] = {}
        result_rows = [
            ("machine", "Принятая машина"),
            ("productivity", "Часовая производительность (Q_ч)"),
            ("hours_required", "Требуемые машино-часы (L)"),
            ("num_adopt", "Принятое количество машин (Ппр)"),
            ("load_factor", "Коэффициент загрузки (Кзо)"),
        ]
        for r, (key, title) in enumerate(result_rows):
            n_lbl = QLabel(f"{title}:")
            n_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            v_lbl = QLabel("—")
            v_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            v_lbl.setStyleSheet(f"color: {COLORS['success']};")
            rgrid.addWidget(n_lbl, r, 0)
            rgrid.addWidget(v_lbl, r, 1)
            self._result_labels[key] = v_lbl
        self._layout.addWidget(result_box)
        self._layout.addStretch()

    def _add_grid_row(self, grid: QGridLayout, row: int,
                      title: str, key: str) -> None:
        """Добавить в сетку пару «подпись — значение» блока программы."""
        name_lbl = QLabel(f"{title}:")
        name_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-weight: normal;")
        val_lbl = QLabel("—")
        val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        val_lbl.setStyleSheet(f"color: {COLORS['accent']};")
        grid.addWidget(name_lbl, row, 0)
        grid.addWidget(val_lbl, row, 1)
        self._prog_labels[key] = val_lbl

    # ─────────────────────── данные/расчёт ───────────────────────
    def _molding_program(self) -> Dict[str, Any]:
        """Взять годовую программу форм из модели проекта.

        Использует ``calc_molding`` (единый источник истины с формовочной
        вкладкой), чтобы получить Nф.год, категорию материала и фонд времени.

        Returns:
            Словарь: annual_molds, fund_hours, material_category, max_mass_kg
        """
        result = calc_molding(self.project, top_n=1)
        castings = list(getattr(self.project, "castings", []) or [])
        max_mass = max((float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
                        for c in castings), default=0.0)
        return {
            "annual_molds": result.annual_molds_total,
            "fund_hours": result.fund_hours,
            "material_category": result.material_category,
            "max_mass_kg": max_mass,
        }

    def refresh(self) -> None:
        """Пересчитать программу стержней и обновить подбор машин.

        Сохранённый ранее выбор пользователя восстанавливается из
        ``user_data/choices.json`` (категория ``core_machine``); если машина
        больше не подходит (сменили материал/программу) — берётся лучший
        вариант по скорингу.
        """
        molding = self._molding_program()
        castings = list(getattr(self.project, "castings", []) or [])
        auto_kst = calc_avg_cores_per_mold(castings)

        # k_ст: ручное значение пользователя или расчёт по номенклатуре
        if self._cores_per_mold_override is None:
            self._set_spin_value(auto_kst)
            self.lbl_kst_source.setText("(по номенклатуре)")
            k_st = auto_kst
        else:
            self.lbl_kst_source.setText("(вручную)")
            k_st = self._cores_per_mold_override

        saved = self.choices.get_equipment_choice(
            self.project.project_id,
            UserChoices.CORE_MACHINE_CATEGORY) or {}
        saved_id: Optional[str] = saved.get("equipment_id") or None

        result = self.calculator.calc_cores(
            material_category=molding["material_category"],
            annual_molds=molding["annual_molds"],
            cores_per_mold=k_st,
            working_hours=molding["fund_hours"],
            max_casting_mass_kg=molding["max_mass_kg"],
            top_n=5,
            selected_machine_id=saved_id,
        )
        self._last_result = result

        cat_title = CATEGORY_TITLES.get(molding["material_category"],
                                        molding["material_category"])
        alloy_name = getattr(self.project, "alloy", "") or \
            getattr(self.project, "selected_alloy_id", "")
        self._prog_labels["material"].setText(
            f"{cat_title} (сплав: {alloy_name})")
        self.lbl_material.setText(f"Материал: {cat_title}")
        self._prog_labels["annual_molds"].setText(
            f"{_fmt_int(molding['annual_molds'])} шт")
        self._prog_labels["annual_cores"].setText(
            f"{_fmt_int(result['annual_cores'])} шт")
        self._prog_labels["fund_hours"].setText(
            f"{_fmt_int(molding['fund_hours'])} ч")

        self._current_options = result["options"]
        self.picker.set_equipment_options(
            result["options"], selected_id=result["selected_machine_id"])

        if not result["options"]:
            self._show_no_options(cat_title)

    def _set_spin_value(self, value: float) -> None:
        """Задать значение спинбора k_ст без запуска пересчёта."""
        self.spin_cores_per_mold.blockSignals(True)
        self.spin_cores_per_mold.setValue(value)
        self.spin_cores_per_mold.blockSignals(False)

    def _show_no_options(self, cat_title: str) -> None:
        """Показать заглушку, если под текущую программу машин не найдено."""
        for key, lbl in self._result_labels.items():
            lbl.setText("—" if key != "load_factor" else "0.000")
        self._result_labels["machine"].setText(
            f"Нет подходящих машин для «{cat_title}» — добавьте свою")

    # ─────────────────────── обработчики ───────────────────────
    def _on_cores_per_mold_changed(self, value: float) -> None:
        """Пользователь задал k_ст вручную — пересчитать подбор."""
        self._cores_per_mold_override = float(value)
        self.refresh()

    def _on_machine_selected(self, equipment: Dict[str, Any]) -> None:
        """Обработать выбор машины: пересчёт итогов и сохранение выбора."""
        self._selected = equipment
        specs = equipment.get("specs", {})
        hourly = float(specs.get("hourly_output_cores_h", 0) or 0)
        num = int(equipment.get("_num_required", 0))
        load = float(equipment.get("_load_factor", 0.0))
        hours = float(equipment.get("_hours_required", 0.0))

        self._result_labels["machine"].setText(
            f"{equipment.get('name', '?')}"
            + (" (пользовательская)" if equipment.get("custom") else ""))
        self._result_labels["productivity"].setText(f"{hourly:g} ст/ч")
        self._result_labels["hours_required"].setText(
            f"{_fmt_int(hours)} ч/год")
        self._result_labels["num_adopt"].setText(f"{num} шт")
        if LOAD_OPTIMAL_MIN <= load <= LOAD_OPTIMAL_MAX:
            color = COLORS["success"]
        elif load < LOAD_OPTIMAL_MIN:
            color = COLORS["warning"]
        else:
            color = COLORS["accent"]
        self._result_labels["load_factor"].setText(f"{load:.3f}")
        self._result_labels["load_factor"].setStyleSheet(f"color: {color};")

        # Сохранение выбора пользователя (требование №4)
        self.choices.save_equipment_choice(
            self.project.project_id, equipment,
            category=UserChoices.CORE_MACHINE_CATEGORY)
        self.machine_choice_changed.emit(equipment)

    def _on_add_custom_machine(self) -> None:
        """Открыть диалог добавления своей стержневой машины (требование №5)."""
        dialog = EquipmentDialog(self, kind="core_machine")
        if dialog.exec() == QDialog.Accepted:
            card = dialog.get_result()
            if not card:
                return
            record = self.calculator.add_custom_machine(card)
            QMessageBox.information(
                self, "Добавлено",
                f"Машина «{record.get('name')}» сохранена в "
                f"user_data/custom_core_machines.json и добавлена в подбор.")
            self.refresh()

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных (слот сигнала)."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь с ключами: annual_cores, cores_per_mold, machine_name,
            machine_count, load_factor
        """
        res = self._last_result
        return {
            "annual_cores": res.get("annual_cores", 0),
            "cores_per_mold": res.get("cores_per_mold", 0.0),
            "machine_name": self._selected.get("name", ""),
            "machine_count": int(self._selected.get("_num_required", 0)),
            "load_factor": float(self._selected.get("_load_factor", 0.0)),
            "capacity_cores_year": (
                __import__("core.core_making", fromlist=["machine_hourly_output"])
                .machine_hourly_output(self._selected)
                * int(self._selected.get("_num_required", 0))
                * float(getattr(self.project, "F_equipment_h", 0) or 0)
                if self._selected.get("id") else None),
        }
