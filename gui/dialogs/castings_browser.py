"""Полноразмерный просмотр номенклатуры с поиском и сортировкой."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt

from core.casting_audit import audit_castings
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableView, QHeaderView, QAbstractItemView, QApplication,
)

_HEADERS = (
    "№", "Наименование", "Масса с ЛПС, кг", "Габариты, мм",
    "Форм/год", "Отливок/форму", "Опоки, мм", "Залив. масса, кг",
    "Металл/год, т", "Проверка",
)


class CastingsTableModel(QAbstractTableModel):
    """QTableView работает быстро и не создаёт тысячи QTableWidgetItem."""

    def __init__(self, castings, parent=None):
        super().__init__(parent)
        self._castings = list(castings)
        self._issues = {}
        for issue in audit_castings(self._castings):
            self._issues.setdefault(issue.row - 1, []).append(issue)

    def rowCount(self, parent=None):  # noqa: N802
        return 0 if parent and parent.isValid() else len(self._castings)

    def columnCount(self, parent=None):  # noqa: N802
        return 0 if parent and parent.isValid() else len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _HEADERS[section]
        if role == Qt.DisplayRole and orientation == Qt.Vertical:
            return str(section + 1)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._castings):
            return None
        if role == Qt.ToolTipRole:
            return "\n".join(i.message for i in self._issues.get(index.row(), [])) or "Проверено по доступным полям"
        if role not in (Qt.DisplayRole, Qt.UserRole):
            if role == Qt.TextAlignmentRole:
                return (Qt.AlignLeft | Qt.AlignVCenter) if index.column() in (
                    1, 3, 6, 9) else (Qt.AlignRight | Qt.AlignVCenter)
            return None
        casting = self._castings[index.row()]
        values = (
            getattr(casting, "index", ""),
            getattr(casting, "name", ""),
            getattr(casting, "mass_with_LPS_kg", 0.0),
            getattr(casting, "dimensions_mm", ""),
            getattr(casting, "molds_per_year", 0),
            getattr(casting, "castings_per_mold", 0),
            getattr(casting, "flask_size_mm", ""),
            getattr(casting, "pouring_mass_kg", 0.0),
            getattr(casting, "annual_metal_t", 0.0),
            len(self._issues.get(index.row(), [])),
        )
        value = values[index.column()]
        if role == Qt.UserRole:
            return value
        if index.column() == 9:
            return "✓" if not value else f"⚠ {value}"
        if index.column() == 5 and not value:
            return "неизвестно"
        if index.column() in (4, 5):
            return f"{int(value):,}".replace(",", " ")
        if index.column() in (2, 7, 8):
            return f"{float(value):,.3f}".replace(",", " ")
        return str(value)


class CastingsBrowserDialog(QDialog):
    """Большая таблица; данные проекта не меняет."""

    def __init__(self, castings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Номенклатура отливок — полный просмотр")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(720, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.info = QLabel(
            f"Всего отливок: {len(castings)}. Поиск по названию, размерам "
            "опок и другим полям. Щёлкните заголовок для сортировки.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Поиск по всем столбцам…")
        controls.addWidget(self.search, 1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        controls.addWidget(close)
        layout.addLayout(controls)

        self.table = QTableView()
        self.table.setObjectName("castingsExplorerTable")
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.verticalHeader().setVisible(False)
        self.model = CastingsTableModel(castings, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setSortRole(Qt.UserRole)
        self.table.setModel(self.proxy)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        for col, width in enumerate((65, 270, 150, 140, 120, 130, 170, 150, 160, 100)):
            self.table.setColumnWidth(col, width)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        layout.addWidget(self.table, 1)

        screen = QApplication.primaryScreen()
        if screen is not None:
            rect = screen.availableGeometry()
            self.resize(
                max(720, min(1500, int(rect.width() * .94))),
                max(460, min(900, int(rect.height() * .88))),
            )
        else:
            self.resize(1400, 820)
