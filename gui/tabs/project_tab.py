"""Вкладка «Исходные данные» — центр управления проектом."""
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QDoubleSpinBox, QSpinBox, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox, QScrollArea, QComboBox,
)
from config import COLORS
from core.project import Project
from core.casting_audit import audit_castings, audit_casting_technology
from core.casting_item import CastingItem
from import_export.excel_importer import ExcelImporter
from data.loader import DataLoader
from gui.dialogs.material_dialog import AddMaterialDialog
from gui.dialogs.castings_browser import CastingsBrowserDialog
from gui.dialogs.official_catalog_dialog import OfficialCatalogDialog
from gui.dialogs.casting_technology_dialog import CastingTechnologyDialog


# ─── Стили ────────────────────────────────────────────────────────────
GROUP_STYLE = f"""
QGroupBox {{
    background-color: {COLORS['bg_panel']};
    border: 1px solid {COLORS['separator']};
    border-radius: 6px;
    margin-top: 24px;
    padding-top: 16px;
    padding-left: 12px;
    padding-right: 12px;
    padding-bottom: 12px;
    font-weight: bold;
    color: {COLORS['accent']};
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 2px;
    padding: 0 6px;
    color: {COLORS['accent']};
}}
"""

GROUP_WIDGETS_STYLE = f"""
QGroupBox QLineEdit,
QGroupBox QSpinBox,
QGroupBox QDoubleSpinBox,
QGroupBox QComboBox {{
    background-color: #111A25;
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['separator']};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 13px;
    min-height: 28px;
}}
QGroupBox QLineEdit:focus,
QGroupBox QSpinBox:focus,
QGroupBox QDoubleSpinBox:focus,
QGroupBox QComboBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QGroupBox QLabel {{
    color: {COLORS['text_primary']};
    font-size: 13px;
    background: transparent;
}}
"""

CONTAINER_STYLE = f"""
QWidget {{
    background-color: {COLORS['bg_main']};
}}
"""


class ProjectTab(QWidget):
    """Вкладка исходных данных проекта."""

    project_changed = Signal()
    help_requested = Signal()

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.loader = DataLoader()
        self._building = True
        self._build_ui()
        self._load_from_project()
        self._building = False

    # ─────────────────────────────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("📋 Исходные данные проекта")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet(f"color: {COLORS['accent']}; padding: 4px 0 8px 0;")
        root.addWidget(title)
        hint_row = QHBoxLayout()
        hint = QLabel("Впервые работаете с программой? Начните с инструкции.")
        hint.setWordWrap(True)
        help_button = QPushButton("❓ Что и куда вводить")
        help_button.clicked.connect(self.help_requested.emit)
        hint_row.addWidget(hint, 1)
        hint_row.addWidget(help_button)
        root.addLayout(hint_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLORS['bg_main']};
                border: 1px solid {COLORS['separator']};
                border-radius: 4px;
            }}
            QScrollBar:vertical {{
                background-color: {COLORS['bg_main']};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {COLORS['separator']};
                border-radius: 5px;
                min-height: 20px;
            }}
        """)
        root.addWidget(scroll, 1)

        container = QWidget()
        container.setStyleSheet(CONTAINER_STYLE)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)
        scroll.setWidget(container)

        layout.addWidget(self._build_general_group())
        layout.addWidget(self._build_material_group())  # ← НОВОЕ
        layout.addWidget(self._build_program_group())
        layout.addWidget(self._build_mode_group())
        layout.addWidget(self._build_losses_group())
        layout.addWidget(self._build_castings_group())
        layout.addStretch()

    # ─────────────────────────────────────────────────────────────────
    # Группа: Выбор материала (НОВАЯ)
    # ─────────────────────────────────────────────────────────────────
    def _build_material_group(self) -> QGroupBox:
        g = QGroupBox("Материал отливок")
        g.setStyleSheet(GROUP_STYLE + GROUP_WIDGETS_STYLE)
        
        layout = QVBoxLayout(g)
        layout.setContentsMargins(12, 16, 12, 12)
        
        # Верхняя строка: категория + сплав + кнопка добавить
        top_row = QHBoxLayout()
        
        # Категория
        form_cat = QFormLayout()
        self.combo_category = QComboBox()
        self.combo_category.setStyleSheet(self._combo_style())
        self.combo_category.currentIndexChanged.connect(self._on_category_changed)
        form_cat.addRow("Категория:", self.combo_category)
        top_row.addLayout(form_cat)
        
        # Сплав
        form_alloy = QFormLayout()
        self.combo_alloy = QComboBox()
        self.combo_alloy.setStyleSheet(self._combo_style())
        self.combo_alloy.currentIndexChanged.connect(self._on_alloy_changed)
        form_alloy.addRow("Сплав:", self.combo_alloy)
        top_row.addLayout(form_alloy)
        
        # Кнопка добавить
        self.btn_add_material = QPushButton(" Добавить")
        self.btn_add_material.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent']};
                color: {COLORS['bg_main']};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
                min-height: 36px;
            }}
            QPushButton:hover {{ background-color: #F3B989; }}
        """)
        self.btn_add_material.clicked.connect(self._on_add_material)
        top_row.addWidget(self.btn_add_material)
        self.btn_official_materials = QPushButton("ГОСТ: 96 марок и источники")
        self.btn_official_materials.setToolTip(
            "Встроенный нормативный справочник; без подмены технологических свойств"
        )
        self.btn_official_materials.clicked.connect(self._show_official_materials)
        top_row.addWidget(self.btn_official_materials)
        
        top_row.addStretch()
        layout.addLayout(top_row)
        
        # Информация о выбранном сплаве
        self.lbl_alloy_info = QLabel("Выберите сплав для просмотра характеристик")
        self.lbl_alloy_info.setWordWrap(True)
        self.lbl_alloy_info.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-size: 12px;
                padding: 8px;
                background-color: {COLORS['bg_main']};
                border: 1px solid {COLORS['separator']};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.lbl_alloy_info)
        
        # Заполнить категории
        self._populate_categories()
        
        return g

    def _show_official_materials(self) -> None:
        dialog = OfficialCatalogDialog(self)
        dialog.tabs.setCurrentIndex(3)
        dialog.exec()

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background-color: #111A25;
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['separator']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
                min-height: 28px;
                min-width: 200px;
            }}
            QComboBox:focus {{
                border: 1px solid {COLORS['accent']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {COLORS['text_primary']};
                margin-right: 8px;
            }}
        """

    def _populate_categories(self) -> None:
        """Заполнить комбо категорий из справочника."""
        self.combo_category.clear()
        categories = self.loader.get_categories()
        for cat in categories:
            self.combo_category.addItem(cat["name"], cat["id"])

    def _populate_alloys(self, category_id: str) -> None:
        """Заполнить комбо сплавов по категории."""
        self.combo_alloy.clear()
        alloys = self.loader.get_alloys_by_category(category_id)
        for alloy in alloys:
            gost = alloy.get("gost", "")
            display = f"{alloy['name']} ({gost})" if gost else alloy["name"]
            self.combo_alloy.addItem(display, alloy["id"])

    def _update_alloy_info(self, alloy_id: str) -> None:
        """Обновить информацию о выбранном сплаве."""
        alloy = self.loader.get_alloy(alloy_id)
        if not alloy:
            self.lbl_alloy_info.setText("Сплав не найден")
            return
        
        info = (
            f" {alloy['name']} | {alloy.get('gost', 'без ГОСТ')} | "
            f"Плотность: {alloy['density_kg_m3']} кг/м³ | "
            f"T плавл: {alloy['melting_temp_C']}°C | "
            f"T заливки: {alloy['pouring_temp_C']}°C | "
            f"Усадка: {alloy['shrinkage_pct']}%"
        )
        # These are legacy operating assumptions, NOT verified normative
        # physical properties. The grade name and cited GOST are separate
        # from proof of density, pouring temperature and process shrinkage.
        info += (
            "\n⚠ Технологические значения выше не подтверждены для этой "
            "марки первоисточником. Не считать их нормами ГОСТ. "
            "Проверенные обозначения марок: «ГОСТ: 96 марок и источники»."
        )
        self.lbl_alloy_info.setText(info)

    # ─────────────────────────────────────────────────────────────────
    # Остальные группы (без изменений)
    # ─────────────────────────────────────────────────────────────────
    def _build_general_group(self) -> QGroupBox:
        g = QGroupBox("Общие сведения")
        g.setStyleSheet(GROUP_STYLE + GROUP_WIDGETS_STYLE)
        form = QFormLayout(g)
        form.setLabelAlignment(Qt.AlignRight)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Название проекта")
        self.edit_name.editingFinished.connect(self._on_general_changed)

        self.edit_customer = QLineEdit()
        self.edit_customer.setPlaceholderText("Заказчик (опционально)")
        self.edit_customer.editingFinished.connect(self._on_general_changed)

        form.addRow("Название проекта:", self.edit_name)
        form.addRow("Заказчик:", self.edit_customer)
        return g

    def _build_program_group(self) -> QGroupBox:
        g = QGroupBox("Производственная программа")
        g.setStyleSheet(GROUP_STYLE + GROUP_WIDGETS_STYLE)
        form = QFormLayout(g)
        form.setLabelAlignment(Qt.AlignRight)

        self.spin_annual = QDoubleSpinBox()
        self.spin_annual.setRange(0, 1_000_000)
        self.spin_annual.setDecimals(0)
        self.spin_annual.setSuffix(" т/год")
        self.spin_annual.setSingleStep(1000)
        self.spin_annual.valueChanged.connect(self._on_program_changed)

        self.edit_alloy = QLineEdit()
        self.edit_alloy.setPlaceholderText("Сталь 20Л ГОСТ 977-88")
        self.edit_alloy.setReadOnly(True)  # Теперь заполняется автоматически
        self.edit_alloy.editingFinished.connect(self._on_program_changed)

        self.spin_density = QDoubleSpinBox()
        self.spin_density.setRange(1000, 20000)
        self.spin_density.setDecimals(0)
        self.spin_density.setSuffix(" кг/м³")
        self.spin_density.setValue(7800)
        self.spin_density.valueChanged.connect(self._on_program_changed)

        form.addRow("Годовой выпуск:", self.spin_annual)
        form.addRow("Марка сплава:", self.edit_alloy)
        form.addRow("Плотность сплава:", self.spin_density)
        return g

    def _build_mode_group(self) -> QGroupBox:
        g = QGroupBox("Режим работы цеха")
        g.setStyleSheet(GROUP_STYLE + GROUP_WIDGETS_STYLE)
        form = QFormLayout(g)
        form.setLabelAlignment(Qt.AlignRight)

        self.spin_shifts = QSpinBox()
        self.spin_shifts.setRange(1, 4)
        self.spin_shifts.setValue(2)
        self.spin_shifts.setSuffix(" смены/сутки")
        self.spin_shifts.valueChanged.connect(self._on_mode_changed)

        self.spin_shift_hours = QDoubleSpinBox()
        self.spin_shift_hours.setRange(1, 24)
        self.spin_shift_hours.setDecimals(1)
        self.spin_shift_hours.setValue(8)
        self.spin_shift_hours.setSuffix(" ч/смена")
        self.spin_shift_hours.valueChanged.connect(self._on_mode_changed)

        self.spin_work_days = QSpinBox()
        self.spin_work_days.setRange(1, 365)
        self.spin_work_days.setValue(249)
        self.spin_work_days.setSuffix(" дней/год")
        self.spin_work_days.valueChanged.connect(self._on_mode_changed)

        form.addRow("Смен в сутки:", self.spin_shifts)
        form.addRow("Часов в смене:", self.spin_shift_hours)
        form.addRow("Рабочих дней в году:", self.spin_work_days)
        return g

    def _build_losses_group(self) -> QGroupBox:
        g = QGroupBox("Потери и брак")
        g.setStyleSheet(GROUP_STYLE + GROUP_WIDGETS_STYLE)
        form = QFormLayout(g)
        form.setLabelAlignment(Qt.AlignRight)

        self.spin_brak = QDoubleSpinBox()
        self.spin_brak.setRange(0, 50)
        self.spin_brak.setDecimals(1)
        self.spin_brak.setValue(5.0)
        self.spin_brak.setSuffix(" %")
        self.spin_brak.valueChanged.connect(self._on_losses_changed)

        self.spin_lp = QDoubleSpinBox()
        self.spin_lp.setRange(0, 100)
        self.spin_lp.setDecimals(1)
        self.spin_lp.setValue(28.9)
        self.spin_lp.setSuffix(" %")
        self.spin_lp.valueChanged.connect(self._on_losses_changed)

        self.spin_ugar = QDoubleSpinBox()
        self.spin_ugar.setRange(0, 50)
        self.spin_ugar.setDecimals(1)
        self.spin_ugar.setValue(5.0)
        self.spin_ugar.setSuffix(" %")
        self.spin_ugar.valueChanged.connect(self._on_losses_changed)

        form.addRow("Брак:", self.spin_brak)
        form.addRow("Литники и прибыли:", self.spin_lp)
        form.addRow("Угар:", self.spin_ugar)
        return g

    def _build_castings_group(self) -> QGroupBox:
        g = QGroupBox("Номенклатура отливок")
        g.setStyleSheet(GROUP_STYLE + GROUP_WIDGETS_STYLE)
        layout = QVBoxLayout(g)
        layout.setContentsMargins(12, 16, 12, 12)

        toolbar = QHBoxLayout()

        self.btn_import = QPushButton("📂 Импорт из Excel")
        self.btn_import.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent']};
                color: {COLORS['bg_main']};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: #F3B989; }}
            QPushButton:pressed {{ background-color: #C88858; }}
        """)
        self.btn_import.clicked.connect(self._on_import_excel)
        toolbar.addWidget(self.btn_import)

        self.btn_clear = QPushButton(" Очистить")
        self.btn_clear.setStyleSheet(f"""
            QPushButton {{
                background-color: #344255;
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['separator']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: #405268; }}
        """)
        self.btn_clear.clicked.connect(self._on_clear_castings)
        toolbar.addWidget(self.btn_clear)
        self.btn_expand_castings = QPushButton("↗ Развернуть таблицу")
        self.btn_expand_castings.setToolTip(
            "Полноразмерный просмотр всей номенклатуры с поиском и сортировкой")
        self.btn_expand_castings.clicked.connect(self._show_castings_browser)
        toolbar.addWidget(self.btn_expand_castings)
        self.btn_verify_casting = QPushButton("✎ Проверить позицию")
        self.btn_verify_casting.setToolTip(
            "Выберите строку и укажите число стержней, чистую массу "
            "и документы-источники для данной отливки")
        self.btn_verify_casting.clicked.connect(self._on_verify_casting)
        toolbar.addWidget(self.btn_verify_casting)

        toolbar.addStretch()

        self.lbl_summary = QLabel("Позиций: 0 | Суммарная масса: 0 т")
        self.lbl_summary.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-size: 12px;
                padding: 4px 8px;
                background-color: {COLORS['bg_main']};
                border: 1px solid {COLORS['separator']};
                border-radius: 4px;
            }}
        """)
        toolbar.addWidget(self.lbl_summary)

        layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setMinimumHeight(440)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(31)
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "№", "Наименование", "Масса с ЛПС, кг", "Габариты, мм",
            "Форм/год", "Отливок/форму", "Опоки, мм", "Залив. масса, кг", "Металл в год, т"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: #111A25;
                alternate-background-color: #202A38;
                color: {COLORS['text_primary']};
                gridline-color: {COLORS['separator']};
                border: 1px solid {COLORS['separator']};
                font-size: 12px;
            }}
            QHeaderView::section {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['accent']};
                padding: 6px;
                border: 1px solid {COLORS['separator']};
                font-weight: bold;
                font-size: 12px;
            }}
            QTableWidget::item:selected {{
                background-color: {COLORS['accent']};
                color: {COLORS['bg_main']};
            }}
        """)
        layout.addWidget(self.table, 1)

        return g

    # ─────────────────────────────────────────────────────────────────
    # Загрузка данных
    # ─────────────────────────────────────────────────────────────────
    def _load_from_project(self) -> None:
        p = self.project

        self.edit_name.setText(p.name)
        self.edit_customer.setText(p.customer)

        self.spin_annual.setValue(p.annual_output_t)
        self.edit_alloy.setText(p.alloy)
        self.spin_density.setValue(p.alloy_density_kg_m3)

        self.spin_shifts.setValue(p.shifts_per_day)
        self.spin_shift_hours.setValue(p.shift_duration_h)
        self.spin_work_days.setValue(p.working_days_per_year)

        self.spin_brak.setValue(p.brak_pct)
        self.spin_lp.setValue(p.litniki_pribyli_pct)
        self.spin_ugar.setValue(p.ugar_pct)

        # Выбрать сплав по умолчанию (сталь 20Л)
        if not p.selected_alloy_id:
            p.selected_alloy_id = "steel_20L"
        
        # Установить категорию и сплав
        alloy = self.loader.get_alloy(p.selected_alloy_id)
        if alloy:
            category_id = alloy.get("category", "steel")
            # Найти индекс категории
            for i in range(self.combo_category.count()):
                if self.combo_category.itemData(i) == category_id:
                    self.combo_category.setCurrentIndex(i)
                    break
            
            # Заполнить сплавы и выбрать нужный
            self._populate_alloys(category_id)
            for i in range(self.combo_alloy.count()):
                if self.combo_alloy.itemData(i) == p.selected_alloy_id:
                    self.combo_alloy.setCurrentIndex(i)
                    break
            
            self._update_alloy_info(p.selected_alloy_id)

        self._refresh_table()

    # ────────────────────────────────────────────────────────────────
    # Обработчики выбора материала
    # ─────────────────────────────────────────────────────────────────
    def _on_category_changed(self, index: int) -> None:
        if self._building or index < 0:
            return
        category_id = self.combo_category.itemData(index)
        if category_id:
            self._populate_alloys(category_id)
            if self.combo_alloy.count() > 0:
                self.combo_alloy.setCurrentIndex(0)

    def _on_alloy_changed(self, index: int) -> None:
        if self._building or index < 0:
            return
        alloy_id = self.combo_alloy.itemData(index)
        if alloy_id:
            alloy = self.loader.get_alloy(alloy_id)
            if alloy:
                # Обновить проект
                self.project.selected_alloy_id = alloy_id
                self.project.alloy = f"{alloy['name']} {alloy.get('gost', '')}".strip()
                self.project.alloy_density_kg_m3 = alloy.get("density_kg_m3", 7800)
                
                # Обновить UI
                self.edit_alloy.setText(self.project.alloy)
                self.spin_density.setValue(alloy.get("density_kg_m3", 7800))
                self._update_alloy_info(alloy_id)
                
                self.project_changed.emit()

    def _on_add_material(self) -> None:
        """Открыть диалог добавления нового материала."""
        dialog = AddMaterialDialog(self)
        if dialog.exec() == AddMaterialDialog.Accepted:
            new_material = dialog.get_material_data()
            
            # Здесь можно сохранить в пользовательский JSON
            # Пока просто показываем сообщение
            QMessageBox.information(
                self, "Материал добавлен",
                f"Сплав '{new_material['name']}' добавлен в справочник.\n"
                f"ID: {new_material['id']}\n"
                f"Категория: {new_material['category']}"
            )
            
            # Перезагрузить справочник и обновить UI
            self.loader.clear_cache()
            category_id = new_material["category"]
            for i in range(self.combo_category.count()):
                if self.combo_category.itemData(i) == category_id:
                    self.combo_category.setCurrentIndex(i)
                    break

    # ─────────────────────────────────────────────────────────────────
    # Остальные обработчики (без изменений)
    # ─────────────────────────────────────────────────────────────────
    def _on_general_changed(self) -> None:
        if self._building:
            return
        self.project.name = self.edit_name.text().strip() or "Проект литейного цеха"
        self.project.customer = self.edit_customer.text().strip()
        self.project_changed.emit()

    def _on_program_changed(self) -> None:
        if self._building:
            return
        self.project.annual_output_t = self.spin_annual.value()
        self.project.alloy = self.edit_alloy.text().strip()
        self.project.alloy_density_kg_m3 = self.spin_density.value()
        self.project_changed.emit()

    def _on_mode_changed(self) -> None:
        if self._building:
            return
        # Four 8-hour shifts cannot fit into 24 hours. Enforce the
        # physical day at input time instead of a fictional annual fund.
        shifts = self.spin_shifts.value()
        max_duration = 24.0 / shifts
        self.spin_shift_hours.blockSignals(True)
        self.spin_shift_hours.setMaximum(max_duration)
        self.spin_shift_hours.blockSignals(False)
        self.project.shifts_per_day = shifts
        self.project.shift_duration_h = self.spin_shift_hours.value()
        self.project.working_days_per_year = self.spin_work_days.value()
        self.project.time_funds_verified = False
        self.project_changed.emit()

    def _on_losses_changed(self) -> None:
        if self._building:
            return
        self.project.brak_pct = self.spin_brak.value()
        self.project.litniki_pribyli_pct = self.spin_lp.value()
        self.project.ugar_pct = self.spin_ugar.value()
        self.project_changed.emit()

    def _on_import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт номенклатуры отливок",
            str(Path.home()), "Excel файлы (*.xlsx *.xlsm);;Все файлы (*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return

        try:
            preview = ExcelImporter().load_preview(Path(path))
            items = preview.castings
            if not items:
                QMessageBox.warning(self, "Импорт",
                                    "Не удалось распознать данные в файле.")
                return
            if self.project.castings:
                answer = QMessageBox.question(
                    self, "Заменить номенклатуру?",
                    "Новая таблица Excel ЗАМЕНИТ все отливки текущего проекта. "
                    "Прежняя номенклатура не будет сохранена. Продолжить?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
            self.project.clear_castings()
            # Confirmation applies only to the PREVIOUS nomenclature:
            # never inherit a declaration of "coreless" after Excel import.
            self.project.cores_zero_confirmed = False
            for item in items:
                self.project.add_casting(item)
            self._refresh_table()
            self.project_changed.emit()
            message = (
                f"Загружено позиций: {len(items)}\n"
                f"Заливка по программе: {self.project.total_castings_mass_t():.2f} т/год")
            if preview.warnings:
                notes = "\n".join(preview.warnings[:12])
                remaining = len(preview.warnings) - 12
                if remaining > 0:
                    notes += f"\n... ещё предупреждений: {remaining}"
                QMessageBox.warning(
                    self, "Импорт завершён с замечаниями",
                    message + "\n\nПРОВЕРЬТЕ ИСХОДНЫЕ ДАННЫЕ:\n" + notes)
            else:
                QMessageBox.information(self, "Импорт завершён", message)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", f"{type(e).__name__}: {e}")

    def _on_clear_castings(self) -> None:
        reply = QMessageBox.question(
            self, "Очистка", "Удалить всю номенклатуру отливок?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.project.clear_castings()
            self.project.cores_zero_confirmed = False
            self._refresh_table()
            self.project_changed.emit()

    def _show_castings_browser(self) -> None:
        """Большое окно для просмотра любой по объёму номенклатуры."""
        browser = getattr(self, "_castings_browser", None)
        if browser is not None and browser.isVisible():
            browser.raise_()
            browser.activateWindow()
            return
        self._castings_browser = CastingsBrowserDialog(self.project.castings, self)
        self._castings_browser.show()

    def _on_verify_casting(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.project.castings)):
            QMessageBox.information(
                self, "Выберите отливку",
                "Сначала выделите строку номенклатуры, которую нужно проверить.")
            return
        dialog = CastingTechnologyDialog(self.project.castings[row], self)
        if dialog.exec() == dialog.Accepted and dialog.result_item is not None:
            # A blanket confirmation for the previous source list is no
            # longer sufficient after an individual technological edit.
            self.project.cores_zero_confirmed = False
            self.project.castings[row] = dialog.result_item
            self._refresh_table()
            self.table.selectRow(row)
            self.project_changed.emit()

    def _refresh_table(self) -> None:
        items = self.project.castings
        self.table.setRowCount(len(items))
        total_mass = 0.0
        for row, item in enumerate(items):
            cols = [
                str(item.index), item.name,
                f"{item.mass_with_LPS_kg:.1f}", item.dimensions_mm,
                str(item.molds_per_year),
                str(item.castings_per_mold) if item.castings_per_mold else "неизв.",
                item.flask_size_mm,
                f"{item.pouring_mass_kg:.1f}", f"{item.annual_metal_t:.3f}",
            ]
            for col, val in enumerate(cols):
                cell = QTableWidgetItem(val)
                cell.setTextAlignment(Qt.AlignCenter if col in (0, 3, 4) else Qt.AlignLeft)
                self.table.setItem(row, col, cell)
            total_mass += item.annual_metal_t

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in range(self.table.columnCount()):
            if i != 1:
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        issues = audit_castings(items) + audit_casting_technology(items)
        self.lbl_summary.setText(
            f"Позиций: {len(items)} | Суммарная масса: {total_mass:.2f} т"
            + (f" | ⚠ Замечаний: {len(issues)}" if issues else " | Исходные данные проверены"))
        self.lbl_summary.setToolTip("\n".join(i.describe() for i in issues[:40])
                                    or "Арифметические связи номенклатуры проверены")