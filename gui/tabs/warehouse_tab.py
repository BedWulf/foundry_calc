"""Вкладка «Складское хозяйство» (Разделы 8, 10 дипломного проекта).

Реализует подбор единиц хранения по «умной» архитектуре, совместимой с
остальными отделениями приложения:

  1. Оборудование фильтруется по типу склада (шихта, формовочные,
     стержневые материалы, опки, оснастка, инструмент) и по категории
     выбранного материала — см. ``applicable_for`` в
     ``data/equipment/warehouse_equip.json``.
  2. По каждому складу показывается топ-3…5 карточек компоновки
     (переиспользуется виджет ``EquipmentPicker``): название единицы,
     вместимость, количество единиц, суммарная площадь.
  3. Лучший вариант выбирается автоматически по скорингу
     (минимум избыточной площади при запасе ~12 % сверх нормы; дипломы —
     примеры, поэтому оптимальность важнее флага ``recommended``).
  4. Выбор сохраняется в ``user_data/choices.json`` (категория
     ``warehouse_units``, подсловарь по ключам складов) и восстанавливается
     при следующем запуске.
  5. Есть кнопка добавления своего склада через ``EquipmentDialog``
     (запись в ``user_data/custom_warehouses.json``).
  6. Связки: шихтовый склад считает объём от металлозавалки плавильного
     отделения, склады материалов — от тоннажей смесей, склад инструмента —
     от списочной численности рабочих (:mod:`core.workforce`).

Эталонные формулы (методичка, раздел «Склады»):
    Qраз = Mгод / 365 · Tхран / kн ;  F = Q / (h · ρ · kисп)
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
from core.warehouse import (
    WarehouseResult, calc_warehouses, total_warehouse_area,
    to_picker_options, add_custom_unit, MAX_AREA_OVERNORM_RATIO,
)
from core.user_choices import UserChoices
from gui.widgets.equipment_picker import EquipmentPicker
from gui.dialogs.equipment_dialog import EquipmentDialog

#: Порядок складов и ключи секций вкладки
WAREHOUSE_SECTIONS: List[str] = [
    "charge", "molding_sand", "core_materials",
    "flasks", "patterns", "tools",
]

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


class WarehouseTab(QWidget):
    """Вкладка складского хозяйства: нормативы и подбор единиц хранения."""

    #: Сигнал о том, что выбор складского оборудования изменился
    equipment_choice_changed = Signal(dict)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        """Инициализировать вкладку.

        Args:
            project: общая модель проекта
            parent: родительский виджет
        """
        super().__init__(parent)
        self.project = project
        self.choices = UserChoices()
        self._results: Dict[str, WarehouseResult] = {}
        self._selected: Dict[str, Dict[str, Any]] = {}
        self._pickers: Dict[str, EquipmentPicker] = {}
        self._boxes: Dict[str, QGroupBox] = {}
        self._info_labels: Dict[str, QLabel] = {}
        self._build_ui()
        self.refresh()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self) -> None:
        """Собрать интерфейс вкладки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QLabel("📦 Складское хозяйство")
        header.setObjectName("title")
        outer.addWidget(header)
        subtitle = QLabel(
            "Разделы 8, 10: запасы материалов, подбор единиц хранения "
            "и ведомость площадей (связки с плавкой, смесями и рабочей силой)")
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

        # ── Верхняя панель: материал + кнопки ──
        top_box = QGroupBox("Общие данные")
        top_box.setStyleSheet(GROUP_STYLE)
        tgrid = QGridLayout(top_box)
        tgrid.setContentsMargins(12, 12, 12, 12)
        tgrid.setHorizontalSpacing(24)

        self._material_lbl = QLabel("—")
        self._material_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._material_lbl.setStyleSheet(f"color: {COLORS['accent']};")
        self._k_lbl = QLabel("—")
        self._k_lbl.setStyleSheet(f"color: {COLORS['text_secondary']};")
        rows = [("material", "Материал / сплав"), ("k_norm", "Нормы хранения")]
        for r, (key, title) in enumerate(rows):
            name_lbl = QLabel(f"{title}:")
            name_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            tgrid.addWidget(name_lbl, r, 0)
            if key == "material":
                tgrid.addWidget(self._material_lbl, r, 1)
            else:
                tgrid.addWidget(self._k_lbl, r, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_add = QPushButton("＋ Добавить свой склад")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(BTN_STYLE)
        btn_add.clicked.connect(self._on_add_custom_warehouse)
        btn_row.addWidget(btn_add)
        btn_refresh = QPushButton("⟳ Пересчитать")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(BTN_STYLE)
        btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(btn_refresh)
        tgrid.addLayout(btn_row, len(rows), 1, Qt.AlignRight)
        self._layout.addWidget(top_box)

        # ── Секции по складам ──
        for key in WAREHOUSE_SECTIONS:
            box = QGroupBox("Склад")
            box.setStyleSheet(GROUP_STYLE)
            vbox = QVBoxLayout(box)
            vbox.setContentsMargins(12, 12, 12, 12)
            vbox.setSpacing(8)

            info_lbl = QLabel("—")
            info_lbl.setWordWrap(True)
            info_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-weight: normal;")
            vbox.addWidget(info_lbl)
            self._info_labels[key] = info_lbl

            picker = EquipmentPicker(category=f"warehouse_{key}")
            picker.equipment_selected.connect(
                lambda eq, k=key: self._on_equipment_selected(k, eq))
            vbox.addWidget(picker, 1)
            self._pickers[key] = picker
            self._boxes[key] = box
            self._layout.addWidget(box)

        # ── Блок «Итоги: ведомость площадей» ──
        result_box = QGroupBox("Ведомость площадей складов")
        result_box.setStyleSheet(GROUP_STYLE)
        rgrid = QGridLayout(result_box)
        rgrid.setContentsMargins(12, 12, 12, 12)
        rgrid.setHorizontalSpacing(24)
        self._result_labels: Dict[str, QLabel] = {}
        result_rows = [
            ("breakdown", "Площади по складам"),
            ("total_area", "Итоговая площадь складского хозяйства"),
            ("park_list", "Принятые единицы хранения"),
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
    def _info_text(self, r: WarehouseResult, area_m2: float) -> str:
        """Сформировать строку норматива для конкретной площади.

        Args:
            r: результат расчёта склада
            area_m2: принятая площадь компоновки, м²

        Returns:
            Человекочитаемая строка «база · норма · принято · риск»
        """
        req = r.requirement
        norm = req.area_norm_hint_m2 or 0.0
        overnorm = area_m2 / norm if norm > 0 else 0.0
        warn = ""
        if overnorm > MAX_AREA_OVERNORM_RATIO:
            warn = "  ⚠ значительный избыток площади"
        elif overnorm < 1.0:
            warn = "  ⚠ площадь меньше нормы"
        return (f"{req.basis} · Норма площади: {norm:,.0f} м² · Принято: "
                f"{area_m2:,.0f} м² ({overnorm:.2f}× от нормы){warn}")

    def refresh(self) -> None:
        """Пересчитать все склады и обновить карточки.

        Сохранённые ранее выборы пользователя восстанавливаются из
        ``user_data/choices.json`` (категория ``warehouse_units``); если
        оборудование больше не подходит (сменили материал/программу) —
        берётся лучший вариант по скорингу.
        """
        saved_ids = self.choices.get_operation_choices(
            self.project.project_id, UserChoices.WAREHOUSE_CATEGORY)
        results = calc_warehouses(self.project, selected_ids=saved_ids,
                                  top_n=5)
        self._results = {r.key: r for r in results}
        self._selected = {}

        category = ""
        try:
            from core.data_loader import DataLoader
            from config import DATA_DIR
            loader = DataLoader(DATA_DIR)
            category = loader.get_alloy_category(
                getattr(self.project, "selected_alloy_id", "") or "")
        except Exception:
            pass
        cat_title = CATEGORY_TITLES.get(category, category or "—")
        alloy_name = getattr(self.project, "alloy", "") or \
            getattr(self.project, "selected_alloy_id", "")
        self._material_lbl.setText(f"{cat_title} (сплав: {alloy_name})")

        norm_parts: List[str] = []
        for r in results:
            req = r.requirement
            if req.storage_days:
                short = req.title.replace("Склад ", "")
                norm_parts.append(f"{short} — {req.storage_days:.0f} сут")
        self._k_lbl.setText(("kн = 1.2 · " + "; ".join(norm_parts[:3]))
                            if norm_parts else "—")

        for r in results:
            key = r.key
            if key not in self._boxes:
                continue
            self._boxes[key].setTitle(r.title)
            info = self._info_labels[key]
            options = to_picker_options(r.units)
            if not options:
                self._pickers[key].set_equipment_options([])
                info.setText(f"{r.requirement.basis} — подходящих единиц "
                             f"хранения не найдено, добавьте свои")
                continue
            chosen = next((o for o in r.units
                           if o["id"] == saved_ids.get(key)), r.units[0])
            info.setText(self._info_text(r, float(chosen["total_area_m2"])))
            self._pickers[key].set_equipment_options(
                options, selected_id=chosen["id"])

        self._update_summary()

    def _update_summary(self) -> None:
        """Обновить ведомость площадей и принятый парк складов."""
        breakdown: List[str] = []
        park: List[str] = []
        chosen_total = 0.0
        for key in WAREHOUSE_SECTIONS:
            r = self._results.get(key)
            if not r:
                continue
            sel = self._selected.get(key) or {}
            default = r.units[0] if r.units else {}
            area = float(sel.get("total_area_m2",
                                 default.get("total_area_m2", 0.0)))
            cap = float(sel.get("total_capacity_t",
                               default.get("total_capacity_t", 0.0)))
            count = int(sel.get("_num_required",
                                default.get("unit_count", 0)))
            name = sel.get("name") or default.get("name", "—")
            chosen_total += area
            breakdown.append(f"{r.title}: {area:,.0f} м² · вместимость "
                             f"{cap:,.0f} т")
            park.append(f"{r.title}: {name} × {count}")
        self._result_labels["breakdown"].setText("\n".join(breakdown) or "—")
        self._result_labels["total_area"].setText(f"{chosen_total:,.0f} м²")
        self._result_labels["park_list"].setText("\n".join(park) or "—")

    # ─────────────────────── обработчики ───────────────────────
    def _on_equipment_selected(self, warehouse_key: str,
                               equipment: Dict[str, Any]) -> None:
        """Обработать выбор компоновки склада: сохранить и обновить итоги.

        Args:
            warehouse_key: ключ склада (``charge`` и т.п.)
            equipment: карточка выбранной компоновки
        """
        self._selected[warehouse_key] = equipment
        r = self._results.get(warehouse_key)
        if r is not None:
            r.total_area_m2 = float(equipment.get("total_area_m2",
                                                  r.total_area_m2))
            r.total_capacity_t = float(equipment.get("total_capacity_t",
                                                     r.total_capacity_t))
            self._info_labels[warehouse_key].setText(
                self._info_text(r, r.total_area_m2))

        # Сохранение выбора пользователя (требование №4)
        self.choices.save_operation_choice(
            self.project.project_id, UserChoices.WAREHOUSE_CATEGORY,
            warehouse_key, equipment)
        self._update_summary()
        self.equipment_choice_changed.emit(
            {"warehouse": warehouse_key, **equipment})

    def _on_add_custom_warehouse(self) -> None:
        """Открыть диалог добавления своего склада (требование №5)."""
        dialog = EquipmentDialog(self, kind="warehouse")
        if dialog.exec() == QDialog.Accepted:
            card = dialog.get_result()
            if not card:
                return
            record = add_custom_unit(card)
            QMessageBox.information(
                self, "Добавлено",
                f"Склад «{record.get('name')}» сохранен в "
                f"user_data/custom_warehouses.json и добавлен в подбор.")
            self.refresh()

    # ─────────────────────── внешний API ───────────────────────
    def on_project_changed(self) -> None:
        """Реактивный пересчёт при изменении исходных данных (слот сигнала)."""
        self.refresh()

    def get_summary(self) -> Dict[str, Any]:
        """Вернуть итоговые данные вкладки для сводной таблицы.

        Returns:
            Словарь: total_area_m2, areas (склад → площадь/вместимость),
            park (склад → название/кол-во единиц)
        """
        areas: Dict[str, Any] = {}
        park: Dict[str, Any] = {}
        for key in WAREHOUSE_SECTIONS:
            r = self._results.get(key)
            if not r:
                continue
            sel = self._selected.get(key) or {}
            default = r.units[0] if r.units else {}
            area = float(sel.get("total_area_m2",
                                 default.get("total_area_m2", 0.0)))
            cap = float(sel.get("total_capacity_t",
                                default.get("total_capacity_t", 0.0)))
            areas[key] = {"title": r.title, "area_m2": area,
                          "capacity_t": cap,
                          "norm_area_m2": r.requirement.area_norm_hint_m2}
            park[key] = {
                "title": r.title,
                "unit": sel.get("name") or default.get("name", ""),
                "count": int(sel.get("_num_required",
                                     default.get("unit_count", 0))),
            }
        total = sum(a["area_m2"] for a in areas.values())
        return {"total_area_m2": round(total, 1), "areas": areas, "park": park}
