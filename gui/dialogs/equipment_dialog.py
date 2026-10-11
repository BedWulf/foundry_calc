"""Диалог добавления пользовательского оборудования (требование №5).

Базовая реализация: форма вводит название, тип, ёмкость, производительность
и категории материалов, для которых применима печь. Результат — словарь в
формате карточки справочника `data/equipment/furnaces.json`
(флаг custom=True проставляет EquipmentSelector.add_custom_furnace).
"""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    }

    def __init__(self, parent: Optional[QWidget] = None,
                 kind: str = "furnace"):
        """Инициализировать диалог.

        Args:
            parent: родительский виджет
            kind: вид оборудования ("furnace" | "molding_line")
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

        hint_text = (
            "Линия будет сохранена в user_data/custom_molding_lines.json "
            "и появится в подборе для выбранных материалов."
            if self._kind == "molding_line" else
            "Печь будет сохранена в user_data/custom_furnaces.json "
            "и появится в подборе для выбранных материалов."
        )
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(hint)

        form = QFormLayout()
        name_default = ("Формовочная линия индивидуальная"
                        if self._kind == "molding_line"
                        else "Печь индивидуальная")
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
        """Собрать карточку печи и закрыть диалог с accepted."""
        materials: List[str] = [c for c, cb in self.checks.items()
                                if cb.isChecked()]
        self._result = {
            "name": self.edit_name.text().strip() or "Печь без названия",
            "type": self.edit_type.text().strip() or "custom",
            "description": "Пользовательское оборудование",
            "specs": {
                "capacity_t": self.spin_capacity.value(),
                "productivity_t_h": self.spin_productivity.value(),
            },
            "applicable_for": {
                "materials": materials,
                "casting_mass_range_kg": [0, 10000],
                "recommended": False,
            },
        }
        self.accept()

    def get_result(self) -> Optional[Dict[str, Any]]:
        """Возвращает собранную карточку печи или None (отмена)."""
        return self._result
