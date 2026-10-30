"""Диалог добавления нового материала."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QDoubleSpinBox, QComboBox, QPushButton,
    QMessageBox, QDialogButtonBox,
)
from config import COLORS


class AddMaterialDialog(QDialog):
    """Диалог добавления нового сплава."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить новый материал")
        self.setMinimumSize(580, 500)
        self.resize(700, 650)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        # Заголовок
        title = QLabel("Новый сплав")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet(f"color: {COLORS['accent']}; padding: 8px 0;")
        layout.addWidget(title)

        # Форма
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        # Категория
        self.combo_category = QComboBox()
        self.combo_category.addItems(["Сталь литейная", "Серый чугун", "Алюминиевые сплавы"])
        self.combo_category.setStyleSheet(self._input_style())
        form.addRow("Категория:", self.combo_category)

        # Название
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Например: СЧ35")
        self.edit_name.setStyleSheet(self._input_style())
        form.addRow("Название:", self.edit_name)

        # ГОСТ
        self.edit_gost = QLineEdit()
        self.edit_gost.setPlaceholderText("ГОСТ 1412-85")
        self.edit_gost.setStyleSheet(self._input_style())
        form.addRow("ГОСТ:", self.edit_gost)

        # Плотность
        self.spin_density = QDoubleSpinBox()
        self.spin_density.setRange(1000, 20000)
        self.spin_density.setValue(7800)
        self.spin_density.setSuffix(" кг/м³")
        self.spin_density.setStyleSheet(self._input_style())
        form.addRow("Плотность:", self.spin_density)

        # Температура плавления
        self.spin_melting = QDoubleSpinBox()
        self.spin_melting.setRange(500, 2000)
        self.spin_melting.setValue(1520)
        self.spin_melting.setSuffix(" °C")
        self.spin_melting.setStyleSheet(self._input_style())
        form.addRow("T плавления:", self.spin_melting)

        # Температура заливки
        self.spin_pouring = QDoubleSpinBox()
        self.spin_pouring.setRange(500, 2000)
        self.spin_pouring.setValue(1600)
        self.spin_pouring.setSuffix(" °C")
        self.spin_pouring.setStyleSheet(self._input_style())
        form.addRow("T заливки:", self.spin_pouring)

        # Усадка
        self.spin_shrinkage = QDoubleSpinBox()
        self.spin_shrinkage.setRange(0, 5)
        self.spin_shrinkage.setDecimals(1)
        self.spin_shrinkage.setValue(2.0)
        self.spin_shrinkage.setSuffix(" %")
        self.spin_shrinkage.setStyleSheet(self._input_style())
        form.addRow("Усадка:", self.spin_shrinkage)

        layout.addLayout(form)

        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Добавить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.setStyleSheet(self._button_style())
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _input_style(self) -> str:
        return f"""
            QLineEdit, QComboBox, QDoubleSpinBox {{
                background-color: #111A25;
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['separator']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
                min-height: 28px;
            }}
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {COLORS['accent']};
            }}
        """

    def _button_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {COLORS['accent']};
                color: {COLORS['bg_main']};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #F3B989; }}
        """

    def _on_accept(self) -> None:
        if not self.edit_name.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите название материала")
            return
        self.accept()

    def get_material_data(self) -> dict:
        """Вернуть введённые данные."""
        category_map = {
            "Сталь литейная": "steel",
            "Серый чугун": "cast_iron",
            "Алюминиевые сплавы": "aluminum",
        }
        category = category_map.get(self.combo_category.currentText(), "steel")
        
        # Генерируем ID
        name = self.edit_name.text().strip()
        alloy_id = f"{category}_{name.lower().replace(' ', '_').replace('л', 'L').replace('ч', 'Ch')}"
        
        return {
            "id": alloy_id,
            "name": name,
            "gost": self.edit_gost.text().strip(),
            "category": category,
            "density_kg_m3": self.spin_density.value(),
            "melting_temp_C": self.spin_melting.value(),
            "pouring_temp_C": self.spin_pouring.value(),
            "shrinkage_pct": self.spin_shrinkage.value(),
            "burnout_pct": {"C": 10, "Si": 0, "Mn": 10, "P": 0, "S": 5},
            "recommended_furnace_types": ["induction_crucible"],
            "recommended_molding_method": "machine_wet_sand",
            "mix_composition_id": f"EFS_{category}",
            "description": f"Пользовательский сплав: {name}",
            "custom": True,
        }