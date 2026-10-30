"""Виджет выбора оборудования из нескольких вариантов."""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QRadioButton, 
    QButtonGroup, QLabel, QFrame, QScrollArea, QPushButton,
    QMessageBox, QInputDialog, QDialog, QDialogButtonBox, QApplication
)
from config import COLORS


class EquipmentCard(QFrame):
    """Карточка одного варианта оборудования.

    Ключ ``card_fields`` в словаре оборудования позволяет переопределить
    строку характеристик (используется карточками формовочных линий, где
    единицы — ф/ч и размеры опок, а не т и т/ч; стержневые машины задают
    часы работы парка в ключе ``_hours_required`` — тогда вместо «Требуется
    N шт.» показывается «N ч работы парка в год»).
    """

    selected = Signal(dict)

    def __init__(self, equipment_data: dict, parent=None):
        super().__init__(parent)
        self.equipment_data = equipment_data
        self._build_ui()

    def _specs_text(self) -> str:
        """Собрать строку характеристик карточки (печь / АФЛ / стержневая машина)."""
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

        # Стержневые машины: свои единицы (цикл, гнезда, час. произв., опочный размер)
        if "cycle_time_s" in specs or "hourly_output_cores_h" in specs:
            parts = []
            if specs.get("box_size_mm"):
                parts.append(f"Ящик: {specs['box_size_mm']} мм")
            if specs.get("cycle_time_s"):
                parts.append(f"Цикл: {specs['cycle_time_s']:g} с")
            if specs.get("cavities_per_box"):
                parts.append(f"Гнезд: {specs['cavities_per_box']:g}")
            if specs.get("hourly_output_cores_h"):
                parts.append(f"Производительность: {specs['hourly_output_cores_h']:g} ст/ч")
            if specs.get("installed_power_kw"):
                parts.append(f"Мощность: {specs['installed_power_kw']:g} кВт")
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
        name_lbl.setWordWrap(True)
        header_layout.addWidget(name_lbl, 1)
        
        # Если рекомендуемое
        if self.equipment_data.get("applicable_for", {}).get("recommended", False):
            rec_lbl = QLabel("⭐ Рекомендуемое")
            rec_lbl.setStyleSheet(f"""
                QLabel {{
                    color: #E8A66F;
                    font-size: 12px;
                    font-weight: bold;
                }}
            """)
            header_layout.addWidget(rec_lbl)
        
        layout.addLayout(header_layout)

        # Характеристики (печь либо линия АФЛ — см. _specs_text)
        specs_lbl = QLabel(self._specs_text())
        specs_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 13px;
            }}
        """)
        specs_lbl.setWordWrap(True)
        layout.addWidget(specs_lbl)
        
        # Расчётные данные
        if "_num_required" in self.equipment_data:
            calc_layout = QHBoxLayout()

            hours = self.equipment_data.get("_hours_required")
            if hours is not None:
                num_lbl = QLabel(
                    f"Загрузка парка: {float(hours):,.0f} ч/год".replace(",", " "))
            else:
                num_lbl = QLabel(
                    f"Требуется: {self.equipment_data['_num_required']} шт.")
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
    
    def __init__(self, category: str, parent=None, *, allow_expand: bool = True):
        super().__init__(parent)
        self.category = category
        self._allow_expand = allow_expand
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
        title_row = QHBoxLayout()
        title_row.addWidget(title, 1)
        if self._allow_expand:
            self.btn_expand = QPushButton("↗ Развернуть выбор")
            self.btn_expand.setToolTip(
                "Открыть большой список оборудования, выбрать модель и применить")
            self.btn_expand.clicked.connect(self._open_expanded)
            title_row.addWidget(self.btn_expand)
        layout.addLayout(title_row)
        
        # Скроллируемая область с вариантами
        self.scroll = QScrollArea()
        self.scroll.setMinimumHeight(420)
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
        
        # Очистить старые карточки: удалить виджеты и отвязать radio-кнопки
        # от группы. Без removeButton кнопки оставались в старой QButtonGroup
        # и на экране одновременно подсвечивалось по две карточки (дефект
        # проявлялся при повторных refresh(): смена материала/программы).
        while self.cards_layout.count() > 1:  # Не удаляем stretch
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                for btn in widget.findChildren(QRadioButton):
                    self.button_group.removeButton(btn)
                widget.deleteLater()
                widget.setParent(None)

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
                # A programmatic check toggles the radio button and emits
                # card.selected; suppress that intermediate event. We must
                # notify the tab once, after options are fully installed.
                self._setting_options = True
                try:
                    button.setChecked(True)
                finally:
                    self._setting_options = False
                self._emit_selection(equipment_list[idx])

    def _emit_selection(self, equipment_data: dict) -> None:
        """Эмитировать ``equipment_selected``, подавляя рекурсивные refresh().

        Обработчики сигнала во вкладках часто вызывают ``refresh()``, который
        снова попадает в :meth:`set_equipment_options` и эмитит выбор обратно.
        Без защиты получается каскад «формовка → стержни → склады → площади →
        формовка …», способный зациклиться при смене материала проекта. Флаг
        ``_blocked`` гарантирует: внешний слушатель получает ровно одно
        уведомление о выборе, вложенные (reentrant) эмиссии игнорируются.
        """
        if getattr(self, "_blocked", False):
            return
        self._blocked = True
        try:
            self.equipment_selected.emit(equipment_data)
        finally:
            self._blocked = False

    def _on_equipment_selected(self, equipment_data: dict):
        if not getattr(self, "_setting_options", False):
            self._emit_selection(equipment_data)
    def _open_expanded(self) -> None:
        """Большой выбор оборудования с сохранением выбора только при OK."""
        if not self.equipment_list:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Выбор оборудования — полный просмотр")
        dialog.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        dialog.setSizeGripEnabled(True)
        dialog.setMinimumSize(740, 480)
        layout = QVBoxLayout(dialog)
        expanded = EquipmentPicker(self.category, dialog, allow_expand=False)
        expanded.set_equipment_options(
            self.equipment_list,
            selected_id=self.get_selected_equipment().get("id"))
        layout.addWidget(expanded, 1)
        controls = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Ok).setText("Применить")
        controls.button(QDialogButtonBox.Cancel).setText("Отмена")
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        screen = QApplication.primaryScreen()
        if screen is not None:
            rect = screen.availableGeometry()
            dialog.resize(
                max(740, min(1250, int(rect.width() * .90))),
                max(480, min(840, int(rect.height() * .84))))
        else:
            dialog.resize(1120, 760)

        if dialog.exec() == QDialog.Accepted:
            choice = expanded.get_selected_equipment()
            if not choice:
                return
            for idx, equip in enumerate(self.equipment_list):
                if equip.get("id") == choice.get("id"):
                    button = self.button_group.button(idx)
                    if button is not None:
                        # Update radio with signal blocked: the listeners
                        # receive exactly one equipment_selected signal.
                        self._setting_options = True
                        try:
                            button.setChecked(True)
                        finally:
                            self._setting_options = False
                    self._emit_selection(equip)
                    break

    def get_selected_equipment(self) -> dict:
        """Получить выбранное оборудование."""
        checked_id = self.button_group.checkedId()
        if checked_id >= 0 and checked_id < len(self.equipment_list):
            return self.equipment_list[checked_id]
        return {}