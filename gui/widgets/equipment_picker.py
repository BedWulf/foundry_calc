"""Виджет выбора оборудования из нескольких вариантов."""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QRadioButton, 
    QButtonGroup, QLabel, QFrame, QScrollArea, QPushButton,
    QMessageBox, QInputDialog
)
from config import COLORS


class EquipmentCard(QFrame):
    """Карточка одного варианта оборудования.

    Ключ ``card_fields`` в словаре оборудования позволяет переопределить
    строку характеристик (используется карточками формовочных линий, где
    единицы — ф/ч и размеры опок, а не т и т/ч).
    """

    selected = Signal(dict)

    def __init__(self, equipment_data: dict, parent=None):
        super().__init__(parent)
        self.equipment_data = equipment_data
        self._build_ui()

    def _specs_text(self) -> str:
        """Собрать строку характеристик карточки (печь либо линия АФЛ)."""
        specs = self.equipment_data.get("specs", {})
        override = self.equipment_data.get("card_fields")
        if override:
            parts = []
            for key, label in override:
                value = specs.get(key)
                if value in (None, "", 0):
                    continue
                parts.append(f"{label}: {value}")
            return " | ".join(parts)

        specs_text = []
        if "capacity_t" in specs:
            specs_text.append(f"Ёмкость: {specs['capacity_t']} т")
        if "productivity_t_h" in specs:
            specs_text.append(f"Производительность: {specs['productivity_t_h']} т/ч")
        if "power_kw" in specs and specs["power_kw"] > 0:
            specs_text.append(f"Мощность: {specs['power_kw']} кВт")
        if "working_temp_C" in specs:
            specs_text.append(f"T = {specs['working_temp_C']}°C")
        return " | ".join(specs_text)

    def _build_ui(self):
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_panel']};
                border: 2px solid {COLORS['separator']};
                border-radius: 6px;
                padding: 12px;
            }}
            QFrame:hover {{
                border: 2px solid {COLORS['accent']};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        
        # Заголовок с названием
        header_layout = QHBoxLayout()
        
        self.radio = QRadioButton()
        self.radio.setStyleSheet(f"""
            QRadioButton {{
                spacing: 8px;
            }}
        """)
        header_layout.addWidget(self.radio)
        
        name_lbl = QLabel(self.equipment_data.get("name", "Unknown"))
        name_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['accent']};
                font-size: 16px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(name_lbl, 1)
        
        # Если рекомендуемое
        if self.equipment_data.get("applicable_for", {}).get("recommended", False):
            rec_lbl = QLabel("⭐ Рекомендуемое")
            rec_lbl.setStyleSheet(f"""
                QLabel {{
                    color: #FFD700;
                    font-size: 12px;
                    font-weight: bold;
                }}
            """)
            header_layout.addWidget(rec_lbl)
        
        layout.addLayout(header_layout)
        
        # Характеристики
        specs = self.equipment_data.get("specs", {})
        specs_text = []
        
        if "capacity_t" in specs:
            specs_text.append(f"Ёмкость: {specs['capacity_t']} т")
        if "productivity_t_h" in specs:
            specs_text.append(f"Производительность: {specs['productivity_t_h']} т/ч")
        if "power_kw" in specs and specs["power_kw"] > 0:
            specs_text.append(f"Мощность: {specs['power_kw']} кВт")
        if "working_temp_C" in specs:
            specs_text.append(f"T = {specs['working_temp_C']}°C")
        
        specs_lbl = QLabel(" | ".join(specs_text))
        specs_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 13px;
            }}
        """)
        layout.addWidget(specs_lbl)
        
        # Расчётные данные
        if "_num_required" in self.equipment_data:
            calc_layout = QHBoxLayout()
            
            num_lbl = QLabel(f"Требуется: {self.equipment_data['_num_required']} шт.")
            num_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_secondary']};
                    font-size: 12px;
                    font-weight: bold;
                }}
            """)
            calc_layout.addWidget(num_lbl)
            
            load_lbl = QLabel(f"К_загр = {self.equipment_data['_load_factor']:.2f}")
            load_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_secondary']};
                    font-size: 12px;
                }}
            """)
            calc_layout.addWidget(load_lbl)
            
            calc_layout.addStretch()
            layout.addLayout(calc_layout)
        
        # Описание
        if "description" in self.equipment_data:
            desc_lbl = QLabel(self.equipment_data["description"])
            desc_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_secondary']};
                    font-size: 11px;
                    font-style: italic;
                }}
            """)
            desc_lbl.setWordWrap(True)
            layout.addWidget(desc_lbl)
        
        # Сигнал
        self.radio.toggled.connect(self._on_toggled)
    
    def _on_toggled(self, checked: bool):
        if checked:
            self.selected.emit(self.equipment_data)
    
    def set_selected(self, selected: bool):
        self.radio.setChecked(selected)


class EquipmentPicker(QWidget):
    """Виджет выбора оборудования из списка вариантов."""
    
    equipment_selected = Signal(dict)
    
    def __init__(self, category: str, parent=None):
        super().__init__(parent)
        self.category = category
        self.equipment_list: list = []
        self.button_group = QButtonGroup(self)
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Заголовок
        title = QLabel(f"Выберите оборудование ({self.category})")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet(f"color: {COLORS['accent']};")
        layout.addWidget(title)
        
        # Скроллируемая область с вариантами
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLORS['bg_main']};
                border: 1px solid {COLORS['separator']};
                border-radius: 4px;
            }}
        """)
        
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(8, 8, 8, 8)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()
        
        self.scroll.setWidget(self.cards_container)
        layout.addWidget(self.scroll, 1)
    
    def set_equipment_options(
        self,
        equipment_list: List[Dict[str, Any]],
        selected_id: Optional[str] = None,
    ) -> None:
        """Установить список доступных вариантов.

        Args:
            equipment_list: карточки оборудования (первая — лучшая по скорингу)
            selected_id: id печи, которую нужно отметить (восстановление
                выбора пользователя); если None или не найдено —
                автовыбор первой (лучшей) карточки
        """
        self.equipment_list = equipment_list
        
        # Очистить старые карточки
        while self.cards_layout.count() > 1:  # Не удаляем stretch
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.button_group = QButtonGroup(self)
        
        # Создать карточки
        for i, equip in enumerate(equipment_list):
            card = EquipmentCard(equip)
            self.cards_layout.insertWidget(i, card)
            self.button_group.addButton(card.radio, i)
            
            # Сигнал
            card.selected.connect(self._on_equipment_selected)
        
        # Выбор: сохранённый пользователем либо первый (лучший) вариант
        if equipment_list:
            idx = 0
            if selected_id is not None:
                for i, equip in enumerate(equipment_list):
                    if equip.get("id") == selected_id:
                        idx = i
                        break
            button = self.button_group.button(idx)
            if button is not None:
                button.setChecked(True)
                self.equipment_selected.emit(equipment_list[idx])
    
    def _on_equipment_selected(self, equipment_data: dict):
        self.equipment_selected.emit(equipment_data)
    
    def get_selected_equipment(self) -> dict:
        """Получить выбранное оборудование."""
        checked_id = self.button_group.checkedId()
        if checked_id >= 0 and checked_id < len(self.equipment_list):
            return self.equipment_list[checked_id]
        return {}