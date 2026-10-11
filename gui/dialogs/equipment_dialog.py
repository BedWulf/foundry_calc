"""Диалог добавления пользовательского оборудования (требование №5).

Базовая реализация: форма вводит название, тип, ёмкость, производительность
и категории материалов, для которых применима печь. Результат — словарь в
формате карточки справочника `data/equipment/furnaces.json`
(флаг custom=True проставляет EquipmentSelector.add_custom_furnace).
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QDialogButtonBox, QCheckBox, QGroupBox, QWidget,
)

from config import COLORS

# Категория материала -> человекочитаемое имя
CATEGORY_NAMES: Dict[str, str] = {
    "steel": "Сталь",
    "cast_iron": "Чугун",
    "aluminum": "Алюминий",
}


class EquipmentDialog(QDialog):
    """Модальное окно «Добавить своё оборудование».

    Атрибут ``KIND``: ``"furnace"`` — плавильный агрегат (ёмкость в т,
    производительность в т/ч), ``"molding_line"`` — формовочная линия
    (макс. металлоемкость формы в кг, цикловая производительность в ф/ч).
    """

    #: Единицы и подписи полей формы для каждого вида оборудования
    _KIND_META: Dict[str, Dict[str, Any]] = {
        "furnace": {
            "title": "Добавить своё оборудование",
            "capacity_label": "Ёмкость:",
            "capacity_suffix": " т",
            "capacity_range": (0.01, 200.0),
            "capacity_default": 1.0,
            "prod_label": "Производительность:",
            "prod_suffix": " т/ч",
            "prod_range": (0.01, 100.0),
            "prod_default": 1.0,
            "type_default": "custom",
        },
        "molding_line": {
            "title": "Добавить свою формовочную линию",
            "capacity_label": "Макс. металлоемкость формы:",
            "capacity_suffix": " кг",
            "capacity_range": (1.0, 5000.0),
            "capacity_default": 70.0,
            "prod_label": "Цикловая производительность:",
            "prod_suffix": " ф/ч",
            "prod_range": (1.0, 1000.0),
            "prod_default": 240.0,
            "type_default": "custom_molding",
        },
        "cleaning_machine": {
            "title": "Добавить своё очистное оборудование",
            "capacity_label": "Макс. масса отливки:",
            "capacity_suffix": " кг",
            "capacity_range": (0.1, 5000.0),
            "capacity_default": 100.0,
            "prod_label": "Производительность:",
            "prod_suffix": " т/ч",
            "prod_range": (0.01, 500.0),
            "prod_default": 8.0,
            "type_default": "custom_cleaning",
        },
        "core_machine": {
            "title": "Добавить свою стержневую машину",
            "capacity_label": "Гнезд в ящике:",
            "capacity_suffix": " гнезд",
            "capacity_range": (1.0, 64.0),
            "capacity_default": 2.0,
            "prod_label": "Время цикла:",
            "prod_suffix": " с",
            "prod_range": (1.0, 600.0),
            "prod_default": 30.0,
            "type_default": "custom_core",
        },
        "mixer": {
            "title": "Добавить смесеприготовительную установку",
            "capacity_label": "Объём замеса:",
            "capacity_suffix": " м³",
            "capacity_range": (0.01, 50.0),
            "capacity_default": 3.0,
            "prod_label": "Производительность:",
            "prod_suffix": " м³/ч",
            "prod_range": (0.01, 500.0),
            "prod_default": 12.0,
            "type_default": "custom_mixer",
        },
    }

    def __init__(self, parent: Optional[QWidget] = None,
                 kind: str = "furnace"):
        """Инициализировать диалог.

        Args:
            parent: родительский виджет
            kind: вид оборудования
                ("furnace" | "molding_line" | "core_machine" | "cleaning_machine")
        """
        super().__init__(parent)
        if kind not in self._KIND_META:
            raise ValueError(f"Неизвестный вид оборудования: {kind}")
        self._kind = kind
        meta = self._KIND_META[kind]
        self.setWindowTitle(str(meta["title"]))
        self.setMinimumWidth(420)
        self._result: Optional[Dict[str, Any]] = None
        self._build_ui()

    def _build_ui(self) -> None:
        meta = self._KIND_META[self._kind]
        layout = QVBoxLayout(self)

        hint_text = {
            "cleaning_machine": (
                "Установка будет сохранена в user_data/custom_cleaning_machines.json "
                "и появится в подборе для выбранных материалов и позиций."),
            "molding_line": (
                "Линия будет сохранена в user_data/custom_molding_lines.json "
                "и появится в подборе для выбранных материалов."),
            "core_machine": (
                "Машина будет сохранена в user_data/custom_core_machines.json "
                "и появится в подборе для выбранных материалов."),
        }.get(self._kind, (
            "Печь будет сохранена в user_data/custom_furnaces.json "
            "и появится в подборе для выбранных материалов."))
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(hint)

        form = QFormLayout()
        name_default = {
            "cleaning_machine": "Установка очистки индивидуальная",
            "molding_line": "Формовочная линия индивидуальная",
            "core_machine": "Стержневая машина индивидуальная",
        }.get(self._kind, "Печь индивидуальная")
        self.edit_name = QLineEdit(name_default)
        self.edit_type = QLineEdit(str(meta["type_default"]))
        self.spin_capacity = QDoubleSpinBox()
        self.spin_capacity.setRange(*meta["capacity_range"])
        self.spin_capacity.setValue(float(meta["capacity_default"]))
        self.spin_capacity.setSuffix(str(meta["capacity_suffix"]))
        self.spin_productivity = QDoubleSpinBox()
        self.spin_productivity.setRange(*meta["prod_range"])
        self.spin_productivity.setValue(float(meta["prod_default"]))
        self.spin_productivity.setSuffix(str(meta["prod_suffix"]))
        form.addRow("Название:", self.edit_name)
        form.addRow("Тип/марка:", self.edit_type)
        form.addRow(str(meta["capacity_label"]), self.spin_capacity)
        form.addRow(str(meta["prod_label"]), self.spin_productivity)
        layout.addLayout(form)

        self.operation_combo: Optional[QComboBox] = None
        if self._kind == "cleaning_machine":
            op_group = QGroupBox("Позиция техпроцесса")
            ov = QVBoxLayout(op_group)
            self.operation_combo = QComboBox()
            try:
                from core.cleaning import OPERATION_TITLES
                for key, title in OPERATION_TITLES.items():
                    self.operation_combo.addItem(title, key)
            except Exception:  # pragma: no cover - страховка от циклов импорта
                self.operation_combo.addItem("Очистка и удаление стержней",
                                             "shot_blasting")
            self.operation_combo.setCurrentIndex(2)
            ov.addWidget(self.operation_combo)
            layout.addWidget(op_group)
        elif self._kind == "mixer":
            op_group = QGroupBox("Операция отделения")
            ov = QVBoxLayout(op_group)
            self.operation_combo = QComboBox()
            try:
                from core.sand_prep import OPERATION_TITLES as MIX_OP_TITLES
                for key, title in MIX_OP_TITLES.items():
                    self.operation_combo.addItem(title, key)
            except Exception:  # pragma: no cover - страховка от циклов импорта
                self.operation_combo.addItem("Приготовление формовочной смеси",
                                             "molding_mix")
            ov.addWidget(self.operation_combo)
            layout.addWidget(op_group)

        group = QGroupBox("Применима для материалов")
        gbox = QVBoxLayout(group)
        self.checks: Dict[str, QCheckBox] = {}
        for cat, title in CATEGORY_NAMES.items():
            cb = QCheckBox(title)
            cb.setChecked(cat == "steel")
            gbox.addWidget(cb)
            self.checks[cat] = cb
        layout.addWidget(group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        """Собрать карточку оборудования (печь/линия/стержневая машина).

        Поля «ёмкость» и «производительность» переиспользуются под разные
        виды: для печи — т и т/ч; для линии — кг металла в форме и ф/ч;
        для стержневой машины — число гнёзд в ящике и время цикла, с, при
        этом часовая производительность считается автоматически
        (3600/цикл * гнёзда).
        """
        materials: List[str] = [c for c, cb in self.checks.items()
                                if cb.isChecked()]
        name = self.edit_name.text().strip() or "Оборудование без названия"
        etype = self.edit_type.text().strip() or str(
            self._KIND_META[self._kind]["type_default"])
        cap = float(self.spin_capacity.value())
        prod = float(self.spin_productivity.value())

        specs: Dict[str, Any]
        mass_range_max: float
        if self._kind == "molding_line":
            specs = {"flask_size_mm": "индивидуальная",
                     "nominal_productivity_molds_h": prod,
                     "max_mold_metal_kg": cap}
            mass_range_max = cap
        elif self._kind == "cleaning_machine":
            specs = {"productivity_t_h": prod}
            mass_range_max = cap
        elif self._kind == "core_machine":
            # cap — гнёзда, prod — цикл, с
            hourly = (3600.0 / prod) * cap if prod > 0 else 0.0
            specs = {"box_size_mm": "индивидуальный",
                     "cycle_time_s": prod,
                     "cavities_per_box": cap,
                     "hourly_output_cores_h": round(hourly, 1)}
            mass_range_max = 500.0
        elif self._kind == "mixer":
            # cap — объём замеса, м³; prod — производительность, м³/ч
            specs = {"batch_volume_m3": cap, "productivity_m3_h": prod}
            mass_range_max = 10000.0
        else:
            specs = {"capacity_t": cap, "productivity_t_h": prod}
            mass_range_max = 10000.0

        self._result = {
            "name": name,
            "type": etype,
            "description": "Пользовательское оборудование",
            "specs": specs,
            "applicable_for": {
                "materials": materials,
                "casting_mass_range_kg": [0, mass_range_max],
                "recommended": False,
            },
        }
        if self._kind == "mixer":
            unit = "t_h" if prod < 2.0 else "m3_h"
            self._result["unit"] = unit
            if unit == "t_h":
                self._result["specs"] = {"productivity_t_h": prod}
        if self.operation_combo is not None and self._kind != "mixer":
            self._result["applicable_for"]["operations"] = [
                str(self.operation_combo.currentData())]
        elif self.operation_combo is not None:
            # для смесеприготовления операция — обязательный ключ подбора
            self._result["operation"] = str(
                self.operation_combo.currentData())
        self.accept()

    def get_result(self) -> Optional[Dict[str, Any]]:
        """Возвращает собранную карточку оборудования или None (отмена)."""
        return self._result
