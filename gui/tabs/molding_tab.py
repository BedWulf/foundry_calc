"""Вкладка «Формовочное отделение» (Шаг 5).

Реализует подбор формовочного оборудования по той же «умной» архитектуре,
что и плавильное отделение:

  1. Линии фильтруются строго по категории выбранного материала
     (сталь / чугун / алюминий) — см. ``applicable_for.materials`` в
     ``data/equipment/molding_lines.json``.
  2. Пользователю показывается топ-3…5 подходящих линий карточками с
     радио-кнопками (переиспользуется виджет ``EquipmentPicker``).
  3. Лучший вариант выбирается автоматически по скорингу
     (близость коэффициента загрузки Кзо к идеальной зоне 0.70–0.85).
  4. Выбор сохраняется в ``user_data/choices.json`` (категория
     ``molding_line``) и восстанавливается при следующем запуске.
  5. Есть кнопка добавления своей линии через ``EquipmentDialog``
     (запись в ``user_data/custom_molding_lines.json``).
  6. Расчёты сверены с эталоном дипломов («Sample Diploma.pdf», л. 25;
     «Sample Diploma 2.pdf», л. 23): группа 4 000 т/год, отливка 4 кг →
     1 000 000 форм, Рр = 257 ф/ч, ИЛ-225 → П₁ = 1.07, принято 2 линии,
     Кзо = 0.536.

Эталонные формулы:
    Nф.год = Г · k_бр.доп / m_отл        — годовое число форм, шт
    Рр     = Nф.год / (Фд · k_мн)        — потребная производительность, ф/ч
    П₁     = Рр / q_ном                  — расчётное число линий
    Кзо    = Рр / (Ппр · q_ном)          — коэффициент загрузки
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QGridLayout, QScrollArea, QMessageBox, QDialog,
    QSpinBox, QDoubleSpinBox, QTextEdit, QFormLayout,
)

from config import COLORS
from core.project import Project
from core.molding import (
    MoldingCalculator, MoldingCalculation, calc_molding,
    calc_avg_cores_per_mold,
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

#: Идеальная зона загрузки формовочных линий (методичка, 0.70–0.85)
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
    """Отформатировать целое с пробелами-разделителями разрядов (1 000 000)."""
    return f"{int(round(value)):,}".replace(",", " ")


class MoldingTab(QWidget):
    """Вкладка формовочного отделения: программа формовки и подбор АФЛ."""

    #: Сигнал о том, что выбор линии изменился (для сводки/соседних вкладок)
    line_choice_changed = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self.calculator = MoldingCalculator()
        self.choices = UserChoices()
        self._current_options: List[Dict[str, Any]] = []
        self._selected: Dict[str, Any] = {}
        self._last_result: Optional[MoldingCalculation] = None
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("🏗 Формовочное отделение")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel("Раздел 4: программа формовки, группы номенклатуры, подбор АФЛ")
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

        # ── Блок «Расчёт программы формовки» ──
        prog_box = QGroupBox("Расчёт годовой программы формовки (табл. 7 диплома)")
        prog_box.setStyleSheet(GROUP_STYLE)
        grid = QGridLayout(prog_box)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(24)
        self._prog_labels: Dict[str, QLabel] = {}
        rows = [
            ("material", "Материал / сплав"),
            ("annual_molds", "Годовое число форм, Nф.год"),
            ("fund_hours", "Действительный фонд работы линий, Фд"),
            ("required_productivity", "Потребная производительность, Рр"),
            ("groups_count", "Групп номенклатуры по массе"),
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
        self._layout.addWidget(prog_box)

        # ── Блок «Выбор оборудования» ──
        equip_box = QGroupBox("Подбор формовочных линий (фильтр по материалу)")
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

        btn_add = QPushButton("＋ Добавить свою линию")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['accent']};
                border: 1px solid {COLORS['accent']};
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg_panel']}; }}
        """)
        btn_add.clicked.connect(self._on_add_custom_line)
        top_row.addWidget(btn_add)

        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(btn_add.styleSheet())
        btn_refresh.clicked.connect(self.refresh)
        top_row.addWidget(btn_refresh)
        vbox.addLayout(top_row)

        self.picker = EquipmentPicker(category="формовочные линии")
        self.picker.equipment_selected.connect(self._on_line_selected)
        vbox.addWidget(self.picker, 1)
        self._layout.addWidget(equip_box, 1)

        # ── Блок «Итоги по выбранной линии» ──
        result_box = QGroupBox("Итоговый расчёт по выбранному оборудованию")
        result_box.setStyleSheet(GROUP_STYLE)
        rgrid = QGridLayout(result_box)
        rgrid.setContentsMargins(12, 12, 12, 12)
        rgrid.setHorizontalSpacing(24)
        self._result_labels: Dict[str, QLabel] = {}
        result_rows = [
            ("line", "Принятая линия"),
            ("productivity", "Номинальная производительность (q_ном)"),
            ("p1_calc", "Расчётное количество линий (П₁)"),
            ("num_adopt", "Принятое количество линий (Ппр)"),
            ("load_factor", "Коэффициент загрузки (Кзо)"),
            ("cores_per_mold", "Среднее число стержней на форму (k_ст)"),
        ]
        for r, (key, title) in enumerate(result_rows):
            name_lbl = QLabel(f"{title}:")
            name_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            val_lbl.setStyleSheet(f"color: {COLORS['success']};")
            rgrid.addWidget(name_lbl, r, 0)
            rgrid.addWidget(val_lbl, r, 1)
            self._result_labels[key] = val_lbl
        self._layout.addWidget(result_box)
        # Общий парк: разные отливки последовательно на общих линиях.
        plan_box = QGroupBox("Общий парк — последовательный выпуск партиями")
        plan_box.setStyleSheet(GROUP_STYLE)
        plan_lay = QVBoxLayout(plan_box)
        form = QFormLayout()
        self._batch_count = QSpinBox()
        self._batch_count.setRange(1, 10000)
        self._batch_count.setValue(self.project.molding_batches_per_year)
        form.addRow("Партий в год на позицию:", self._batch_count)
        self._setup_h = QDoubleSpinBox()
        self._setup_h.setRange(0, 1000)
        self._setup_h.setDecimals(2)
        self._setup_h.setSuffix(" ч")
        self._setup_h.setValue(self.project.molding_setup_h)
        form.addRow("Переналадка каждой партии:", self._setup_h)
        self._max_load = QDoubleSpinBox()
        self._max_load.setRange(0.01, 1.0)
        self._max_load.setDecimals(2)
        self._max_load.setSingleStep(0.05)
        self._max_load.setValue(self.project.molding_max_load_factor)
        form.addRow("Максимальная годовая загрузка:", self._max_load)
        plan_lay.addLayout(form)
        self._batch_report = QTextEdit()
        self._batch_report.setReadOnly(True)
        self._batch_report.setMinimumHeight(210)
        plan_lay.addWidget(self._batch_report)
        self._layout.addWidget(plan_box)
        self._batch_count.valueChanged.connect(self._on_batch_options_changed)
        self._setup_h.valueChanged.connect(self._on_batch_options_changed)
        self._max_load.valueChanged.connect(self._on_batch_options_changed)
        self._layout.addStretch()

    # ─────────────────────── данные/расчёт ───────────────────────
    def refresh(self) -> None:
        """Пересчитать программу формовки и обновить подбор линий.

        Вызывается при старте, при изменении исходных данных и по кнопке
        «Пересчитать». Сохранённый ранее выбор пользователя восстанавливается
        из ``user_data/choices.json`` (категория ``molding_line``); если
        линия больше не подходит (сменили материал/программу) — берётся
        лучший вариант по скорингу.
        """
        saved = self.choices.get_equipment_choice(
            self.project.project_id, UserChoices.MOLDING_LINE_CATEGORY) or {}
        saved_id: Optional[str] = saved.get("equipment_id") or None

        result = calc_molding(
            self.project,
            calculator=self.calculator,
            top_n=5,
            selected_line_id=saved_id,
        )
        self._last_result = result
        self._render_batch_plan(result)

        cat_title = CATEGORY_TITLES.get(result.material_category,
                                        result.material_category)
        alloy_name = getattr(self.project, "alloy", "") or \
            getattr(self.project, "selected_alloy_id", "")
        self._prog_labels["material"].setText(f"{cat_title} (сплав: {alloy_name})")
        self.lbl_material.setText(f"Материал: {cat_title}")
        self._prog_labels["annual_molds"].setText(
            f"{_fmt_int(result.annual_molds_total)} шт")
        self._prog_labels["fund_hours"].setText(f"{_fmt_int(result.fund_hours)} ч")
        self._prog_labels["required_productivity"].setText(
            f"{result.required_productivity_molds_h:.1f} ф/ч")
        if result.groups:
            g_titles = ", ".join(g.title for g in result.groups)
            self._prog_labels["groups_count"].setText(
                f"{len(result.groups)} ({g_titles})")
        else:
            self._prog_labels["groups_count"].setText(
                "0 (номенклатура не загружена — оценка по средней массе)")

        self._current_options = result.line_options
        self.picker.set_equipment_options(
            result.line_options, selected_id=result.selected_line_id)

        # k_ст — мост в стержневое и очистное отделения (тоннаж стержней на
        # выбивке зависит именно от него); показываем здесь, чтобы пользователь
        # видел, откуда берётся число стержней.
        castings = list(getattr(self.project, "castings", []) or [])
        k_st = calc_avg_cores_per_mold(castings) if castings else 0.0
        self._result_labels["cores_per_mold"].setText(
            f"{k_st:.2f} шт/форму" if k_st > 0 else
            "— (номенклатура не загружена)")

    # ─────────────────────── обработчики ───────────────────────
    def _on_batch_options_changed(self, *_args: Any) -> None:
        self.project.molding_batches_per_year = self._batch_count.value()
        self.project.molding_setup_h = self._setup_h.value()
        self.project.molding_max_load_factor = self._max_load.value()
        self.refresh()
        # Give dependent tabs a chance to update.
        self.line_choice_changed.emit(self._selected)

    def _render_batch_plan(self, result: MoldingCalculation) -> None:
        plan = result.batch_plan
        if plan is None:
            self._batch_report.setPlainText(
                "План не построен: " + (result.planning_error or "загрузите номенклатуру"))
            return
        out = [f"Распределено {plan.assigned_molds:,} / {plan.total_molds:,} форм; "
               + ("выполнимо по годовому фонду" if plan.feasible else "НЕ ВЫПОЛНЕНО")]
        for ln in plan.lines:
            out.append(f"{ln.equipment_name} №{ln.instance_no}: "
                       f"{ln.used_hours:.1f}/{ln.allowed_hours:.1f} ч допустимого фонда, "
                       f"загрузка {ln.utilization:.1%}")
            for c in ln.campaigns:
                out.append(f"  {c.job_name}: {c.molds:,} форм; "
                           f"{c.process_hours:.1f} ч + {c.setup_hours:.1f} ч переналадки")
        if plan.unassigned:
            out.append("Не распределены: " + ", ".join(plan.unassigned))
        out.extend("⚠ " + w for w in plan.warnings)
        self._batch_report.setPlainText("\n".join(out))

    def _on_line_selected(self, equipment: Dict[str, Any]) -> None:
        """Обработать выбор линии: пересчёт итогов и сохранение выбора."""
        self._selected = equipment
        specs = equipment.get("specs", {})
        nominal = float(specs.get("nominal_productivity_molds_h", 0) or 0)
        num = int(equipment.get("_num_required", 0))
        load = float(equipment.get("_load_factor", 0.0))
        p1 = float(equipment.get("_p1_required", 0.0))

        self._result_labels["line"].setText(
            f"{equipment.get('name', '?')}"
            + (" (пользовательская)" if equipment.get("custom") else ""))
        self._result_labels["productivity"].setText(f"{nominal:g} ф/ч")
        self._result_labels["p1_calc"].setText(f"{p1:.2f} шт")
        self._result_labels["num_adopt"].setText(f"{num} шт")
        if LOAD_OPTIMAL_MIN <= load <= LOAD_OPTIMAL_MAX:
            color = COLORS["success"]
        elif load < LOAD_OPTIMAL_MIN:
            # недогрузка — в дипломе компенсируется догрузкой др. групп
            color = COLORS["warning"]
        else:
            color = COLORS["accent"]
        self._result_labels["load_factor"].setText(f"{load:.3f}")
        self._result_labels["load_factor"].setStyleSheet(f"color: {color};")

        # Сохранение выбора пользователя (требование №4)
        self.choices.save_equipment_choice(
            self.project.project_id, equipment,
            category=UserChoices.MOLDING_LINE_CATEGORY)
        self.line_choice_changed.emit(equipment)

    def _on_add_custom_line(self) -> None:
        """Открыть диалог добавления своей формовочной линии (требование №5)."""
        dialog = EquipmentDialog(self, kind="molding_line")
        if dialog.exec() == QDialog.Accepted:
            card = dialog.get_result()
            if not card:
                return
            record = self.calculator.add_custom_line(card)
            QMessageBox.information(
                self, "Добавлено",
                f"Линия «{record.get('name')}» сохранена в "
                f"user_data/custom_molding_lines.json и добавлена в подбор.")
            self.refresh()

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных (слот сигнала)."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Сводка фактически принятого ПАРКА, а не одной карточки линии."""
        calc = self._last_result
        plan = calc.batch_plan if calc else None
        planned = bool(plan and plan.feasible and plan.lines)
        has_positions = bool(getattr(self.project, "castings", None))
        park: list[dict] = []
        if planned:
            by_model: Dict[str, list] = {}
            for line in plan.lines:
                by_model.setdefault(line.equipment_id, []).append(line)
            for model_id, instances in sorted(by_model.items()):
                hours = sum(line.used_hours for line in instances)
                fund = sum(line.annual_fund_hours for line in instances)
                card = self.calculator.get_line_by_id(model_id)
                park.append({
                    "id": model_id,
                    "name": instances[0].equipment_name,
                    "units": len(instances),
                    "load_factor": hours / fund if fund else 0,
                    "has_shakeout": bool(card.get("has_shakeout", False)),
                    "note": f"{sum(c.molds for line in instances for c in line.campaigns):,} форм/год",
                })
        elif not has_positions and self._selected:
            park = [{
                "id": self._selected.get("id", ""),
                "name": self._selected.get("name", ""),
                "units": int(self._selected.get("_num_required", 0)),
                "load_factor": float(self._selected.get("_load_factor", 0)),
                "has_shakeout": bool(self._selected.get("has_shakeout", False)),
                "note": "Предварительная оценка без номенклатуры",
            }]
        count = sum(row["units"] for row in park)
        hours_used = sum(line.used_hours for line in plan.lines) if planned else 0.0
        hours_fund = sum(line.annual_fund_hours for line in plan.lines) if planned else 0.0
        loading = hours_used / hours_fund if hours_fund else (
            float(self._selected.get("_load_factor", 0)) if not has_positions else 0.0)
        return {
            "annual_molds_total": calc.annual_molds_total if calc else 0,
            "required_productivity": calc.required_productivity_molds_h if calc else 0.0,
            "line_name": ", ".join(row["name"] for row in park),
            "line_count": count,
            "load_factor": loading,
            "park": park,
            "batch_plan_feasible": planned,
            "batch_planning_error": calc.planning_error if calc else "",
            "batch_plan_warnings": list(plan.warnings) if plan else [],
            "material_category": calc.material_category if calc else "",
            "shakeout_in_line": bool(park) and all(row["has_shakeout"] for row in park),
        }
