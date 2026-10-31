"""Вкладка «Плавильное отделение» (Шаг 4).

Реализует требование «умного подбора оборудования»:
  1. Фильтр печей строго по категории выбранного материала (сталь/чугун/алюминий).
  2. Показ 3–5 подходящих вариантов в виде карточек с радио-кнопками
     (виджет ``EquipmentPicker``).
  3. Автоматический выбор лучшего варианта по скорингу (близость к идеальной
     загрузке 70–85 %).
  4. Сохранение выбора пользователя в ``user_data/choices.json`` и его
     восстановление при следующем запуске (``UserChoices`` + project_id).
  5. Возможность добавить своё оборудование через UI-диалог
     (``EquipmentDialog`` → запись в ``user_data/custom_furnaces.json``).
  6. Расчёты сходятся с эталоном диплома: металлозавалка 58 932 т → топ-1
     ИСТ-6М1, 6 печей, К_загр ≈ 0.84.

Эталонные формулы («Sample Diploma 2», лист 21):
    P1 = М · k_н / (Ф_д · q_печ)   — расчётное количество печей
    К_загр = М · k_н / (N_пр · Ф_д · q_печ) — коэффициент загрузки
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QGridLayout, QScrollArea, QMessageBox,
)

from config import COLORS
from core.project import Project
from core.melting import calc_metal_charge
from core.equipment_selector import EquipmentSelector
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


class MeltingTab(QWidget):
    """Вкладка плавильного отделения: расчёт завалки и подбор печей."""

    #: Сигнал о том, что выбор печи изменился (для сводки/соседних вкладок)
    furnace_choice_changed = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительний виджет
        """
        super().__init__(parent)
        self.project = project
        self.selector = EquipmentSelector()
        self.choices = UserChoices()
        self._current_options: List[Dict[str, Any]] = []
        self._selected: Dict[str, Any] = {}
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("🔥 Плавильное отделение")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel("Раздел 3: металлозавалка, выбор типа и количества печей")
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

        # ── Блок «Расчёт металлозавалки» ──
        charge_box = QGroupBox("Расчёт годовой металлозавалки (баланс металла, табл. 6 диплома)")
        charge_box.setStyleSheet(GROUP_STYLE)
        grid = QGridLayout(charge_box)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(24)
        self._charge_labels: Dict[str, QLabel] = {}
        rows = [
            ("annual_output_t", "Годовой выпуск годных отливок"),
            ("losses", "Суммарные потери (ЛП + брак + угар)"),
            ("metal_charge_t", "Металлозавалка годовая, М"),
            ("fund_hours", "Действительный фонд работы печей, Фд"),
            ("required_productivity", "Требуемая производительность, М/Фд"),
        ]
        for r, (key, title) in enumerate(rows):
            name_lbl = QLabel(f"{title}:")
            name_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: normal;")
            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            val_lbl.setStyleSheet(f"color: {COLORS['accent']};")
            grid.addWidget(name_lbl, r, 0)
            grid.addWidget(val_lbl, r, 1)
            self._charge_labels[key] = val_lbl
        self._layout.addWidget(charge_box)

        # ── Блок «Выбор оборудования» ──
        equip_box = QGroupBox("Подбор плавильных агрегатов (фильтр по материалу)")
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

        btn_add = QPushButton("＋ Добавить своё оборудование")
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
        btn_add.clicked.connect(self._on_add_custom_equipment)
        top_row.addWidget(btn_add)

        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(btn_add.styleSheet())
        btn_refresh.clicked.connect(self.refresh)
        top_row.addWidget(btn_refresh)
        vbox.addLayout(top_row)

        self.lbl_source_status = QLabel(
            "⚠ ПРЕДВАРИТЕЛЬНЫЙ ПОДБОР: старый каталог печей ещё не имеет "
            "подтверждённых паспортных источников для всех расчётных полей. "
            "Количество и загрузка печей не могут считаться окончательным "
            "проектным решением. См. «Сводка → Проверка источников»."
        )
        self.lbl_source_status.setWordWrap(True)
        self.lbl_source_status.setStyleSheet(
            f"color: {COLORS['warning']}; padding: 8px; "
            f"background-color: {COLORS['bg_panel']};"
        )
        vbox.addWidget(self.lbl_source_status)

        self.picker = EquipmentPicker(category="плавильные печи")
        self.picker.equipment_selected.connect(self._on_equipment_selected)
        vbox.addWidget(self.picker, 1)
        self._layout.addWidget(equip_box, 1)

        # ── Блок «Итоги по выбранной печи» ──
        result_box = QGroupBox("Итоговый расчёт по выбранному оборудованию")
        result_box.setStyleSheet(GROUP_STYLE)
        rgrid = QGridLayout(result_box)
        rgrid.setContentsMargins(12, 12, 12, 12)
        rgrid.setHorizontalSpacing(24)
        self._result_labels: Dict[str, QLabel] = {}
        result_rows = [
            ("furnace", "Принятая печь"),
            ("capacity", "Ёмкость тигля / производительность"),
            ("num_calc", "Расчётное количество печей (P₁)"),
            ("num_adopt", "Принятое количество печей (Nпр)"),
            ("load_factor", "Коэффициент загрузки (Кзагр)"),
        ]
        for r, (key, title) in enumerate(result_rows):
            name_lbl = QLabel(f"{title}:")
            name_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: normal;")
            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            val_lbl.setStyleSheet(f"color: {COLORS['success']};")
            rgrid.addWidget(name_lbl, r, 0)
            rgrid.addWidget(val_lbl, r, 1)
            self._result_labels[key] = val_lbl
        self._layout.addWidget(result_box)
        self._layout.addStretch()

    # ─────────────────────── данные/расчёт ───────────────────────
    def _material_category(self) -> str:
        """Определить категорию материала по selected_alloy_id проекта.

        Returns:
            Категория ('steel' / 'cast_iron' / 'aluminum'); при неизвестном
            сплаве — 'steel' как базовый вариант для сталелитейного цеха
        """
        alloy_id = getattr(self.project, "selected_alloy_id", "") or ""
        try:
            alloys = self.selector.loader.load_list("materials/alloys.json", key="alloys")
        except Exception:
            alloys = []
        for a in alloys:
            if a.get("id") == alloy_id:
                return a.get("category", "steel")
        return "steel"

    def _working_hours(self) -> float:
        """Действительный фонд времени оборудования, ч (из модели проекта)."""
        fund = float(getattr(self.project, "F_equipment_h", 3890) or 3890)
        return fund if fund > 0 else 3890.0

    def refresh(self) -> None:
        """Пересчитать завалку и обновить подбор оборудования.

        Вызывается при старте, при изменении исходных данных и по кнопке
        «Пересчитать». Сохранённый ранее выбор пользователя восстанавливается.
        """
        output = float(self.project.annual_output_t)
        charge = calc_metal_charge(
            output,
            brak_pct=self.project.brak_pct,
            litniki_pribyli_pct=self.project.litniki_pribyli_pct,
            ugar_pct=self.project.ugar_pct,
        )
        self.project.metal_charge_t = charge
        fund = self._working_hours()

        lp = self.project.litniki_pribyli_pct
        br = self.project.brak_pct
        ug = self.project.ugar_pct

        self._charge_labels["annual_output_t"].setText(f"{output:,.0f} т".replace(",", " "))
        self._charge_labels["losses"].setText(
            f"ЛП {lp}% + брак {br}% + угар {ug}%")
        self._charge_labels["metal_charge_t"].setText(f"{charge:,.0f} т".replace(",", " "))
        self._charge_labels["fund_hours"].setText(f"{fund:,.0f} ч".replace(",", " "))
        req = charge / fund if fund > 0 else 0.0
        self._charge_labels["required_productivity"].setText(f"{req:.2f} т/ч")

        category = self._material_category()
        self.lbl_material.setText(
            f"Материал: {CATEGORY_TITLES.get(category, category)} "
            f"(сплав: {getattr(self.project, 'alloy', '')})")

        options = self.selector.find_furnaces(
            material_category=category,
            annual_charge_t=charge,
            working_hours=fund,
            top_n=5,
        )
        self._current_options = options

        saved = self.choices.get_equipment_choice(self.project.project_id) or {}
        saved_id = saved.get("equipment_id")
        # Если сохранённая печь больше не подходит (сменили материал) — сброс
        if saved_id and not any(o.get("id") == saved_id for o in options):
            saved_id = None
        self.picker.set_equipment_options(options, selected_id=saved_id)

    # ─────────────────────── обработчики ───────────────────────
    def _on_equipment_selected(self, equipment: Dict[str, Any]) -> None:
        """Обработать выбор печи: пересчёт итогов и сохранение выбора."""
        self._selected = equipment
        num = int(equipment.get("_num_required", 0))
        load = float(equipment.get("_load_factor", 0.0))
        specs = equipment.get("specs", {})
        productivity = float(specs.get("productivity_t_h", 0) or 0)
        capacity = float(specs.get("capacity_t", 0) or 0)
        fund = self._working_hours()
        charge = self.project.metal_charge_t
        # Расчётное количество по формуле диплома: P1 = M·kн / (Фд·q), kн=1.0
        p1 = charge / (fund * productivity) if productivity > 0 and fund > 0 else 0.0

        self._result_labels["furnace"].setText(
            f"{equipment.get('name', '?')}"
            + (" (пользовательская)" if equipment.get("custom") else ""))
        self._result_labels["capacity"].setText(
            f"{capacity:g} т / {productivity:g} т/ч")
        self._result_labels["num_calc"].setText(f"{p1:.2f} шт")
        self._result_labels["num_adopt"].setText(f"{num} шт")
        color = COLORS["success"] if 0.7 <= load <= 0.85 else COLORS["warning"]
        self._result_labels["load_factor"].setText(f"{load:.3f}")
        self._result_labels["load_factor"].setStyleSheet(f"color: {color};")

        # Сохранение выбора пользователя (требование №4)
        self.choices.save_equipment_choice(self.project.project_id, equipment)
        self.furnace_choice_changed.emit(equipment)

    def _on_add_custom_equipment(self) -> None:
        """Открыть диалог добавления своего оборудования (требование №5)."""
        dialog = EquipmentDialog(self)
        if dialog.exec() == EquipmentDialog.Accepted:
            card = dialog.get_result()
            if not card:
                return
            record = self.selector.add_custom_furnace(card)
            QMessageBox.information(
                self, "Добавлено",
                f"Печь «{record.get('name')}» сохранена в "
                f"user_data/custom_furnaces.json и добавлена в подбор.")
            self.refresh()

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных (слот сигнала)."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь с ключами: metal_charge_t, furnace_name, furnace_count,
            load_factor, material_category
        """
        return {
            "metal_charge_t": round(self.project.metal_charge_t, 1),
            "furnace_name": self._selected.get("name", ""),
            "furnace_count": int(self._selected.get("_num_required", 0)),
            "load_factor": float(self._selected.get("_load_factor", 0.0)),
            "material_category": self._material_category(),
            "capacity_charge_t_year": (
                float(self._selected.get("specs", {}).get("productivity_t_h", 0) or 0)
                * int(self._selected.get("_num_required", 0))
                * self._working_hours()
                if self._selected.get("id") else None),
            "effective_fund_h": self._working_hours(),
            "capacity_charge_t_h": (
                float(self._selected.get("specs", {}).get("productivity_t_h", 0) or 0)
                * int(self._selected.get("_num_required", 0))
                if self._selected.get("id") and
                float(self._selected.get("specs", {}).get("productivity_t_h", 0) or 0) > 0
                else None),
        }
