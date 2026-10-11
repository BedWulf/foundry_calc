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
    """Модальное окно «Добавить своё оборудование»."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Добавить своё оборудование")
        self.setMinimumWidth(420)
        self._result: Optional[Dict[str, Any]] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel("Печь будет сохранена в user_data/custom_furnaces.json "
                      "и появится в подборе для выбранных материалов.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(hint)

        form = QFormLayout()
        self.edit_name = QLineEdit("Печь индивидуальная")
        self.edit_type = QLineEdit("custom")
        self.spin_capacity = QDoubleSpinBox()
        self.spin_capacity.setRange(0.01, 200.0)
        self.spin_capacity.setValue(1.0)
        self.spin_capacity.setSuffix(" т")
        self.spin_productivity = QDoubleSpinBox()
        self.spin_productivity.setRange(0.01, 100.0)
        self.spin_productivity.setValue(1.0)
        self.spin_productivity.setSuffix(" т/ч")
        form.addRow("Название:", self.edit_name)
        form.addRow("Тип/марка:", self.edit_type)
        form.addRow("Ёмкость:", self.spin_capacity)
        form.addRow("Производительность:", self.spin_productivity)
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
